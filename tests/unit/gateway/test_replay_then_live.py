"""P3: `LLM_MODE=replay_then_live` and the daily cap, against a mock upstream only.

A recorded request is served from `data/fixtures/llm` and spends nothing; a miss goes live once, is stored in
the live cache (never the fixtures) and is then served from there. Every live call is refused with 402
`sgw_daily_cap` when today's UTC spend plus the in-flight reservations plus its own worst case would exceed
`LLM_DAILY_CAP_USD` (default 30); the day resets at UTC midnight. Cumulative stops: hard stop 90 USD and a
balance floor of 100 USD on the console reading, whichever comes first."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from services.llm_gateway.budget import BudgetGuard
from services.llm_gateway.calls import MemorySink
from services.llm_gateway.config import REPO_ROOT, Mode, Settings
from services.llm_gateway.policy import PolicyViolation
from services.llm_gateway.prices import worst_case_cost_usd
from services.llm_gateway.spend import CallRow, SpendLedger

from .gateway_testkit import BASE_HEADERS, FakeUpstream, base_body

DEMO = {**BASE_HEADERS, "x-sgw-purpose": "demo"}


def _row(ts: str, usd: float) -> CallRow:
    return CallRow(
        ts=ts,
        mode="live",
        purpose="demo",
        wave="R27",
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


def _today(hms: str = "00:00:01") -> str:
    return datetime.now(UTC).strftime(f"%Y-%m-%dT{hms}Z")


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.json")) if root.exists() else []


@pytest.fixture
def rtl(client_factory, tmp_path):
    def make(upstream: FakeUpstream | None = None, **kw):
        return client_factory(
            upstream=upstream,
            mode=Mode.REPLAY_THEN_LIVE,
            record_overwrite=False,
            live_cache_dir=tmp_path / "var" / "llm" / "live_cache",
            **kw,
        )

    return make


async def test_a_recorded_request_is_replayed_and_spends_nothing(client_factory, rtl, tmp_path):
    recorder, _ = client_factory()
    assert (await recorder.post("/v1/messages", json=base_body(), headers=DEMO)).status_code == 200
    fixtures = _files(tmp_path / "fixtures")
    spent = SpendLedger(tmp_path / "var" / "llm_spend.csv").total_usd()
    upstream, sink = FakeUpstream(), MemorySink()
    client, _ = rtl(upstream, sink=sink)
    r = await client.post("/v1/messages", json=base_body(), headers=DEMO)
    assert r.status_code == 200 and r.headers["x-sgw-replay"] == "hit"
    assert r.headers["x-sgw-replay-source"] == "fixtures"
    assert upstream.requests == []
    assert SpendLedger(tmp_path / "var" / "llm_spend.csv").total_usd() == spent
    assert _files(tmp_path / "var" / "llm" / "live_cache") == []
    assert _files(tmp_path / "fixtures") == fixtures
    assert (sink.records[0].mode, sink.records[0].billed, sink.records[0].cost_usd) == ("replay", False, 0.0)


async def test_a_miss_goes_live_once_then_is_served_from_the_live_cache(rtl, tmp_path):
    upstream, sink = FakeUpstream(), MemorySink()
    client, _ = rtl(upstream, sink=sink)
    first = await client.post("/v1/messages", json=base_body(), headers=DEMO)
    assert first.status_code == 200 and "x-sgw-replay" not in first.headers
    assert len(upstream.requests) == 1
    cached = _files(tmp_path / "var" / "llm" / "live_cache")
    assert len(cached) == 1 and cached[0].parent.name == "test.narrate"
    assert cached[0].stem == first.headers["x-sgw-request-hash"]
    assert json.loads(cached[0].read_text())["response"]["content"][0]["text"] == "PS-17 is de-energised."
    assert _files(tmp_path / "fixtures") == []
    second = await client.post("/v1/messages", json=base_body(), headers=DEMO)
    assert second.status_code == 200 and second.headers["x-sgw-replay-source"] == "live_cache"
    assert second.json()["content"] == first.json()["content"]
    assert len(upstream.requests) == 1
    ledger = SpendLedger(tmp_path / "var" / "llm_spend.csv")
    assert ledger.billed_calls() == 1 and ledger.total_usd() > 0
    assert [r.mode for r in sink.records] == ["live", "replay"]


async def test_a_streamed_miss_is_cached_too(rtl, tmp_path):
    from services.llm_gateway.sse import synthesize_events

    from .gateway_testkit import message_json

    body = b"".join(synthesize_events(message_json()))
    upstream = FakeUpstream(
        [httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})]
    )
    client, _ = rtl(upstream)
    async with client.stream("POST", "/v1/messages", json=base_body(stream=True), headers=DEMO) as r:
        assert r.status_code == 200
        _ = [c async for c in r.aiter_bytes()]
    assert len(_files(tmp_path / "var" / "llm" / "live_cache")) == 1
    again = await client.post("/v1/messages", json=base_body(stream=True), headers=DEMO)
    assert again.headers["x-sgw-replay-source"] == "live_cache" and len(upstream.requests) == 1


async def test_daily_cap_refuses_at_the_boundary_before_egress(rtl, tmp_path):
    worst = worst_case_cost_usd("claude-sonnet-5-5", len(json.dumps(base_body()).encode()) // 3, 512)
    csv = tmp_path / "var" / "llm_spend.csv"
    SpendLedger(csv).append(_row(_today(), round(30.0 - worst, 6)))
    upstream, sink = FakeUpstream(), MemorySink()
    client, _ = rtl(upstream, sink=sink, soft_stop_usd=1000.0, hard_stop_usd=2000.0)
    ok = await client.post("/v1/messages", json=base_body(), headers=DEMO)
    assert ok.status_code == 200 and len(upstream.requests) == 1
    r = await client.post("/v1/messages", json=base_body(max_tokens=513), headers=DEMO)
    assert r.status_code == 402 and r.json()["error"]["type"] == "sgw_daily_cap"
    assert len(upstream.requests) == 1
    assert sink.records[-1].stop_reason == "sgw_daily_cap" and sink.records[-1].decision == "deny"
    replayed = await client.post("/v1/messages", json=base_body(), headers=DEMO)
    assert replayed.status_code == 200 and replayed.headers["x-sgw-replay-source"] == "live_cache"
    budget = (await client.get("/budget")).json()
    assert budget["daily_cap_usd"] == 30.0
    assert budget["today_spent_usd"] >= 30.0 - worst


def _guard(tmp_path: Path, now: datetime, **kw) -> BudgetGuard:
    settings = Settings(
        fixture_dir=tmp_path / "fixtures",
        spend_csv=tmp_path / "spend.csv",
        live_cache_dir=tmp_path / "live_cache",
        soft_stop_usd=1000.0,
        hard_stop_usd=2000.0,
        **kw,
    )
    return BudgetGuard(settings, SpendLedger(settings.spend_csv), clock=lambda: now)


def test_the_day_resets_at_utc_midnight(tmp_path):
    ledger = SpendLedger(tmp_path / "spend.csv")
    ledger.append(_row("2026-11-21T23:59:59Z", 29.5))
    ledger.append(_row("2026-11-20T12:00:00Z", 25.0))
    late = _guard(tmp_path, datetime(2026, 11, 21, 23, 59, 59, tzinfo=UTC))
    with pytest.raises(PolicyViolation) as exc:
        late.check_live(wave="R27", worst_case_usd=0.6)
    assert exc.value.code == "sgw_daily_cap" and exc.value.status == 402
    late.check_live(wave="R27", worst_case_usd=0.5)
    midnight = _guard(tmp_path, datetime(2026, 11, 22, 0, 0, 0, tzinfo=UTC))
    midnight.check_live(wave="R27", worst_case_usd=29.9)
    assert midnight.state()["today_spent_usd"] == 0.0 and late.state()["today_spent_usd"] == 29.5
    ledger.append(_row("2026-11-21T23:59:59Z", 0.5))
    assert late.level() == "daily_cap" and midnight.level() == "ok"


def test_in_flight_reservations_count_against_the_day(tmp_path):
    SpendLedger(tmp_path / "spend.csv").append(_row("2026-11-21T08:00:00Z", 5.0))
    guard = _guard(tmp_path, datetime(2026, 11, 21, 9, 0, tzinfo=UTC))
    token = guard.reserve(wave="R27", worst_case_usd=20.0)
    with pytest.raises(PolicyViolation) as exc:
        guard.reserve(wave="R27", worst_case_usd=5.01)
    assert exc.value.code == "sgw_daily_cap"
    guard.release(token)
    guard.reserve(wave="R27", worst_case_usd=24.99)


def test_daily_cap_off_and_env_overrides(tmp_path, monkeypatch):
    SpendLedger(tmp_path / "spend.csv").append(_row("2026-11-21T08:00:00Z", 40.0))
    _guard(tmp_path, datetime(2026, 11, 21, 9, 0, tzinfo=UTC), daily_cap_usd=None).check_live(
        wave="R27", worst_case_usd=1.0
    )
    for name in ("LLM_DAILY_CAP_USD", "LLM_HARD_STOP_USD", "LLM_BALANCE_FLOOR_USD", "LLM_LIVE_CACHE_DIR"):
        monkeypatch.delenv(name, raising=False)
    s = Settings.from_env()
    assert (s.daily_cap_usd, s.hard_stop_usd, s.balance_floor_usd) == (30.0, 90.0, 100.0)
    assert s.live_cache_dir == REPO_ROOT / "var" / "llm" / "live_cache"
    monkeypatch.setenv("LLM_DAILY_CAP_USD", "12.5")
    monkeypatch.setenv("LLM_HARD_STOP_USD", "80")
    monkeypatch.setenv("LLM_BALANCE_FLOOR_USD", "110")
    monkeypatch.setenv("LLM_MODE", "replay_then_live")
    monkeypatch.setenv("LLM_EGRESS_PDP", "reference")
    s = Settings.from_env()
    assert (s.mode, s.daily_cap_usd, s.hard_stop_usd, s.balance_floor_usd) == (
        Mode.REPLAY_THEN_LIVE,
        12.5,
        80.0,
        110.0,
    )


@pytest.mark.parametrize("inside", ["fixtures", "fixtures/llm-live"])
def test_the_live_cache_never_lives_in_the_fixtures(tmp_path, inside):
    with pytest.raises(ValueError, match="live cache"):
        Settings(fixture_dir=tmp_path / "fixtures", live_cache_dir=tmp_path / inside)
    with pytest.raises(ValueError, match="live cache"):
        Settings(live_cache_dir=REPO_ROOT / "data" / "fixtures" / "llm_live")


def test_hard_stop_and_balance_floor_whichever_comes_first(tmp_path):
    ledger = SpendLedger(tmp_path / "spend.csv")
    ledger.append(_row("2026-11-01T08:00:00Z", 89.0))
    settings = Settings(
        fixture_dir=tmp_path / "fixtures", spend_csv=tmp_path / "spend.csv", live_cache_dir=tmp_path / "lc"
    )
    assert (settings.hard_stop_usd, settings.balance_floor_usd) == (90.0, 100.0)
    guard = BudgetGuard(settings, ledger, clock=lambda: datetime(2026, 11, 21, tzinfo=UTC))
    guard.acknowledge(ack_usd=100.0, console_balance_usd=None)
    guard.check_live(wave="R27", worst_case_usd=0.5)
    with pytest.raises(PolicyViolation) as exc:
        guard.check_live(wave="R27", worst_case_usd=1.0)
    assert exc.value.code == "sgw_budget_hard_stop"
    floor = BudgetGuard(
        Settings(
            fixture_dir=tmp_path / "fixtures",
            spend_csv=tmp_path / "other.csv",
            live_cache_dir=tmp_path / "lc",
            console_balance_usd=100.4,
        ),
        SpendLedger(tmp_path / "other.csv"),
        clock=lambda: datetime(2026, 11, 21, tzinfo=UTC),
    )
    floor.acknowledge(ack_usd=100.0, console_balance_usd=None)
    with pytest.raises(PolicyViolation) as exc:
        floor.check_live(wave="R27", worst_case_usd=0.5)
    assert exc.value.code == "sgw_balance_floor"
    assert floor.level() == "ok"
    floor.check_live(wave="R27", worst_case_usd=0.3)


@pytest.mark.parametrize("cap_s, floor_s", [(0.0, 0.0), (0.3, 0.28), (5.0, 0.38)])
async def test_a_replay_is_paced_at_the_recorded_latency_up_to_the_cap(
    client_factory, rtl, tmp_path, cap_s, floor_s
):
    import time

    recorder, _ = client_factory()
    assert (await recorder.post("/v1/messages", json=base_body(), headers=DEMO)).status_code == 200
    (fixture,) = _files(tmp_path / "fixtures")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    fixture.write_text(json.dumps({**data, "latency_ms": 400}), encoding="utf-8")
    client, _ = rtl(FakeUpstream(), replay_pace_max_s=cap_s)
    started = time.monotonic()
    r = await client.post("/v1/messages", json=base_body(), headers=DEMO)
    took = time.monotonic() - started
    assert r.status_code == 200 and r.headers["x-sgw-replay"] == "hit"
    assert floor_s <= took < (floor_s or 0.25) + 0.3
