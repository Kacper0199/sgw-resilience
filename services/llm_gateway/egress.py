"""Egress gate (SEC-R2): one decision per model call from the `sgw.egress` policy in `policy/egress.rego`.

`OpaEgress` asks the OPA server that loads `policy/` (compose mounts it read-only). `ReferenceEgress` is the
same deny-list in Python for runs without OPA (unit tests, CI, a replay gateway on a laptop); a parity test
runs both over one case table against the pinned OPA image. Live and record runs against the real API
require OPA (`Settings`). Both fail closed: an unreachable OPA or a malformed decision denies.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TypeGuard

import httpx

from .policy import CUSTOM_TOOL_TYPES, INLINE_SOURCES, NodeRule, PolicyViolation, content_sources
from .redact import CANARY_PATTERN, KEY_PATTERN

POLICY_VERSION = "egress-v1"
REGO_PATH = Path(__file__).resolve().parents[2] / "policy" / "egress.rego"
DECISION_PATH = "/v1/data/sgw/egress/decision"
HEALTH_PROBE: dict[str, dict[str, list[str]]] = {"input": {"classes": []}}
ROUTES: dict[str, dict[str, frozenset[str]]] = {
    "R1": {"allowed": frozenset({"C0", "C1"}), "pseudonymized_only": frozenset()},
    "R2": {"allowed": frozenset({"C0", "C1", "C2"}), "pseudonymized_only": frozenset({"C2"})},
}
CLASS_RANK = {"C0": 0, "C1": 1, "C2": 2, "C3": 3, "C3-N": 4, "C4": 5, "CX": 6}

CANARY_PREFIX_TAIL = re.compile(r"C(?:A(?:N(?:A(?:R(?:Y(?:-[0-9A-F]{0,3})?)?)?)?)?)?$", re.IGNORECASE)
SECRET_PATTERNS = (KEY_PATTERN, re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"))

# Deny reason -> (error type, HTTP status), most specific first; the first reason present names the error.
DENY_CODES: tuple[tuple[str, str, int], ...] = (
    ("unclassified_payload", "sgw_classes_missing", 400),
    ("unknown_class_label", "sgw_class_denied", 403),
    ("class_not_allowed_on_route", "sgw_class_denied", 403),
    ("class_requires_pseudonymization", "sgw_class_denied", 403),
    ("route_unknown", "sgw_route_unknown", 403),
    ("secret_detected", "sgw_secret_blocked", 403),
    ("canary_detected", "sgw_canary_blocked", 403),
    ("detectors_missing", "sgw_egress_input_invalid", 403),
    ("node_not_configured", "sgw_node_not_allowed", 403),
    ("node_ceiling_invalid", "sgw_node_not_allowed", 403),
    ("model_not_allowed", "sgw_model_not_allowed", 403),
    ("class_above_node_ceiling", "sgw_class_above_ceiling", 403),
    ("beta_not_allowed", "sgw_beta_not_allowed", 403),
    ("tool_type_not_allowed", "sgw_tool_not_allowed", 403),
    ("source_type_not_allowed", "sgw_source_not_allowed", 403),
)


class EgressUnavailableError(PolicyViolation):
    def __init__(self, message: str) -> None:
        super().__init__("sgw_egress_policy_unavailable", message, 503)


@dataclass(frozen=True)
class DetectorHits:
    canary_hits: int = 0
    secret_hits: int = 0


@dataclass(frozen=True)
class Detectors:
    """Counts canary tokens and secrets in text; never returns the matched values."""

    extra_canaries: tuple[str, ...] = ()

    def scan(self, text: str) -> DetectorHits:
        canaries = len(CANARY_PATTERN.findall(text)) + sum(text.count(t) for t in self.extra_canaries if t)
        secrets = sum(len(p.findall(text)) for p in SECRET_PATTERNS)
        return DetectorHits(canaries, secrets)

    def scan_json(self, value: Any) -> DetectorHits:
        return self.scan(json.dumps(value, ensure_ascii=False))

    def scrub(self, text: str) -> str:
        text = CANARY_PATTERN.sub("<redacted-canary>", text)
        for token in self.extra_canaries:
            if token:
                text = text.replace(token, "<redacted-canary>")
        return text

    def may_end_in_canary_prefix(self, text: str) -> bool:
        """True when the tail of `text` could be the start of a canary still being streamed."""
        if CANARY_PREFIX_TAIL.search(text[-12:]):
            return True
        return any(text.endswith(t[:i]) for t in self.extra_canaries if t for i in range(1, len(t)))


@dataclass(frozen=True)
class EgressDecision:
    allow: bool
    deny: tuple[str, ...]
    policy_version: str
    pdp: str

    def raise_if_denied(self) -> None:
        if self.allow:
            return
        for reason, code, status in DENY_CODES:
            if reason in self.deny:
                raise PolicyViolation(code, f"egress denied ({', '.join(self.deny)})", status)
        raise PolicyViolation("sgw_egress_denied", f"egress denied ({', '.join(self.deny)})", 403)


def rule_json(rule: NodeRule | None) -> dict[str, Any] | None:
    if rule is None:
        return None
    return {
        "models": sorted(rule.models),
        "class_ceiling": rule.class_ceiling,
        "betas": sorted(rule.betas),
        "tool_types": sorted(rule.tool_types),
        "source_types": sorted(rule.source_types),
    }


@dataclass(frozen=True)
class EgressInput:
    route: str
    node: str
    model: str
    classes: tuple[str, ...]
    node_rule: NodeRule | None
    betas: tuple[str, ...] = ()
    tool_types: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    pseudonymized: bool = False
    detectors: DetectorHits = field(default_factory=DetectorHits)

    def to_json(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "node": self.node,
            "model": self.model,
            "classes": list(self.classes),
            "pseudonymized": self.pseudonymized,
            "betas": list(self.betas),
            "tool_types": list(self.tool_types),
            "source_types": list(self.source_types),
            "detectors": {
                "canary_hits": self.detectors.canary_hits,
                "secret_hits": self.detectors.secret_hits,
            },
            "node_rule": rule_json(self.node_rule),
        }


def request_betas(headers: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(sorted({b.strip() for b in headers.get("anthropic-beta", "").split(",") if b.strip()}))


def request_tool_types(body: Mapping[str, Any]) -> tuple[str, ...]:
    types: set[str] = set()
    for tool in body.get("tools") or []:
        ttype = tool.get("type") if isinstance(tool, Mapping) else "invalid"
        if ttype not in CUSTOM_TOOL_TYPES:
            types.add(str(ttype))
    return tuple(sorted(types))


def request_source_types(body: Mapping[str, Any]) -> tuple[str, ...]:
    """Document and image sources the detectors cannot read as plain text (base64, url, file)."""
    kinds = {kind for kind, src in content_sources(body) if src.get("type") not in INLINE_SOURCES}
    return tuple(sorted(kinds))


def outbound_text(body: Mapping[str, Any]) -> str:
    """The body as the detectors see it: its JSON plus the decoded bytes of every base64 source."""
    parts = [json.dumps(body, ensure_ascii=False, sort_keys=True)]
    for _, source in content_sources(body):
        data = source.get("data")
        if source.get("type") == "base64" and isinstance(data, str):
            try:
                parts.append(base64.b64decode(data, validate=False).decode("utf-8", errors="replace"))
            except (binascii.Error, ValueError):
                parts.append("<undecodable base64>")
    return "\n".join(parts)


class EgressPDP(Protocol):
    name: str

    async def decide(self, inp: EgressInput) -> EgressDecision: ...

    async def healthy(self) -> bool: ...


def _in(values: Iterable[str], allowed: Iterable[str]) -> bool:
    allowed_set = set(allowed)
    return all(v in allowed_set for v in values)


class ReferenceEgress:
    """Python twin of `policy/egress.rego`; kept equal by `test_egress_parity.py`."""

    name = "reference"

    def evaluate(self, raw: Mapping[str, Any]) -> EgressDecision:
        deny: set[str] = set()
        classes_raw = raw.get("classes")
        classes = set(classes_raw) if isinstance(classes_raw, list) else set()
        if not isinstance(classes_raw, list) or not classes:
            deny.add("unclassified_payload")
        if any(c not in CLASS_RANK for c in classes):
            deny.add("unknown_class_label")
        route = ROUTES.get(str(raw.get("route", "")))
        if route is None:
            deny.add("route_unknown")
        else:
            if any(c in CLASS_RANK and c not in route["allowed"] for c in classes):
                deny.add("class_not_allowed_on_route")
            if (
                any(c in route["pseudonymized_only"] for c in classes)
                and raw.get("pseudonymized") is not True
            ):
                deny.add("class_requires_pseudonymization")
        raw_detectors = raw.get("detectors")
        detectors: Mapping[str, Any] = raw_detectors if isinstance(raw_detectors, Mapping) else {}
        for key, reason in (("canary_hits", "canary_detected"), ("secret_hits", "secret_detected")):
            value = detectors.get(key)
            if not _is_number(value):
                deny.add("detectors_missing")
            elif float(value) > 0:
                deny.add(reason)
        rule = raw.get("node_rule")
        if not isinstance(rule, Mapping) or not rule.get("models"):
            deny.add("node_not_configured")
        if isinstance(rule, Mapping):
            if rule.get("models") and raw.get("model") not in rule["models"]:
                deny.add("model_not_allowed")
            ceiling = rule.get("class_ceiling")
            if ceiling not in CLASS_RANK:
                deny.add("node_ceiling_invalid")
            elif any(CLASS_RANK.get(c, -1) > CLASS_RANK[ceiling] for c in classes):
                deny.add("class_above_node_ceiling")
            if not _in(raw.get("betas") or [], rule.get("betas") or []):
                deny.add("beta_not_allowed")
            if not _in(raw.get("tool_types") or [], rule.get("tool_types") or []):
                deny.add("tool_type_not_allowed")
            if not _in(raw.get("source_types") or [], rule.get("source_types") or []):
                deny.add("source_type_not_allowed")
        return EgressDecision(not deny, tuple(sorted(deny)), POLICY_VERSION, self.name)

    async def decide(self, inp: EgressInput) -> EgressDecision:
        return self.evaluate(inp.to_json())

    async def healthy(self) -> bool:
        return True


def _is_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def parse_decision(raw: Any, pdp: str) -> EgressDecision:
    try:
        result = raw["result"]
        allow = result["allow"] is True
        deny = tuple(str(r) for r in result["deny"])
        version = str(result["policy_version"])
    except (KeyError, TypeError) as exc:
        raise EgressUnavailableError(
            f"malformed or undefined egress decision ({type(exc).__name__})"
        ) from exc
    if version != POLICY_VERSION:
        raise EgressUnavailableError(f"egress policy version {version!r} is not {POLICY_VERSION!r}")
    if allow and deny:
        raise EgressUnavailableError("egress decision allows with deny reasons")
    return EgressDecision(allow, deny, version, pdp)


class OpaEgress:
    name = "opa"

    def __init__(
        self, base_url: str, *, timeout_s: float = 2.0, transport: httpx.AsyncBaseTransport | None = None
    ):
        self.base_url = base_url.rstrip("/")
        token = os.environ.get("SGW_OPA_TOKEN")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout_s,
            transport=transport,
            trust_env=False,
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )
        self.last_error: str | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def decide(self, inp: EgressInput) -> EgressDecision:
        try:
            response = await self._client.post(DECISION_PATH, json={"input": inp.to_json()})
            response.raise_for_status()
            decision = parse_decision(response.json(), self.name)
        except (httpx.HTTPError, ValueError) as exc:
            self.last_error = type(exc).__name__
            raise EgressUnavailableError(f"OPA egress query failed: {type(exc).__name__}") from exc
        except EgressUnavailableError as exc:
            self.last_error = exc.message
            raise
        self.last_error = None
        return decision

    async def healthy(self) -> bool:
        """True only when the egress decision itself is defined and current, not merely when OPA is up."""
        try:
            response = await self._client.post(DECISION_PATH, json=HEALTH_PROBE)
            parse_decision(response.json(), self.name)
        except (httpx.HTTPError, ValueError, EgressUnavailableError):
            return False
        return response.status_code == 200
