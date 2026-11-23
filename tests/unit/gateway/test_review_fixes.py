from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from services.llm_gateway.callers import TEST_TOKENS, token_sha256
from services.llm_gateway.config import Settings
from services.llm_gateway.egress import EgressInput, ReferenceEgress, request_betas, request_tool_types
from services.llm_gateway.policy import NodeAllowlist, NodeRule
from services.llm_gateway.sse import synthesize_events
from services.llm_gateway.upstream import CircuitBreaker

from .gateway_testkit import BASE_HEADERS, KEY_PREFIX, ChunkStream, FakeUpstream, base_body, message_json


async def test_concurrent_calls_cannot_overrun_hard_stop(client_factory):
    release = asyncio.Event()
    seen: list[httpx.Request] = []

    async def slow(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        await release.wait()
        return httpx.Response(200, json=message_json(output_tokens=1))

    client, app = client_factory(upstream=slow, hard_stop_usd=0.02)

    async def call():
        return await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)

    tasks = [asyncio.create_task(call()) for _ in range(10)]
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5.0
    while len(seen) + sum(t.done() for t in tasks) < len(tasks) and loop.time() < deadline:
        await asyncio.sleep(0.01)
    in_flight = len(seen)
    release.set()
    results = await asyncio.gather(*tasks)
    ok = [r for r in results if r.status_code == 200]
    stopped = [r for r in results if r.status_code == 402]
    assert in_flight == len(ok) == 3
    assert len(stopped) == 7
    assert all(r.json()["error"]["type"] == "sgw_budget_hard_stop" for r in stopped)
    assert app.state.gateway.budget.state()["inflight_calls"] == 0


async def test_read_timeout_is_not_retried_and_booked_at_worst_case(client_factory):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    upstream = FakeUpstream([boom, boom])
    client, app = client_factory(upstream=upstream)
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 504 and r.json()["error"]["type"] == "sgw_upstream_post_send_failure"
    assert len(upstream.requests) == 1
    row = app.state.gateway.ledger.rows()[-1]
    assert row["billed"] == "True" and float(row["cost_usd"]) > 0
    assert row["stop_reason"] == "post_send_failure_worst_case"
    assert app.state.gateway.budget.state()["inflight_calls"] == 0


async def test_connect_error_is_retried_and_logged_when_exhausted(client_factory):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    upstream = FakeUpstream([refuse] * 5)
    client, app = client_factory(upstream=upstream, max_attempts=3)
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 502 and r.json()["error"]["type"] == "sgw_upstream_unreachable"
    assert len(upstream.requests) == 3
    row = app.state.gateway.ledger.rows()[-1]
    assert row["billed"] == "False" and row["status"] == "502"


async def test_unreadable_200_is_booked_not_400(client_factory):
    upstream = FakeUpstream(
        [httpx.Response(200, content=b"{not json", headers={"content-type": "application/json"})]
    )
    client, app = client_factory(upstream=upstream)
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 502 and r.json()["error"]["type"] == "sgw_upstream_unreadable"
    row = app.state.gateway.ledger.rows()[-1]
    assert row["billed"] == "True" and row["stop_reason"] == "unreadable_response_worst_case"


@pytest.mark.parametrize(
    ("header", "value"),
    [
        ("x-sgw-run", "run,1\nx"),
        ("x-sgw-run", KEY_PREFIX + "api03-abc"),
        ("x-sgw-wave", "W0-this-is-far-too-long"),
        ("x-sgw-wave", ""),
        ("x-sgw-prompt-version", "narrate v2"),
        ("x-sgw-deadline-s", "soon"),
    ],
)
async def test_bad_tags_rejected_before_egress(client_factory, header, value):
    upstream = FakeUpstream()
    client, _ = client_factory(upstream=upstream)
    r = await client.post("/v1/messages", json=base_body(), headers={**BASE_HEADERS, header: value})
    assert r.status_code == 400
    assert upstream.requests == []


async def test_missing_classes_refused(client_factory):
    upstream = FakeUpstream()
    client, _ = client_factory(upstream=upstream)
    headers = {k: v for k, v in BASE_HEADERS.items() if k != "x-sgw-classes"}
    r = await client.post("/v1/messages", json=base_body(), headers=headers)
    assert r.status_code == 400 and r.json()["error"]["type"] == "sgw_classes_missing"
    assert upstream.requests == []


@pytest.mark.parametrize(
    ("body", "headers", "code"),
    [
        (base_body(mcp_servers=[{"type": "url", "url": "https://x.example"}]), {}, "sgw_param_not_allowed"),
        (base_body(container="c1"), {}, "sgw_param_not_allowed"),
        (base_body(tools=[{"type": "web_fetch_20260209", "name": "web_fetch"}]), {}, "sgw_tool_not_allowed"),
        (base_body(), {"anthropic-beta": "mcp-client-2025-11-20"}, "sgw_beta_not_allowed"),
    ],
)
async def test_egress_widening_features_refused(client_factory, body, headers, code):
    upstream = FakeUpstream()
    client, _ = client_factory(upstream=upstream)
    r = await client.post("/v1/messages", json=body, headers={**BASE_HEADERS, **headers})
    assert r.json()["error"]["type"] == code
    assert upstream.requests == []


def test_node_rule_from_yaml_allows_named_betas_tools_and_ceiling(tmp_path):
    path = tmp_path / "llm_nodes.yaml"
    path.write_text(
        "nodes:\n  answer_sop:\n    model: claude-sonnet-5-5\n    class_ceiling: C0\n"
        "    betas: [x-2026]\n    tool_types: [web_search_20260209]\n"
    )
    rule = NodeAllowlist.load(path).rule_for("answer_sop")
    body = base_body(tools=[{"type": "web_search_20260209", "name": "web_search"}])

    def decide(betas: str, classes: tuple[str, ...]) -> tuple[str, ...]:
        inp = EgressInput(
            route="R1",
            node="answer_sop",
            model=body["model"],
            classes=classes,
            node_rule=rule,
            betas=request_betas({"anthropic-beta": betas}),
            tool_types=request_tool_types(body),
        )
        return ReferenceEgress().evaluate(inp.to_json()).deny

    assert decide("x-2026", ("C0",)) == ()
    assert decide("", ("C1",)) == ("class_above_node_ceiling",)
    assert decide("other-beta", ("C0",)) == ("beta_not_allowed",)


def test_default_rules_have_c2_ceiling_for_test_nodes():
    assert NodeAllowlist.load(None).rule_for("test.narrate") == NodeRule(
        ("claude-sonnet-5-5", "claude-haiku-5-5"), class_ceiling="C2"
    )


def test_upstream_url_locked_to_anthropic(monkeypatch):
    with pytest.raises(ValueError):
        Settings(upstream_base_url="https://evil.example")
    Settings(upstream_base_url="https://upstream.invalid", allow_test_upstream=True)
    monkeypatch.setenv("LLM_UPSTREAM_BASE_URL", "http://127.0.0.1:9")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_zero_values_are_honoured(monkeypatch):
    monkeypatch.setenv("LLM_HARD_STOP_USD", "0")
    monkeypatch.setenv("LLM_SOFT_STOP_USD", "0")
    s = Settings.from_env()
    assert s.hard_stop_usd == 0.0 and s.soft_stop_usd == 0.0
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "0")
    with pytest.raises(ValueError):
        Settings.from_env()


async def test_hard_stop_zero_blocks_live(client_factory):
    upstream = FakeUpstream()
    client, _ = client_factory(upstream=upstream, hard_stop_usd=0.0)
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 402 and upstream.requests == []


def test_upstream_client_ignores_proxy_env(client_factory):
    _, app = client_factory()
    assert app.state.gateway.upstream.client._trust_env is False


def test_half_open_probe_released_after_unclassified_outcome():
    now = [0.0]
    b = CircuitBreaker(threshold=1, cooldown_s=1.0, clock=lambda: now[0])
    b.failure(b.acquire())
    now[0] = 2.0
    gen = b.acquire()
    assert b.state == "half_open" and b.probe_in_flight
    b.end_attempt(gen)
    assert not b.probe_in_flight
    b.acquire()


async def test_wave_cap_counts_unbilled_live_calls(client_factory):
    err = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}
    upstream = FakeUpstream([httpx.Response(400, json=err)] * 3)
    client, _ = client_factory(upstream=upstream, wave_cap_calls=2)
    codes = [
        (await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)).status_code
        for _ in range(3)
    ]
    assert codes == [400, 400, 402]
    assert len(upstream.requests) == 2


async def test_ledger_never_raises_on_key_shaped_values(client_factory, tmp_path):
    from services.llm_gateway.spend import CallRow, SpendLedger

    ledger = SpendLedger(tmp_path / "l.csv")
    row = CallRow(
        "t",
        "record",
        "spike",
        "W0",
        KEY_PREFIX + "api03-x",
        "n",
        "",
        "m",
        "low",
        False,
        0,
        0,
        0,
        0,
        "",
        0,
        0.1,
        "h",
        True,
        1,
        200,
    )
    ledger.append(row)
    assert KEY_PREFIX not in (tmp_path / "l.csv").read_text()
    assert ledger.total_usd() == 0.1


def test_stream_recording_saved_before_message_stop_reaches_client(tmp_path):
    import threading
    import time

    import uvicorn
    from services.llm_gateway.api import create_app
    from services.llm_gateway.config import Mode

    payload = b"".join(synthesize_events(message_json("early", output_tokens=4)))

    def up(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, stream=ChunkStream(payload, size=23), headers={"content-type": "text/event-stream"}
        )

    settings = Settings(
        caller_token_digests=(("cli", token_sha256(TEST_TOKENS["cli"])),),
        mode=Mode.RECORD,
        fixture_dir=tmp_path / "fx",
        spend_csv=tmp_path / "s.csv",
        api_key="placeholder",
        record_overwrite=True,
        egress_pdp="reference",
    )
    app = create_app(settings, transport=httpx.MockTransport(up))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        seen_at_stop = None
        buf = b""
        with httpx.stream(
            "POST",
            f"http://127.0.0.1:{port}/v1/messages",
            json={**base_body(), "stream": True},
            headers=BASE_HEADERS,
            timeout=10,
        ) as r:
            for chunk in r.iter_raw():
                buf += chunk
                if seen_at_stop is None and b'"message_stop"}\n\n' in buf:
                    seen_at_stop = list((tmp_path / "fx").rglob("*.json"))
        assert seen_at_stop, "recording must exist before the client sees message_stop"
        assert json.loads((tmp_path / "s.csv").read_text().splitlines()[1].split(",")[13]) == 4
    finally:
        server.should_exit = True
        thread.join(timeout=5)
