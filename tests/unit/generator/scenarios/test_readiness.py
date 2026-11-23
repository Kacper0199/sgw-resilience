from __future__ import annotations

from datetime import timedelta

import pytest

from sgw.contracts.vocab import ClockKind, NoRegretVerdict
from sgw.generator.scenarios import readiness as rd
from sgw.models.clocks import lead_times
from sgw.models.clocks.waterfall import TermKind


@pytest.fixture(scope="module")
def queue():
    return rd.queue()


def test_five_to_six_seeded_cases_all_rule_deadlines(queue) -> None:
    assert 5 <= len(queue.cases) <= 6
    for c in queue.cases.values():
        assert c.case.clock.clock_kind is ClockKind.RULE_DEADLINE
        assert c.case.clock.consequence_basis.kind is ClockKind.RULE_DEADLINE
        assert c.case.clock.decide_by_utc == c.case.clock.consequence_utc - timedelta(
            minutes=c.case.clock.action_lead_time_min
        )
        assert c.case.no_regret_verdict is NoRegretVerdict.NOT_APPLICABLE
    assert not queue.no_clock and not queue.dropped_edges


def test_rule_deadline_has_no_spread(queue) -> None:
    for c in queue.cases.values():
        k = c.case.clock
        assert k.consequence_p10_utc == k.consequence_utc == k.consequence_p90_utc


def test_readiness_runs_through_wp12_compute_queue(queue) -> None:
    from sgw.models.clocks.service import compute_queue

    direct = compute_queue(rd.specs(), now=rd.NOW)
    assert set(direct.cases) == set(queue.cases)
    for cid, c in queue.cases.items():
        assert direct.cases[cid].case == c.case
        assert direct.cases[cid].waterfall() == c.waterfall()
        assert c.lead.basis.basis_id == f"lead_time.{c.lead.key}"
    keys = {s.lead_key for s in rd.SEEDS}
    assert keys <= set(lead_times.registry())


def test_staging_lease_is_on_the_critical_path_of_the_mou(queue) -> None:
    stage = queue.cases["DC-RDY-STAGE-SANDHILL-LEASE"]
    mou = queue.cases["DC-RDY-MAID-TALON-MOU"]
    assert stage.path.bound_by_case_id == "DC-RDY-MAID-TALON-MOU"
    assert stage.case.on_critical_path and mou.case.on_critical_path
    lead = timedelta(minutes=stage.lead.minutes)
    assert stage.case.effective_decide_by_utc == mou.case.effective_decide_by_utc - lead
    assert stage.case.effective_decide_by_utc < stage.case.clock.decide_by_utc


def test_overdue_load_test_is_missed_and_the_rest_are_open(queue) -> None:
    missed = {cid for cid, c in queue.cases.items() if c.missed}
    assert missed == {"DC-RDY-GEN-PS52-LOADTEST"}
    assert all(c.case.effective_decide_by_utc > rd.NOW for cid, c in queue.cases.items() if cid not in missed)


def test_waterfall_rows_add_up_to_the_effective_decide_by(queue) -> None:
    for c in queue.cases.values():
        rows = c.waterfall_rows()
        anchor = sum(r.p50 for r in rows if r.term_kind is TermKind.ANCHOR)
        minutes = sum(r.p50 for r in rows if r.term_kind is not TermKind.ANCHOR)
        assert anchor + 60.0 * minutes == pytest.approx(c.case.effective_decide_by_utc.timestamp())


def test_moving_the_deadline_moves_every_decide_by_by_the_same_amount() -> None:
    shift = timedelta(days=3)
    seeds = [
        rd.ReadinessSeed(**{**s.__dict__, "deadline_utc": s.deadline_utc + shift})  # type: ignore[arg-type]
        for s in rd.SEEDS
    ]
    base, moved = rd.queue(), rd.queue(seeds)
    for cid in base.cases:
        delta = moved.cases[cid].case.effective_decide_by_utc - base.cases[cid].case.effective_decide_by_utc
        assert delta == shift


def test_budget_cut_keeps_the_three_d022_cases() -> None:
    keep = [s.case_id for s in sorted(rd.SEEDS, key=lambda s: s.priority)[:3]]
    assert keep == ["DC-RDY-GEN-PS52-LOADTEST", "DC-RDY-FUEL-PS38-PS52-TOPUP", "DC-RDY-VEG-FDR2207-2231"]
    q = rd.queue([s for s in rd.SEEDS if s.case_id in keep])
    assert len(q.cases) == 3


def test_lead_times_stay_inside_the_k16_bound() -> None:
    keys = {s.lead_key for s in rd.SEEDS}
    assert all(0 < lead_times.lead_time(k).minutes <= 60 * 24 * 14 for k in keys)
