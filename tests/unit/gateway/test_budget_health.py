"""Money rules (working-rules 3) and the breaker as the platform sees them: typed 402/503 refusals before any
egress, the level in every response's `x-sgw-budget` header, and the same facts on `/healthz` for Health."""

from __future__ import annotations

from pathlib import Path

import httpx
from services.llm_gateway.calls import MemorySink
from services.llm_gateway.config import Mode
from services.llm_gateway.spend import CallRow, SpendLedger

from .gateway_testkit import BASE_HEADERS, FakeUpstream, base_body

DEV = {**BASE_HEADERS, "x-sgw-purpose": "dev"}
ADMIN = "maintainer-admin-token-for-tests"


def _spent(csv: Path, usd: float) -> None:
    SpendLedger(csv).append(
        CallRow(
            ts="2026-11-19T22:00:00Z",
            mode="live",
            purpose="eval",
            wave="W1",
            run_id="",
            node="test.narrate",
            prompt_version="",
            model="claude-sonnet-5-5",
            effort="medium",
            batch=False,
            input_tokens=0,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            output_tokens=0,
            stop_reason="end_turn",
            latency_ms=1,
            cost_usd=usd,
            request_hash="c" * 64,
            billed=True,
            attempts=1,
            status=200,
        )
    )


async def test_soft_stop_refuses_before_egress_until_acknowledged(client_factory, tmp_path):
    csv = tmp_path / "var" / "llm_spend.csv"
    _spent(csv, 40.2)
    upstream, sink = FakeUpstream(), MemorySink()
    client, _ = client_factory(upstream=upstream, sink=sink, mode=Mode.LIVE, admin_token=ADMIN)
    r = await client.post("/v1/messages", json=base_body(), headers=DEV)
    assert r.status_code == 402 and r.json()["error"]["type"] == "sgw_budget_soft_stop"
    assert r.headers["x-sgw-budget"] == "soft_stop" and upstream.requests == []
    assert (sink.records[0].decision, sink.records[0].stop_reason) == ("deny", "sgw_budget_soft_stop")
    health = (await client.get("/healthz")).json()
    assert health["budget"]["level"] == "soft_stop" and "budget_soft_stop" in health["degraded"]
    assert health["status"] == "degraded"
    ack = await client.post("/budget/ack", json={"ack_usd": 45}, headers={"x-sgw-admin-token": ADMIN})
    assert ack.status_code == 200 and ack.json()["level"] == "soft_stop_acknowledged"
    r = await client.post("/v1/messages", json=base_body(), headers=DEV)
    assert r.status_code == 200 and r.headers["x-sgw-budget"] == "soft_stop_acknowledged"
    assert (await client.get("/healthz")).json()["status"] == "ok"


async def test_soft_stop_counts_the_worst_case_of_the_call(client_factory, tmp_path):
    _spent(tmp_path / "var" / "llm_spend.csv", 39.999)
    upstream = FakeUpstream()
    client, _ = client_factory(upstream=upstream, mode=Mode.LIVE)
    r = await client.post("/v1/messages", json=base_body(max_tokens=4000), headers=DEV)
    assert r.status_code == 402 and r.json()["error"]["type"] == "sgw_budget_soft_stop"
    assert r.headers["x-sgw-budget"] == "ok" and upstream.requests == []


async def test_hard_stop_holds_even_after_a_soft_stop_ack(client_factory, tmp_path):
    _spent(tmp_path / "var" / "llm_spend.csv", 90.0)
    upstream, sink = FakeUpstream(), MemorySink()
    client, _ = client_factory(upstream=upstream, sink=sink, mode=Mode.LIVE, budget_ack_usd=60.0)
    r = await client.post("/v1/messages", json=base_body(), headers=DEV)
    assert r.status_code == 402 and r.json()["error"]["type"] == "sgw_budget_hard_stop"
    assert r.headers["x-sgw-budget"] == "hard_stop" and upstream.requests == []
    assert sink.records[0].stop_reason == "sgw_budget_hard_stop"
    health = (await client.get("/healthz")).json()
    assert health["budget"]["level"] == "hard_stop" and health["budget"]["hard_stop_usd"] == 90.0


async def test_balance_floor_surfaces(client_factory, tmp_path):
    _spent(tmp_path / "var" / "llm_spend.csv", 1.0)
    client, _ = client_factory(mode=Mode.LIVE, console_balance_usd=100.0)
    r = await client.post("/v1/messages", json=base_body(), headers=DEV)
    assert r.status_code == 402 and r.json()["error"]["type"] == "sgw_balance_floor"
    assert (await client.get("/healthz")).json()["budget"]["level"] == "balance_floor"


async def test_replay_is_never_stopped_by_the_budget(client_factory, tmp_path):
    client, _ = client_factory()
    assert (await client.post("/v1/messages", json=base_body(), headers=DEV)).status_code == 200
    _spent(tmp_path / "var" / "llm_spend.csv", 95.0)
    replay, _ = client_factory(mode=Mode.REPLAY, api_key=None)
    r = await replay.post("/v1/messages", json=base_body(), headers=DEV)
    assert r.status_code == 200 and r.headers["x-sgw-budget"] == "hard_stop"


async def test_breaker_opens_and_shows_on_health(client_factory):
    upstream = FakeUpstream([httpx.Response(529, json={"type": "error"}) for _ in range(5)])
    sink = MemorySink()
    client, _ = client_factory(upstream=upstream, sink=sink, mode=Mode.LIVE, max_attempts=5)
    r = await client.post("/v1/messages", json=base_body(), headers=DEV)
    assert r.status_code == 529 and len(upstream.requests) == 5
    health = (await client.get("/healthz")).json()
    assert health["breaker"]["state"] == "open" and health["breaker"]["retry_in_s"] > 0
    assert health["breaker"]["consecutive_failures"] == 5 and "breaker_open" in health["degraded"]
    r = await client.post("/v1/messages", json=base_body(), headers=DEV)
    assert r.status_code == 503 and r.json()["error"]["type"] == "sgw_breaker_open"
    assert len(upstream.requests) == 5
    assert sink.records[-1].stop_reason == "sgw_breaker_open" and sink.records[-1].decision == "deny"


async def test_health_reports_egress_and_sink(client_factory):
    client, _ = client_factory(sink=MemorySink())
    health = (await client.get("/healthz")).json()
    assert health["egress"] == {"pdp": "reference", "reachable": True, "route": "R1", "policy": "sgw.egress"}
    assert health["llm_call_sink"]["kind"] == "memory"
    assert set(health["counters"]) >= {"egress_denied", "output_blocked", "replay_hits", "live_calls"}
