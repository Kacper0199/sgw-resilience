from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from sgw.contracts.vocab import CommitmentState
from sgw.models.clocks import lead_times
from sgw.models.commitments import learning, plan, watch

PROMISED = datetime(2024, 9, 27, 6, 40, tzinfo=UTC)
BIND = {"$station": "PS-17", "$generator": "GEN-X", "$targets": ["Y1", "Y2"]}
HELENE = Path(__file__).resolve().parents[4] / "data" / "fixtures" / "helene" / "eam.jsonl"


def _ev(t: datetime, etype: str, **payload: Any) -> dict[str, Any]:
    return {"type": etype, "event_time": t.isoformat(), "event_id": f"e-{t:%H%M}-{etype}", "payload": payload}


def _wo(
    t: datetime, status: str, work_type: str = "portable_generator_hookup", asset: str = "PS-17"
) -> dict[str, Any]:
    return _ev(t, "WorkOrder", status=status, work_type=work_type, asset_id=asset, work_order_id="WO-T-1")


def _gen_plan() -> plan.Plan:
    return plan.build_plan("portable_generator_hookup", PROMISED, BIND)


def test_generator_plan_is_latest_finish_from_the_promise() -> None:
    p = _gen_plan()
    hookup = lead_times.lead_time("portable_generator_hookup").minutes
    refill = lead_times.lead_time("pump_restart_refill").minutes
    dues = [m.due_utc for m in p.milestones]
    assert dues == [
        PROMISED - timedelta(minutes=hookup + refill),
        PROMISED - timedelta(minutes=refill),
        PROMISED,
    ]
    assert p.milestones[0].signal["asset_id"] == "PS-17"
    assert p.milestones[2].signal["min_value"] == 25


def test_unknown_lead_key_has_no_plan() -> None:
    assert not plan.supported("outage_report_drafting")
    assert plan.lead_key_of({"basis_id": "lead_time.fuel_truck_dispatch"}) == "fuel_truck_dispatch"
    assert plan.lead_key_of({"basis_id": "water_twin.x"}) is None


def test_on_track_until_the_first_due_then_drifts_past_tolerance() -> None:
    ms = list(_gen_plan().milestones)
    first_due = ms[0].due_utc
    tol = 15
    assert watch.assess(ms, PROMISED, first_due, tol).state is CommitmentState.ON_TRACK
    assert watch.assess(ms, PROMISED, first_due + timedelta(minutes=10), tol).state is CommitmentState.AT_RISK
    late = watch.assess(ms, PROMISED, first_due + timedelta(minutes=16), tol)
    assert late.state is CommitmentState.DRIFTED
    assert late.drift_min == 16
    assert late.milestone_seq == 1
    assert late.projected_utc == PROMISED + timedelta(minutes=16)


def test_milestones_met_in_order_and_pressure_counts_only_after_connection() -> None:
    ms = list(_gen_plan().milestones)
    seen: dict[int, set[str]] = {}
    t0 = ms[0].due_utc - timedelta(minutes=30)
    ms = watch.observe(
        ms, _ev(t0, "DeviceState", device_kind="pressure_sensor", asset_id="PS-17", value=60.0), seen
    )
    assert all(m.met_utc is None for m in ms)
    ms = watch.observe(ms, _wo(t0, "open"), seen)
    ms = watch.observe(ms, _wo(t0 + timedelta(minutes=150), "in_progress"), seen)
    ms = watch.observe(
        ms,
        _ev(
            t0 + timedelta(minutes=170),
            "DeviceState",
            device_kind="pressure_sensor",
            asset_id="PS-17",
            value=24.9,
        ),
        seen,
    )
    assert ms[2].met_utc is None
    ms = watch.observe(
        ms,
        _ev(
            t0 + timedelta(minutes=175),
            "DeviceState",
            device_kind="pressure_sensor",
            asset_id="PS-17",
            value=30.0,
        ),
        seen,
    )
    assert [m.met_utc is not None for m in ms] == [True, True, True]
    assert watch.assess(ms, PROMISED, PROMISED, 15).state is CommitmentState.MET


def test_a_late_met_milestone_pushes_the_projection() -> None:
    ms = list(_gen_plan().milestones)
    seen: dict[int, set[str]] = {}
    ms = watch.observe(ms, _wo(ms[0].due_utc + timedelta(minutes=40), "open"), seen)
    a = watch.assess(ms, PROMISED, ms[0].due_utc + timedelta(minutes=41), 15)
    assert a.state is CommitmentState.DRIFTED
    assert a.drift_min == 40


def test_crews_staged_needs_every_target_yard() -> None:
    p = plan.build_plan("crew_mobilise_and_stage", PROMISED, BIND)
    ms = list(p.milestones)
    seen: dict[int, set[str]] = {}
    t = PROMISED - timedelta(hours=2)
    ms = watch.observe(ms, _ev(t, "CrewStatus", status="enroute", location_id="Y1", crew_id="C1"), seen)
    ms = watch.observe(ms, _ev(t, "CrewStatus", status="staged", location_id="Y1", crew_id="C1"), seen)
    assert ms[1].met_utc is None
    ms = watch.observe(
        ms, _ev(t + timedelta(minutes=5), "CrewStatus", status="staged", location_id="Y2"), seen
    )
    assert ms[1].met_utc == t + timedelta(minutes=5)


def test_learning_observes_helene_work_orders() -> None:
    import json

    events = [json.loads(line) for line in HELENE.read_text(encoding="utf-8").splitlines()]
    obs = learning.observe(e for e in events if "payload" in e)
    by_key = {o.key: o for o in obs}
    assert by_key["portable_generator_hookup"].work_order_id == "WO-SYN-PS17-GEN-01"
    assert (
        by_key["portable_generator_hookup"].minutes
        == lead_times.lead_time("portable_generator_hookup").minutes
    )
    fuel = by_key["fuel_truck_dispatch"]
    assert fuel.work_order_id == "WO-SYN-FUEL-01"
    assert fuel.minutes > lead_times.lead_time("fuel_truck_dispatch").minutes
    rows = {r.key: r for r in learning.evidence(obs, "fixture:helene")}
    assert rows["portable_generator_hookup"].proposed_min is None
    assert rows["portable_generator_hookup"].verdict.startswith("keep")
    f = rows["fuel_truck_dispatch"]
    assert f.n == 1
    assumed = lead_times.lead_time("fuel_truck_dispatch").minutes
    z = 1 / (1 + float(plan.policy_value("credibility_prior_n")))
    raw = z * fuel.minutes + (1 - z) * assumed
    assert f.proposed_min is not None
    assert raw <= f.proposed_min < raw + int(plan.policy_value("rounding_min"))
    assert assumed < f.proposed_min < fuel.minutes
    assert f.observations[0]["event_ids"][0] and f.source == "fixture:helene"


@pytest.mark.parametrize("n", [1, 3, 30])
def test_credibility_moves_towards_the_evidence_with_n(n: int) -> None:
    assumed = lead_times.lead_time("fuel_truck_dispatch").minutes
    obs = [
        learning.Observation("fuel_truck_dispatch", f"WO-{i}", "G", "a", "b", assumed * 3, ("x", "y"))
        for i in range(n)
    ]
    row = {r.key: r for r in learning.evidence(obs, "test")}["fuel_truck_dispatch"]
    k = float(plan.policy_value("credibility_prior_n"))
    assert row.credibility_z == pytest.approx(n / (n + k), abs=1e-4)
    assert row.proposed_min is not None
    assert assumed < row.proposed_min <= assumed * 3 + int(plan.policy_value("rounding_min"))


def test_no_observations_proposes_nothing() -> None:
    rows = learning.evidence([], "test")
    assert all(r.proposed_min is None and r.n == 0 for r in rows)
