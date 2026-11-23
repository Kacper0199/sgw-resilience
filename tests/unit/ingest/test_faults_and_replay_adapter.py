from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sgw.contracts.adapter import FaultKind
from sgw.ingest.adapters.registry import scenario_adapters
from sgw.ingest.adapters.replay import CursorError, ReplayAdapter, decode_cursor
from sgw.ingest.faults import FaultConfigError, FaultSpec, apply_faults, faults_from_env
from sgw.ingest.scenario import ScenarioError, available_scenarios, load_scenario

MICRO = load_scenario("helene_micro")
WATER = MICRO.by_source()["scada-water"]


def test_scenario_loads_by_name_and_splits_source_from_platform_events() -> None:
    assert "helene_micro" in available_scenarios()
    assert len(MICRO.source_events()) + len(MICRO.platform_events()) == len(MICRO.events)
    assert all(e.source_id != "sgw-platform" for e in MICRO.source_events())
    with pytest.raises(ScenarioError):
        load_scenario("llm")
    with pytest.raises(ScenarioError, match="available"):
        load_scenario("no_such_storm")


def test_env_grammar_selects_sources_and_params() -> None:
    env = {
        "FAULT_FEED_DELAY": "oms:90,ami-headend",
        "FAULT_FEED_DUPLICATE": "*",
        "FAULT_FEED_GAP": "oms:2024-09-26T12:00:00Z/2024-09-26T18:00:00Z",
    }
    oms = faults_from_env(env, "oms")
    assert FaultSpec(FaultKind.DELAY, {"minutes": 90}) in oms
    assert any(s.kind is FaultKind.DUPLICATE for s in oms)
    assert any(s.kind is FaultKind.GAP and s.params["from_utc"].hour == 12 for s in oms)
    assert faults_from_env(env, "lims") == [FaultSpec(FaultKind.DUPLICATE, {})]
    with pytest.raises(FaultConfigError):
        faults_from_env({"FAULT_FEED_DELAY": "oms:soon"}, "oms")
    with pytest.raises(FaultConfigError):
        faults_from_env({"FAULT_FEED_GAP": "oms:2024-09-26T12:00:00"}, "oms")


def test_faults_are_deterministic() -> None:
    specs = [FaultSpec(k) for k in FaultKind if k is not FaultKind.FLOOD_10X]
    first = apply_faults(WATER, specs)
    second = apply_faults(WATER, specs)
    assert [e.dedup_key for e in first.events] == [e.dedup_key for e in second.events]
    assert [r.reason for r in first.rejects] == [r.reason for r in second.rejects]
    assert first.gaps == second.gaps


def test_delay_moves_knowledge_not_event_time() -> None:
    out = apply_faults(WATER, [FaultSpec(FaultKind.DELAY, {"minutes": 30})]).events
    assert [e.event_time for e in out] == [e.event_time for e in WATER]
    assert all(b.known_at - a.known_at == timedelta(minutes=30) for a, b in zip(WATER, out, strict=True))


def test_gap_drops_window_and_marks_coverage_incomplete() -> None:
    adapter = ReplayAdapter("scada-water", WATER, faults=[FaultSpec(FaultKind.GAP)])
    page = adapter.fetch_since(None)
    assert len(page.events) < len(WATER)
    assert not page.coverage.complete
    gap = adapter.gaps[0]
    assert all(not gap.from_utc <= e.event_time < gap.to_utc for e in page.events)


def test_schema_drift_is_rejected_once() -> None:
    adapter = ReplayAdapter("scada-water", WATER, faults=[FaultSpec(FaultKind.SCHEMA_DRIFT)])
    adapter.fetch_since(None)
    rejects = adapter.drain_rejects()
    assert len(rejects) == len(WATER) // 5
    assert all(r.reason.startswith("schema:") for r in rejects)
    assert adapter.drain_rejects() == []
    assert adapter.health().error_rate_ppm > 0


def test_clock_gates_delivery_and_cursor_resumes() -> None:
    adapter = ReplayAdapter("scada-water", WATER, page_size=1000)
    cutoff = WATER[9].scenario_known_at
    adapter.set_clock(cutoff)
    first = adapter.fetch_since(None)
    assert all(e.scenario_known_at <= cutoff for e in first.events)
    adapter.set_clock(None)
    rest = adapter.fetch_since(first.next_cursor)
    assert len(first.events) + len(rest.events) == len(WATER)
    assert adapter.fetch_since(rest.next_cursor).events == []


def test_health_reports_lag_and_age() -> None:
    adapter = ReplayAdapter("scada-water", WATER)
    assert adapter.health().last_success_at is None
    adapter.set_clock(datetime(2024, 9, 27, 10, tzinfo=UTC))
    adapter.fetch_since(None)
    health = adapter.health()
    assert health.product_age_s == 3600
    assert health.ingest_lag_s is not None and health.ingest_lag_s >= 0


def test_bad_cursor_and_foreign_events_are_refused() -> None:
    with pytest.raises(CursorError):
        decode_cursor("n1:abc")
    with pytest.raises(ValueError, match="other sources"):
        ReplayAdapter("oms", WATER)


def test_registry_builds_one_adapter_per_source_with_env_faults() -> None:
    adapters = scenario_adapters(MICRO, env={"FAULT_FEED_FLOOD_10X": "oms"})
    by_id = {a.source_id: a for a in adapters}
    assert set(by_id) == set(MICRO.by_source())
    assert len(by_id["oms"].fetch_since(None).events) == 10 * len(MICRO.by_source()["oms"])
    with_platform = scenario_adapters(MICRO, env={}, include_platform=True)
    assert "sgw-platform" in {a.source_id for a in with_platform}


def test_resumed_cursor_does_not_repeat_rejects() -> None:
    def make() -> ReplayAdapter:
        return ReplayAdapter("scada-water", WATER, page_size=10, faults=[FaultSpec(FaultKind.SCHEMA_DRIFT)])

    first = make()
    page = first.fetch_since(None)
    early = first.drain_rejects()
    resumed = make()
    cursor: str | None = page.next_cursor
    late = []
    while True:
        result = resumed.fetch_since(cursor)
        late.extend(resumed.drain_rejects())
        if not result.events:
            break
        cursor = result.next_cursor
    assert len(early) + len(late) == len(WATER) // 5
    assert not {r.record["dedup_key"] for r in early} & {r.record["dedup_key"] for r in late}
