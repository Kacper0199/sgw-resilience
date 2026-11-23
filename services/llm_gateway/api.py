from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from opentelemetry import trace

from .budget import BudgetGuard
from .callers import CALLERS_FILE, Caller, CallerRegistry, load_callers
from .calls import CallSink, LlmCallRecord, make_sink, new_call_id
from .canonical import canonical_request, request_hash
from .config import Mode, Settings
from .control import ControlGate, make_gate
from .egress import (
    Detectors,
    EgressDecision,
    EgressInput,
    EgressPDP,
    OpaEgress,
    ReferenceEgress,
    outbound_text,
    request_betas,
    request_source_types,
    request_tool_types,
)
from .policy import NodeAllowlist, PolicyViolation, check_payload
from .prices import cost_usd, usage_tokens, worst_case_cost_usd
from .recording import Recording, RecordingStore, ReplayMiss, now_iso, validate_node
from .redact import (
    KEY_PATTERN,
    KeyLeakError,
    MissingClassesError,
    max_class,
    may_store_verbatim,
    parse_classes,
    redact_for_log,
    scrub_text,
)
from .spend import CallRow, SpendLedger
from .sse import SSEAccumulator, SSEOutputGuard, encode_event, synthesize_events
from .upstream import Upstream, UpstreamPostSendError

log = logging.getLogger("sgw.llm_gateway")
tracer = trace.get_tracer("sgw.llm_gateway")

PURPOSES = frozenset({"spike", "dev", "eval", "redteam", "record", "demo", "test"})
TAG_PATTERNS = {
    "x-sgw-run": re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$|^$"),
    "x-sgw-wave": re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,15}$"),
    "x-sgw-prompt-version": re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:-]{0,63}$|^$"),
}


def _tag(headers: Any, name: str, *, required: bool = False) -> str:
    value = headers.get(name, "")
    if required and not value:
        raise PolicyViolation(name.removeprefix("x-").replace("-", "_"), f"{name} is required")
    if not TAG_PATTERNS[name].match(value) or KEY_PATTERN.search(value):
        raise PolicyViolation("sgw_bad_tag", f"{name} must match {TAG_PATTERNS[name].pattern}")
    return value


HASH_HEADER = "x-sgw-request-hash"
CALL_ID_HEADER = "x-sgw-call-id"
EGRESS_HEADER = "x-sgw-egress"
BUDGET_HEADER = "x-sgw-budget"
OUTPUT_CANARY_CODE = "sgw_output_canary_blocked"
OUTPUT_SECRET_CODE = "sgw_key_leak_blocked"  # noqa: S105 - error type, not a secret


def error_response(code: str, message: str, status: int, **extra: str) -> JSONResponse:
    body = {"type": "error", "error": {"type": code, "message": scrub_text(message)}}
    return JSONResponse(body, status_code=status, headers=extra)


class CallContext:
    def __init__(self, request: Request, body: dict[str, Any]) -> None:
        h = request.headers
        self.headers = {k.lower(): v for k, v in h.items()}
        self.node = validate_node(h.get("x-sgw-node", ""))
        self.run_id = _tag(h, "x-sgw-run")
        self.purpose = h.get("x-sgw-purpose", "")
        if self.purpose not in PURPOSES:
            raise PolicyViolation("sgw_purpose", f"x-sgw-purpose must be one of {sorted(PURPOSES)}")
        self.wave = _tag(h, "x-sgw-wave", required=True)
        try:
            self.classes = parse_classes(h.get("x-sgw-classes"))
        except MissingClassesError as exc:
            raise PolicyViolation("sgw_classes_missing", str(exc)) from exc
        self.prompt_version = _tag(h, "x-sgw-prompt-version")
        deadline = h.get("x-sgw-deadline-s")
        try:
            self.deadline_s = float(deadline) if deadline else None
        except ValueError as exc:
            raise PolicyViolation("sgw_bad_tag", "x-sgw-deadline-s must be a number") from exc
        if self.deadline_s is not None and not 0 < self.deadline_s <= 600:
            raise PolicyViolation("sgw_bad_tag", "x-sgw-deadline-s must be in (0, 600]")
        self.body = body
        self.model = body.get("model", "")
        self.effort = (body.get("output_config") or {}).get("effort", "")
        self.stream = bool(body.get("stream"))
        self.started = time.monotonic()
        self.call_id = new_call_id()
        self.request_hash = ""
        self.payload_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        self.decision: EgressDecision | None = None
        self.recorded = False
        self.caller: Caller | None = None
        self.served_mode = ""

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)


class Gateway:
    def __init__(
        self,
        settings: Settings,
        upstream: Upstream,
        *,
        sink: CallSink | None = None,
        opa_transport: httpx.AsyncBaseTransport | None = None,
        control: ControlGate | None = None,
    ) -> None:
        self.settings = settings
        self.callers = CallerRegistry(
            settings.caller_token_digests,
            load_callers(settings.callers_file or CALLERS_FILE),
            accept_test_tokens=settings.accept_test_tokens,
        )
        self.control: ControlGate = control if control is not None else make_gate(settings.llm_call_dsn)
        secrets = (settings.api_key,)
        self.store = RecordingStore(settings.fixture_dir, secrets=secrets)
        self.live_cache = RecordingStore(settings.live_cache_dir, secrets=secrets)
        self.ledger = SpendLedger(settings.spend_csv, secrets=secrets)
        self.budget = BudgetGuard(settings, self.ledger)
        self.allowlist = NodeAllowlist.load(settings.nodes_file)
        self.upstream = upstream
        self.detectors = Detectors(settings.canary_tokens)
        self.egress: EgressPDP = (
            OpaEgress(settings.opa_url, transport=opa_transport)
            if settings.resolved_pdp() == "opa" and settings.opa_url
            else ReferenceEgress()
        )
        self.sink: CallSink = sink if sink is not None else make_sink(settings.llm_call_dsn)
        self.counters = {
            "replay_hits": 0,
            "live_cache_hits": 0,
            "replay_misses": 0,
            "live_calls": 0,
            "egress_denied": 0,
            "output_blocked": 0,
        }

    def _row(
        self,
        ctx: CallContext,
        message: dict[str, Any] | None,
        *,
        billed: bool,
        req_hash: str,
        attempts: int,
        status: int,
    ) -> CallRow:
        usage = usage_tokens((message or {}).get("usage") or {})
        cost = cost_usd(ctx.model, (message or {}).get("usage") or {}) if billed and message else 0.0
        return CallRow(
            ts=now_iso(),
            mode=self._served(ctx),
            purpose=ctx.purpose,
            wave=ctx.wave,
            run_id=ctx.run_id,
            node=ctx.node,
            prompt_version=ctx.prompt_version,
            model=ctx.model,
            effort=ctx.effort,
            batch=False,
            input_tokens=usage["input_tokens"],
            cache_creation_input_tokens=usage["cache_creation_input_tokens"],
            cache_read_input_tokens=usage["cache_read_input_tokens"],
            output_tokens=usage["output_tokens"],
            stop_reason=str((message or {}).get("stop_reason") or ""),
            latency_ms=ctx.elapsed_ms(),
            cost_usd=cost,
            request_hash=req_hash,
            billed=billed,
            attempts=attempts,
            status=status,
        )

    def _log(self, event: str, **fields: Any) -> None:
        log.info(json.dumps(redact_for_log({"event": event, **fields}), default=str))

    def _finish(
        self,
        ctx: CallContext,
        req_hash: str,
        message: dict[str, Any] | None,
        attempts: int,
        status: int,
        *,
        reservation: int | None = None,
        estimate_usd: float | None = None,
        estimate_reason: str = "incomplete_stream_worst_case",
        deny_code: str | None = None,
    ) -> CallRow:
        try:
            billed = status == 200 and message is not None and bool(message.get("usage"))
            row = self._row(ctx, message, billed=billed, req_hash=req_hash, attempts=attempts, status=status)
            if not billed and estimate_usd is not None:
                row.billed = True
                row.cost_usd = estimate_usd
                row.stop_reason = estimate_reason
            self.ledger.append(row)
        finally:
            self.budget.release(reservation)
        ctx.recorded = True
        self._submit(ctx, row=row, deny_code=deny_code)
        target = {Mode.RECORD: self.store, Mode.REPLAY_THEN_LIVE: self.live_cache}.get(self.settings.mode)
        if (
            deny_code is None
            and billed
            and message is not None
            and target is not None
            and message.get("stop_reason") is not None
        ):
            canonical = canonical_request(ctx.body, ctx.headers)
            target.save(
                Recording(
                    node=ctx.node,
                    request_sha256=req_hash,
                    prompt_version=ctx.prompt_version or None,
                    model=ctx.model,
                    data_classes=ctx.classes,
                    request=canonical["body"] if may_store_verbatim(ctx.classes) else None,
                    request_headers=canonical["headers"],
                    response=message,
                    cost_usd_at_record=row.cost_usd,
                    latency_ms=row.latency_ms,
                    recorded_at=row.ts,
                )
            )
        self._log("llm_call", **{k: v for k, v in row.__dict__.items()})
        span = trace.get_current_span()
        span.set_attribute("gen_ai.usage.input_tokens", row.input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", row.output_tokens)
        span.set_attribute("sgw.cost_usd", row.cost_usd)
        return row

    def _served(self, ctx: CallContext) -> str:
        """The K1 `llm_call.mode` of this call: `replay_then_live` logs each call as what it was."""
        if self.settings.mode is Mode.REPLAY_THEN_LIVE:
            return ctx.served_mode or Mode.LIVE.value
        return self.settings.mode.value

    def _cached(self, ctx: CallContext, req_hash: str) -> tuple[RecordingStore, str] | None:
        for store, source in ((self.store, "fixtures"), (self.live_cache, "live_cache")):
            if store.exists(ctx.node, req_hash):
                return store, source
        return None

    def _submit(
        self,
        ctx: CallContext,
        *,
        row: CallRow | None = None,
        deny_code: str | None = None,
        message: dict[str, Any] | None = None,
        stop_reason: str = "",
    ) -> None:
        usage = usage_tokens((message or {}).get("usage") or {}) if row is None else {}
        record = LlmCallRecord(
            call_id=ctx.call_id,
            ts=row.ts if row else now_iso(),
            mode=self._served(ctx),
            billed=row.billed if row else False,
            purpose=ctx.purpose,
            wave=ctx.wave,
            run_id=ctx.run_id,
            node=ctx.node,
            prompt_version=ctx.prompt_version,
            model=ctx.model,
            effort=ctx.effort,
            route=self.settings.egress_route,
            classes=tuple(ctx.classes),
            decision="deny" if deny_code else "allow",
            request_hash=ctx.request_hash,
            payload_hash=ctx.payload_hash,
            input_tokens=row.input_tokens if row else usage.get("input_tokens", 0),
            cache_creation_input_tokens=(
                row.cache_creation_input_tokens if row else usage.get("cache_creation_input_tokens", 0)
            ),
            cache_read_input_tokens=row.cache_read_input_tokens
            if row
            else usage.get("cache_read_input_tokens", 0),
            output_tokens=row.output_tokens if row else usage.get("output_tokens", 0),
            stop_reason=deny_code or (row.stop_reason if row else stop_reason),
            latency_ms=row.latency_ms if row else ctx.elapsed_ms(),
            cost_usd=row.cost_usd if row else 0.0,
        )
        try:
            self.sink.submit(record)
        except Exception as exc:  # noqa: BLE001
            self._log("llm_call_sink_submit_failed", error=type(exc).__name__)

    async def _gate(self, ctx: CallContext) -> None:
        """One egress decision per call, before any fixture lookup or network request."""
        rule = self.allowlist.rule_for(ctx.node)
        hits = self.detectors.scan(outbound_text(ctx.body))
        inp = EgressInput(
            route=self.settings.egress_route,
            node=ctx.node,
            model=ctx.model,
            classes=tuple(ctx.classes),
            node_rule=rule,
            betas=request_betas(ctx.headers),
            tool_types=request_tool_types(ctx.body),
            source_types=request_source_types(ctx.body),
            pseudonymized=self._pseudonymized(ctx, rule),
            detectors=hits,
        )
        decision = await self.egress.decide(inp)
        ctx.decision = decision
        span = trace.get_current_span()
        span.set_attribute("sgw.egress.decision", "allow" if decision.allow else "deny")
        span.set_attribute("sgw.egress.pdp", decision.pdp)
        span.set_attribute("sgw.egress.policy_version", decision.policy_version)
        if not decision.allow:
            self.counters["egress_denied"] += 1
            span.set_attribute("sgw.egress.deny", ",".join(decision.deny))
            self._log("egress_denied", node=ctx.node, deny=list(decision.deny), pdp=decision.pdp)
        decision.raise_if_denied()

    def _output_violation(self, message: dict[str, Any] | None) -> str | None:
        if not message:
            return None
        hits = self.detectors.scan_json(message.get("content") or [])
        if hits.secret_hits:
            return OUTPUT_SECRET_CODE
        if hits.canary_hits:
            return OUTPUT_CANARY_CODE
        return None

    def _output_blocked(self, ctx: CallContext, code: str) -> JSONResponse:
        self.counters["output_blocked"] += 1
        self._log("output_blocked", node=ctx.node, code=code)
        trace.get_current_span().set_attribute("sgw.output.blocked", code)
        message = (
            "an Anthropic key-shaped token was in the model output; withheld"
            if code == OUTPUT_SECRET_CODE
            else "a canary token was in the model output; withheld (SEC-33)"
        )
        return error_response(code, message, 502)

    def _tag_response(self, response: Response, ctx: CallContext | None) -> Response:
        response.headers[BUDGET_HEADER] = self.budget.level()
        if ctx is not None:
            response.headers[CALL_ID_HEADER] = ctx.call_id
            if ctx.decision is not None:
                response.headers[EGRESS_HEADER] = "allow" if ctx.decision.allow else "deny"
        return response

    def _pseudonymized(self, ctx: CallContext, rule: Any) -> bool:
        """`x-sgw-pseudonymized` counts only from a C2-capable service, for a node whose rule lists R2."""
        claimed = ctx.headers.get("x-sgw-pseudonymized", "") == "1"
        allowed = (
            ctx.caller is not None and ctx.caller.may_send_c2 and rule is not None and "R2" in rule.routes
        )
        if claimed and not allowed:
            self._log(
                "pseudonymized_claim_ignored", node=ctx.node, caller=ctx.caller.service if ctx.caller else ""
            )
        return claimed and allowed

    async def handle(self, request: Request) -> Response:
        try:
            body = json.loads(await request.body())
        except json.JSONDecodeError:
            return error_response("invalid_request_error", "body is not JSON", 400)
        if not isinstance(body, dict):
            return error_response("invalid_request_error", "body must be a JSON object", 400)
        with tracer.start_as_current_span("llm_gateway.messages") as span:
            ctx: CallContext | None = None
            try:
                caller = self.callers.authenticate({k.lower(): v for k, v in request.headers.items()})
                span.set_attribute("sgw.caller", caller.service)
                ctx = CallContext(request, body)
                ctx.caller = caller
                self.callers.authorize(caller, ctx.node)
                span.set_attribute("gen_ai.system", "anthropic")
                span.set_attribute("gen_ai.request.model", ctx.model)
                span.set_attribute("sgw.run_id", ctx.run_id or "none")
                span.set_attribute("sgw.classification", max_class(ctx.classes))
                span.set_attribute("sgw.user_role", "service:llm_gateway")
                span.set_attribute("sgw.run_mode", "replay" if self.settings.mode is Mode.REPLAY else "live")
                span.set_attribute("sgw.node", ctx.node)
                span.set_attribute("sgw.wave", ctx.wave)
                span.set_attribute("sgw.purpose", ctx.purpose)
                span.set_attribute("sgw.call_id", ctx.call_id)
                span.set_attribute("sgw.route", self.settings.egress_route)
                span.set_attribute("sgw.mode", self.settings.mode.value)
                ctx.request_hash = _safe_request_hash(body, ctx.headers)
                span.set_attribute("sgw.request_hash", ctx.request_hash)
                check_payload(body)
                await asyncio.to_thread(self.control.check)
                await self._gate(ctx)
                req_hash = ctx.request_hash
                if self.settings.mode is Mode.REPLAY:
                    return self._tag_response(await self._replay(ctx, req_hash, pace=True), ctx)
                if self.settings.mode is Mode.REPLAY_THEN_LIVE and (found := self._cached(ctx, req_hash)):
                    ctx.served_mode = Mode.REPLAY.value
                    return self._tag_response(await self._replay(ctx, req_hash, *found, pace=True), ctx)
                if (
                    self.settings.mode is Mode.RECORD
                    and not self.settings.record_overwrite
                    and self.store.exists(ctx.node, req_hash)
                ):
                    return self._tag_response(await self._replay(ctx, req_hash), ctx)
                return self._tag_response(await self._live(ctx, req_hash), ctx)
            except PolicyViolation as exc:
                self._log("llm_denied", code=exc.code, status=exc.status)
                if ctx is not None and not ctx.recorded:
                    self._submit(ctx, deny_code=exc.code)
                return self._tag_response(error_response(exc.code, exc.message, exc.status), ctx)
            except KeyLeakError as exc:
                self._log("key_leak_blocked", node=ctx.node if ctx else "")
                return self._tag_response(error_response("sgw_key_leak_blocked", str(exc), 502), ctx)
            except ValueError as exc:
                return self._tag_response(error_response("invalid_request_error", str(exc), 400), ctx)

    async def _replay(
        self,
        ctx: CallContext,
        req_hash: str,
        store: RecordingStore | None = None,
        source: str = "fixtures",
        *,
        pace: bool = False,
    ) -> Response:
        """A recorded answer. With `pace` and LLM_REPLAY_PACE_MAX_S set, it is served after the time the live
        call took when it was recorded (capped), so a replayed answer takes as long as the real one did."""
        try:
            fixture = (store or self.store).load(ctx.node, req_hash)
        except ReplayMiss as exc:
            self.counters["replay_misses"] += 1
            self._log("replay_miss", node=ctx.node, request_hash=req_hash)
            ctx.recorded = True
            self._submit(ctx, stop_reason="sgw_replay_miss")
            return error_response("sgw_replay_miss", str(exc), 424, **{HASH_HEADER: req_hash})
        self.counters["live_cache_hits" if source == "live_cache" else "replay_hits"] += 1
        message = fixture["response"]
        ctx.recorded = True
        if code := self._output_violation(message):
            self._submit(ctx, deny_code=code, message=message)
            return self._output_blocked(ctx, code)
        cap = self.settings.replay_pace_max_s
        if pace and cap > 0:
            recorded_s = min(int(fixture.get("latency_ms") or 0) / 1000, cap)
            await asyncio.sleep(max(0.0, recorded_s - ctx.elapsed_ms() / 1000))
        self._submit(ctx, message=message, stop_reason=str(message.get("stop_reason") or ""))
        headers = {HASH_HEADER: req_hash, "x-sgw-replay": "hit", "x-sgw-replay-source": source}
        if ctx.stream:
            return StreamingResponse(
                _iter(synthesize_events(message)), media_type="text/event-stream", headers=headers
            )
        return JSONResponse(message, headers=headers)

    async def _live(self, ctx: CallContext, req_hash: str) -> Response:
        if not self.settings.api_key:
            raise PolicyViolation("sgw_no_key", "gateway has no ANTHROPIC_API_KEY for a live call", 503)
        raw = json.dumps(ctx.body).encode()
        worst_case = worst_case_cost_usd(ctx.model, len(raw) // 3, ctx.body["max_tokens"])
        token = self.budget.reserve(wave=ctx.wave, worst_case_usd=worst_case)
        handed_off = False
        try:
            deadline = ctx.deadline_s or self.settings.default_deadline_s
            try:
                result = await self.upstream.send(raw, ctx.headers, stream=ctx.stream, deadline_s=deadline)
            except UpstreamPostSendError as exc:
                self.counters["live_calls"] += 1
                self._finish(
                    ctx,
                    req_hash,
                    None,
                    exc.attempts,
                    504,
                    reservation=token,
                    estimate_usd=worst_case,
                    estimate_reason="post_send_failure_worst_case",
                )
                return error_response("sgw_upstream_post_send_failure", str(exc), 504)
            except PolicyViolation as exc:
                if exc.code == "sgw_upstream_unreachable":
                    self._finish(ctx, req_hash, None, self.settings.max_attempts, 502, reservation=token)
                raise
            self.counters["live_calls"] += 1
            resp = result.response
            headers = {HASH_HEADER: req_hash, "x-sgw-attempts": str(result.attempts)}
            if ctx.stream and resp.status_code == 200:
                handed_off = True
                return StreamingResponse(
                    self._proxy_stream(ctx, req_hash, resp, result.attempts, worst_case, token),
                    media_type="text/event-stream",
                    headers=headers,
                )
            try:
                content = await resp.aread()
                message = json.loads(content) if resp.status_code == 200 else None
                if message is not None and not (isinstance(message, dict) and message.get("usage")):
                    raise ValueError("200 response without a usage block")
            except Exception as exc:  # noqa: BLE001
                self._finish(
                    ctx,
                    req_hash,
                    None,
                    result.attempts,
                    502,
                    reservation=token,
                    estimate_usd=worst_case,
                    estimate_reason="unreadable_response_worst_case",
                )
                return error_response(
                    "sgw_upstream_unreadable", f"{type(exc).__name__} reading upstream", 502
                )
            finally:
                await resp.aclose()
            if code := self._output_violation(message):
                self._finish(
                    ctx,
                    req_hash,
                    message,
                    result.attempts,
                    resp.status_code,
                    reservation=token,
                    deny_code=code,
                )
                return self._output_blocked(ctx, code)
            row = self._finish(ctx, req_hash, message, result.attempts, resp.status_code, reservation=token)
            headers["x-sgw-cost-usd"] = str(row.cost_usd)
            return Response(
                content, status_code=resp.status_code, media_type="application/json", headers=headers
            )
        finally:
            if not handed_off:
                self.budget.release(token)

    async def _proxy_stream(
        self,
        ctx: CallContext,
        req_hash: str,
        resp: httpx.Response,
        attempts: int,
        worst_case: float,
        token: int,
    ) -> AsyncIterator[bytes]:
        acc = SSEAccumulator()
        guard = SSEOutputGuard(self.detectors)
        finished = False
        try:
            async for chunk in resp.aiter_bytes():
                acc.feed(chunk)
                out = guard.feed(chunk)
                if guard.blocked_code is not None:
                    finished = True
                    complete = acc.stopped and acc.message is not None
                    self._finish(
                        ctx,
                        req_hash,
                        acc.message if complete else None,
                        attempts,
                        200 if complete else 499,
                        reservation=token,
                        estimate_usd=None if complete else worst_case,
                        estimate_reason="output_blocked_worst_case",
                        deny_code=guard.blocked_code,
                    )
                    self.counters["output_blocked"] += 1
                    self._log("output_blocked", node=ctx.node, code=guard.blocked_code)
                    if out:
                        yield out
                    yield encode_event(
                        "error",
                        {
                            "type": "error",
                            "error": {
                                "type": guard.blocked_code,
                                "message": "model output withheld by the gateway (SEC-33)",
                            },
                        },
                    )
                    return
                if acc.stopped and not finished:
                    finished = True
                    self._finish(ctx, req_hash, acc.message, attempts, 200, reservation=token)
                if out:
                    yield out
            if tail := guard.flush():
                yield tail
        finally:
            if not finished:
                finished = True
                complete = acc.message is not None and acc.message.get("stop_reason") is not None
                self._finish(
                    ctx,
                    req_hash,
                    acc.message,
                    attempts,
                    200 if complete else 499,
                    reservation=token,
                    estimate_usd=None if complete else worst_case,
                )
            with contextlib.suppress(Exception):
                await asyncio.shield(resp.aclose())


async def _iter(events: Any) -> AsyncIterator[bytes]:
    for event in events:
        yield event


def _safe_request_hash(body: dict[str, Any], headers: dict[str, str]) -> str:
    try:
        return request_hash(body, headers)
    except Exception:  # noqa: BLE001
        return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    sink: CallSink | None = None,
    opa_transport: httpx.AsyncBaseTransport | None = None,
    control: ControlGate | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    kwargs: dict[str, Any] = {"transport": transport}
    if sleep is not None:
        kwargs["sleep"] = sleep
    upstream = Upstream(settings, **kwargs)
    gateway = Gateway(settings, upstream, sink=sink, opa_transport=opa_transport, control=control)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await upstream.aclose()
        if isinstance(gateway.egress, OpaEgress):
            await gateway.egress.aclose()
        gateway.sink.close()

    app = FastAPI(title="sgw llm_gateway", version="0.1.0", lifespan=lifespan)
    app.state.gateway = gateway

    @app.post("/v1/messages")
    async def messages(request: Request) -> Response:
        return await gateway.handle(request)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        breaker = gateway.upstream.breaker.snapshot()
        budget = gateway.budget.state()
        egress_ok = await gateway.egress.healthy()
        sink = gateway.sink.snapshot()
        degraded = [
            reason
            for reason, bad in (
                ("breaker_open", breaker["state"] != "closed"),
                (f"budget_{budget['level']}", budget["level"] not in {"ok", "soft_stop_acknowledged"}),
                ("egress_pdp_unreachable", not egress_ok),
                ("llm_call_sink_failing", bool(sink.get("last_error"))),
            )
            if bad
        ]
        return {
            "status": "degraded" if degraded else "ok",
            "degraded": degraded,
            "mode": settings.mode.value,
            "key_present": settings.api_key is not None,
            "breaker": breaker,
            "budget": {
                k: budget[k]
                for k in (
                    "level",
                    "spent_usd",
                    "inflight_reserved_usd",
                    "soft_stop_usd",
                    "hard_stop_usd",
                    "ack_usd",
                    "estimated_balance_usd",
                    "balance_floor_usd",
                    "daily_cap_usd",
                    "today_spent_usd",
                )
            },
            "egress": {
                "pdp": gateway.egress.name,
                "reachable": egress_ok,
                "route": settings.egress_route,
                "policy": "sgw.egress",
            },
            "llm_call_sink": sink,
            "callers": {"services": gateway.callers.services, "test_tokens": gateway.callers.test_tokens},
            "counters": gateway.counters,
        }

    @app.get("/budget")
    async def budget(wave: str | None = None) -> dict[str, Any]:
        return gateway.budget.state(wave)

    @app.post("/budget/ack")
    async def budget_ack(request: Request) -> Response:
        token = request.headers.get("x-sgw-admin-token", "")
        if not settings.admin_token or not hmac.compare_digest(token, settings.admin_token):
            return error_response("sgw_forbidden", "budget ack needs the maintainer admin token", 403)
        data = await request.json()
        gateway.budget.acknowledge(float(data["ack_usd"]), data.get("console_balance_usd"))
        return JSONResponse(gateway.budget.state())

    return app
