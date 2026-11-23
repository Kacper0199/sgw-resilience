from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from sgw.contracts.adapter import FaultKind
from sgw.ingest.faults import FaultSpec, apply_faults
from sgw.ingest.scenario import load_scenario
from sgw.pipeline import dq
from sgw.pipeline.registry import REGISTRY, AssetResult, AssetSpec, RegistryError, lineage, topo_order
from sgw.pipeline.runner import load_assets

EVENTS = load_scenario("helene_micro").source_events()


def _spec(name: str, *deps: str) -> AssetSpec:
    return AssetSpec(name, lambda ctx, conn: AssetResult(), deps, None, "")


def test_registered_assets_run_in_dependency_order() -> None:
    load_assets()
    order = [s.name for s in topo_order()]
    assert order.index("ingest.feeds") < order.index("ledger.relay") < order.index("ledger.reconcile")
    assert order.index("ingest.feeds") < order.index("observations")
    assert ("ingest.feeds", "ledger.relay") in lineage()
    assert all(spec.description for spec in REGISTRY.values())


def test_cycles_and_unknown_dependencies_are_refused() -> None:
    with pytest.raises(RegistryError, match="cycle"):
        topo_order(registry={"a": _spec("a", "b"), "b": _spec("b", "a")})
    with pytest.raises(RegistryError, match="unknown"):
        topo_order(registry={"a": _spec("a", "ghost")})
    with pytest.raises(RegistryError, match="unknown"):
        topo_order(["nope"], registry={"a": _spec("a")})


def test_clean_batch_passes_every_check() -> None:
    frame = dq.batch_frame(EVENTS)
    assert dq.schema_check("s", dq.ENVELOPE_SCHEMA, frame).passed
    assert dq.duplicate_check(frame).passed
    assert dq.out_of_order_check(frame).passed
    assert dq.late_check(frame).passed
    assert all(c.passed for c in dq.reject_checks(len(EVENTS), 0))


def test_faulted_batch_is_flagged() -> None:
    specs = [
        FaultSpec(FaultKind.DUPLICATE),
        FaultSpec(FaultKind.OUT_OF_ORDER),
        FaultSpec(FaultKind.DELAY, {"minutes": 600}),
    ]
    frame = dq.batch_frame(apply_faults(EVENTS, specs).events)
    assert not dq.duplicate_check(frame).passed
    assert not dq.out_of_order_check(frame).passed
    late = dq.late_check(frame)
    assert not late.passed and late.severity == "warn"


def test_pandera_schema_catches_bad_rows() -> None:
    frame = dq.batch_frame(EVENTS[:3])
    frame.loc[0, "coverage_ppm"] = 2_000_000
    frame.loc[1, "classification"] = "secret"
    result = dq.schema_check("ingest.envelope_schema", dq.ENVELOPE_SCHEMA, frame)
    assert not result.passed and result.severity == "error"
    assert result.observed.startswith("2 failure(s)")


def test_observation_schema_rejects_nan_and_duplicate_keys() -> None:
    at = pd.Timestamp("2024-09-27T01:00:00Z")
    frame = pd.DataFrame(
        {
            "source_id": ["scada-water"] * 3,
            "tag": ["PT-PS17-DISCH/discharge_pressure"] * 3,
            "observed_at": [at, at, pd.Timestamp("2024-09-27T01:15:00Z")],
            "known_at": [at, at, pd.Timestamp("2024-09-27T01:15:00Z")],
            "value": [61.0, 61.5, float("nan")],
            "unit": ["psi"] * 3,
            "quality": ["good"] * 3,
        }
    )
    assert not dq.schema_check("observations.schema", dq.OBSERVATION_SCHEMA, frame).passed


def test_reject_thresholds_and_freshness_rule() -> None:
    warn, error = dq.reject_checks(98, 2)
    assert not warn.passed and error.passed
    assert not dq.reject_checks(80, 20)[1].passed
    now = datetime(2024, 9, 27, 12, tzinfo=UTC)
    fresh = dq.freshness_check("scada-water", now - timedelta(seconds=60), now)
    stale = dq.freshness_check("scada-water", now - timedelta(hours=1), now)
    assert fresh.passed and fresh.freshness_limit_s == dq.freshness_limit("scada-water")
    assert not stale.passed and stale.severity == "warn"
    assert not dq.freshness_check("scada-water", None, now).passed


def test_feeds_that_report_on_change_are_late_only_when_their_data_arrives_late() -> None:
    now = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)
    quiet = dq.freshness_check("oms", None, now)
    assert quiet.passed and quiet.observed == "nothing reported yet"
    old = now - timedelta(hours=5)
    on_time = dq.freshness_check("fsm-crews", old, now, last_known_at=old + timedelta(seconds=300))
    assert on_time.passed and on_time.observed == "ingest lag 300 s"
    limit = dq.freshness_limit("fsm-crews")
    late = dq.freshness_check("fsm-crews", old, now, last_known_at=old + timedelta(seconds=limit + 1))
    assert not late.passed
    assert "fsm-crews" not in dq.REPORTS_ON_SCHEDULE and "scada-water" in dq.REPORTS_ON_SCHEDULE


def test_water_sensors_are_measured_against_their_fifteen_minute_reports() -> None:
    now = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)
    assert dq.freshness_check("scada-water", now - timedelta(minutes=5), now).passed
    assert not dq.freshness_check("scada-water", now - timedelta(minutes=31), now).passed


def test_observation_revisions_pass_but_same_instant_conflicts_fail() -> None:
    at = pd.Timestamp("2024-09-27T01:00:00Z")
    later = pd.Timestamp("2024-09-27T02:00:00Z")

    def frame(known: list[pd.Timestamp]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "source_id": ["scada-water"] * 2,
                "tag": ["PT-PS17-DISCH/discharge_pressure"] * 2,
                "observed_at": [at, at],
                "known_at": known,
                "value": [61.0, 61.4],
                "unit": ["psi"] * 2,
                "quality": ["good"] * 2,
            }
        )

    assert dq.schema_check("o", dq.OBSERVATION_SCHEMA, frame([at, later])).passed
    assert not dq.schema_check("o", dq.OBSERVATION_SCHEMA, frame([at, at])).passed
