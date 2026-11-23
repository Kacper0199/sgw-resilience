"""Golden vectors for the PS-17 hinge (synthetic Helene world).

Story of record: the water-twin member table `data/artefacts/water_twin/ps17_clock_members.json`
(WP-13: drain to the state floor at the critical service node, the hospital connection). Effective decide-by
04:45Z at advisory N and 03:29Z at N+1 (-76 min); verdict wait -> decide_now.

Legacy reference: WP-06 member inputs `data/wp06_helene_ps17_members.json` (station-sensor drain, D-068
values 05:44Z -> 04:28Z, wait -> act_now) stay as a regression of the clock service against WP-06's
independent `data/wp06_truth_clocks.json` (compared within a tolerance, not copied) and keep their WP-06
basis ids. Expected values below are this service's outputs on those inputs.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from sgw.contracts.vocab import NoRegretVerdict
from sgw.models.clocks.ps17 import (
    CASE_CREWS,
    CASE_FUEL,
    CASE_HOSPITAL,
    CASE_POWER,
    CASE_PRESSURE,
    ps17_specs,
)
from sgw.models.clocks.service import QueueResult, compute_queue
from sgw.models.clocks.waterfall import TermKind

DATA = Path(__file__).with_name("data")
REPO = Path(__file__).resolve().parents[4]
TWIN_TABLE = REPO / "data" / "artefacts" / "water_twin" / "ps17_clock_members.json"
TWIN = json.loads(TWIN_TABLE.read_text(encoding="utf-8"))
INPUTS = json.loads((DATA / "wp06_helene_ps17_members.json").read_text(encoding="utf-8"))
WP06 = json.loads((DATA / "wp06_truth_clocks.json").read_text(encoding="utf-8"))

# case: (consequence P10, P50, P90, decide-by P50, effective P50, on critical path, share ppm, verdict)
WAIT = "wait_for_next_advisory"
Golden = dict[str, dict[str, tuple[str, str, str, str, str, bool, int | None, str]]]
TWIN_GOLDEN: Golden = {
    "N": {
        CASE_CREWS: ("27T04:52", "27T06:15", "27T07:22", "27T01:15", "26T23:45", True, None, "n/a"),
        CASE_FUEL: ("28T16:20", "28T17:36", "28T18:38", "28T16:06", "27T03:15", True, None, "n/a"),
        CASE_POWER: ("27T06:20", "27T07:45", "27T09:12", "27T05:15", "27T04:45", True, 325000, WAIT),
        CASE_PRESSURE: ("27T06:20", "27T07:45", "27T09:12", "27T07:15", "27T07:15", True, None, "n/a"),
        CASE_HOSPITAL: ("27T12:20", "27T13:45", "27T15:12", "27T11:45", "27T11:45", False, None, "n/a"),
    },
    "N+1": {
        CASE_CREWS: ("27T04:00", "27T05:00", "27T06:15", "27T00:00", "26T22:29", True, None, "n/a"),
        CASE_FUEL: ("28T15:35", "28T16:29", "28T17:36", "28T14:59", "27T01:59", True, None, "n/a"),
        CASE_POWER: ("27T05:13", "27T06:29", "27T08:14", "27T03:59", "27T03:29", True, 925000, "decide_now"),
        CASE_PRESSURE: ("27T05:13", "27T06:29", "27T08:14", "27T05:59", "27T05:59", True, None, "n/a"),
        CASE_HOSPITAL: ("27T11:13", "27T12:29", "27T14:14", "27T10:29", "27T10:29", False, None, "n/a"),
    },
}
GOLDEN: Golden = {
    "N": {
        CASE_CREWS: ("27T04:52", "27T06:15", "27T07:22", "27T01:15", "27T00:44", True, None, "n/a"),
        CASE_FUEL: ("28T16:20", "28T17:36", "28T18:38", "28T16:06", "27T04:14", True, None, "n/a"),
        CASE_POWER: ("27T07:17", "27T08:44", "27T09:35", "27T06:14", "27T05:44", True, 325000, WAIT),
        CASE_PRESSURE: ("27T07:17", "27T08:44", "27T09:35", "27T08:14", "27T08:14", True, None, "n/a"),
        CASE_HOSPITAL: ("27T13:17", "27T14:44", "27T15:35", "27T12:44", "27T12:44", False, None, "n/a"),
    },
    "N+1": {
        CASE_CREWS: ("27T04:00", "27T05:00", "27T06:15", "27T00:00", "26T23:28", True, None, "n/a"),
        CASE_FUEL: ("28T15:35", "28T16:29", "28T17:36", "28T14:59", "27T02:58", True, None, "n/a"),
        CASE_POWER: ("27T06:14", "27T07:28", "27T08:44", "27T04:58", "27T04:28", True, 925000, "act_now"),
        CASE_PRESSURE: ("27T06:14", "27T07:28", "27T08:44", "27T06:58", "27T06:58", True, None, "n/a"),
        CASE_HOSPITAL: ("27T12:14", "27T13:28", "27T14:44", "27T11:28", "27T11:28", False, None, "n/a"),
    },
}


def _t(short: str) -> datetime:
    return datetime.fromisoformat(f"2024-09-{short}:00+00:00")


def _queue(adv: str, table: dict[str, Any] = INPUTS) -> QueueResult:
    a = table["advisories"][adv]
    now = datetime.fromisoformat(a["issued_utc"].replace("Z", "+00:00"))
    return compute_queue(ps17_specs(a, table), now=now)


def _twin(adv: str) -> QueueResult:
    return _queue(adv, TWIN)


@pytest.mark.parametrize("adv", ["N", "N+1"])
@pytest.mark.parametrize("which", ["twin", "wp06"])
def test_golden_vectors(adv: str, which: str) -> None:
    q = _queue(adv, TWIN if which == "twin" else INPUTS)
    golden = TWIN_GOLDEN if which == "twin" else GOLDEN
    assert q.no_clock == {}
    for cid, (c10, c50, c90, db, eff, crit, share, verdict) in golden[adv].items():
        case = q.cases[cid].case
        k = case.clock
        assert (k.consequence_p10_utc, k.consequence_utc, k.consequence_p90_utc) == (
            _t(c10),
            _t(c50),
            _t(c90),
        )
        assert k.decide_by_utc == _t(db)
        assert case.effective_decide_by_utc == _t(eff)
        assert case.on_critical_path is crit
        assert case.no_regret_share_ppm == share
        assert case.no_regret_verdict.value == verdict


def test_d075_twin_clock_is_the_story_of_record() -> None:
    n, n1 = _twin("N").cases[CASE_POWER], _twin("N+1").cases[CASE_POWER]
    assert (n.case.effective_decide_by_utc, n1.case.effective_decide_by_utc) == (
        _t("27T04:45"),
        _t("27T03:29"),
    )
    assert (n1.case.clock.decide_by_utc - n.case.clock.decide_by_utc) == timedelta(minutes=-76)
    assert n.case.no_regret_verdict is NoRegretVerdict.WAIT_FOR_NEXT_ADVISORY
    assert n1.case.no_regret_verdict is NoRegretVerdict.DECIDE_NOW
    assert (n.case.no_regret_share_ppm, n1.case.no_regret_share_ppm) == (325000, 925000)


def test_d075_decide_now_because_the_next_advisory_comes_too_late() -> None:
    q = _twin("N+1")
    power = q.cases[CASE_POWER]
    assert power.case.next_advisory_utc == _t("26T21:00")
    assert power.verdict_basis_utc == q.cases[CASE_CREWS].path.effective["p10"] == _t("26T21:13")


@pytest.mark.parametrize("adv", ["N", "N+1"])
def test_twin_clock_cites_the_twin_bases_and_the_service_connection_floor(adv: str) -> None:
    computed = _twin(adv).cases[CASE_POWER]
    by_kind = {r.term_kind: r for r in computed.waterfall_rows()}
    drain = by_kind[TermKind.TERM]
    twin = TWIN["water_twin"]
    assert drain.basis is not None
    assert drain.basis.model_dump(mode="json") == twin["drain_basis"]
    assert drain.basis.basis_id == "water_twin.zone_drain_critical_node"
    wf = computed.waterfall()
    assert wf.consequence_basis.basis_id == "water_twin.zone_drain_critical_node"
    assert wf.consequence_basis.basis_version == twin["drain_basis"]["basis_version"]
    assert wf.consequence_basis.citation == (
        "rule.sc_service_pressure_normal: SC R.61-58.7.E(7) 25 psi normal operation"
    )
    assert wf.bound_by_case_id == CASE_PRESSURE
    fuel = _twin(adv).cases[CASE_FUEL].waterfall()
    assert fuel.consequence_basis.model_dump(mode="json") == twin["generator_runtime_basis"]


@pytest.mark.parametrize("adv", ["N", "N+1"])
def test_twin_critical_path_chain(adv: str) -> None:
    q = _twin(adv)
    crews = q.cases[CASE_CREWS]
    assert crews.path.binding_chain == (CASE_CREWS, CASE_POWER, CASE_PRESSURE)
    power = q.cases[CASE_POWER].case
    expected = q.cases[CASE_PRESSURE].case.effective_decide_by_utc - timedelta(minutes=150)
    assert power.effective_decide_by_utc == expected
    assert crews.case.effective_decide_by_utc == power.effective_decide_by_utc - timedelta(minutes=300)


def test_ps17_hinge_moves_earlier_and_flips_to_act_now() -> None:
    n, n1 = _queue("N").cases[CASE_POWER], _queue("N+1").cases[CASE_POWER]
    assert (n1.case.clock.decide_by_utc - n.case.clock.decide_by_utc) == timedelta(minutes=-76)
    assert n.case.no_regret_verdict is NoRegretVerdict.WAIT_FOR_NEXT_ADVISORY
    assert n1.case.no_regret_verdict is NoRegretVerdict.ACT_NOW


@pytest.mark.parametrize("adv", ["N", "N+1"])
@pytest.mark.parametrize("case_id", [CASE_CREWS, CASE_FUEL, CASE_POWER, CASE_PRESSURE, CASE_HOSPITAL])
@pytest.mark.parametrize("which", ["twin", "wp06"])
def test_waterfall_rows_sum_at_every_quantile(adv: str, case_id: str, which: str) -> None:
    computed = _queue(adv, TWIN if which == "twin" else INPUTS).cases[case_id]
    rows = computed.waterfall_rows()
    k = computed.case.clock
    targets = {
        "p10": (k.consequence_p10_utc, computed.path.effective["p10"]),
        "p50": (k.consequence_utc, computed.path.effective["p50"]),
        "p90": (k.consequence_p90_utc, computed.path.effective["p90"]),
    }
    for q, (consequence, effective) in targets.items():
        anchor = getattr(rows[0], q)
        cons_rows = [r for r in rows[1:] if r.term_kind in (TermKind.TERM, TermKind.ENSEMBLE_NONADDITIVITY)]
        assert anchor + 60 * sum(getattr(r, q) for r in cons_rows) == pytest.approx(consequence.timestamp())
        assert anchor + 60 * sum(getattr(r, q) for r in rows[1:]) == pytest.approx(effective.timestamp())


@pytest.mark.parametrize("adv", ["N", "N+1"])
def test_wp06_table_keeps_its_wp06_basis_ids(adv: str) -> None:
    computed = _queue(adv).cases[CASE_POWER]
    rows = computed.waterfall_rows()
    by_kind = {r.term_kind: r for r in rows}
    assert rows[0].term_kind is TermKind.ANCHOR
    assert rows[0].basis is not None and rows[0].basis.basis_id == "outage.ps17_feeder_exposure"
    drain = by_kind[TermKind.TERM]
    assert drain.basis is not None and drain.basis.basis_id == "water_twin.ps17_tank_drain"
    assert drain.context_p10 is not None and drain.context_p90 is not None
    assert drain.context_p10 <= drain.p50 <= drain.context_p90
    lead = by_kind[TermKind.LEAD_TIME]
    assert lead.basis is not None and lead.basis.basis_id == "lead_time.portable_generator_hookup"
    assert by_kind[TermKind.CRITICAL_PATH].basis is None
    if TermKind.ENSEMBLE_NONADDITIVITY in by_kind:
        assert by_kind[TermKind.ENSEMBLE_NONADDITIVITY].basis is None
    wf = computed.waterfall()
    assert wf.bound_by_case_id == CASE_PRESSURE
    assert wf.lead_time_basis.citation == "SOP-WTR-4.2"
    assert wf.consequence_basis.citation == "SC R.61-58.7.E(7) 25 psi floor"
    assert wf.decide_by_utc == wf.consequence_utc - timedelta(minutes=wf.action_lead_time_min)


def test_wp06_table_reproduces_the_d068_values() -> None:
    n, n1 = _queue("N").cases[CASE_POWER].case, _queue("N+1").cases[CASE_POWER].case
    assert (n.effective_decide_by_utc, n1.effective_decide_by_utc) == (_t("27T05:44"), _t("27T04:28"))
    assert (n.no_regret_share_ppm, n1.no_regret_share_ppm) == (325000, 925000)


def test_verdict_basis_is_earliest_p10_over_prerequisites() -> None:
    q = _queue("N+1")
    power = q.cases[CASE_POWER]
    closure = [CASE_POWER, CASE_FUEL, CASE_CREWS]
    assert power.verdict_basis_utc == min(q.cases[c].path.effective["p10"] for c in closure)
    assert power.verdict_basis_utc == q.cases[CASE_CREWS].path.effective["p10"]


def test_critical_path_propagation_chain() -> None:
    q = _queue("N")
    crews = q.cases[CASE_CREWS]
    assert crews.path.binding_chain == (CASE_CREWS, CASE_POWER, CASE_PRESSURE)
    assert crews.path.slack_min == 31
    power = q.cases[CASE_POWER].case
    expected = q.cases[CASE_PRESSURE].case.effective_decide_by_utc - timedelta(minutes=150)
    assert power.effective_decide_by_utc == expected
    assert crews.case.effective_decide_by_utc == power.effective_decide_by_utc - timedelta(minutes=300)


def _diff_min(a: str, b: datetime) -> float:
    return abs((datetime.fromisoformat(a.replace("Z", "+00:00")) - b) / timedelta(minutes=1))


@pytest.mark.parametrize("adv", ["N", "N+1"])
def test_agrees_with_wp06_reference_within_two_minutes(adv: str) -> None:
    ref: dict[str, Any] = WP06["advisories"][adv]
    q = _queue(adv)
    for cid, r in ref.items():
        case = q.cases[cid].case
        k = case.clock
        for ref_t, ours in zip(
            r["consequence"], (k.consequence_p10_utc, k.consequence_utc, k.consequence_p90_utc), strict=True
        ):
            assert _diff_min(ref_t, ours) <= 2
        assert _diff_min(r["decide_by"], k.decide_by_utc) <= 2
        assert _diff_min(r["effective"], case.effective_decide_by_utc) <= 2
        assert r["on_critical_path"] == case.on_critical_path
        assert r["share_ppm"] == case.no_regret_share_ppm
        assert r["verdict"] == case.no_regret_verdict.value
