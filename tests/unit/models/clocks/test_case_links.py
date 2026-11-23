from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sgw.contracts.vocab import NoRegretVerdict
from sgw.models.clocks.links import NO_ENSEMBLE, PASSED, CaseFacts, case_links
from sgw.models.clocks.ps17 import (
    CASE_CREWS,
    CASE_FUEL,
    CASE_HOSPITAL,
    CASE_POWER,
    CASE_PRESSURE,
    ps17_specs,
)
from sgw.models.clocks.service import QueueResult, compute_queue

INPUTS = json.loads((Path(__file__).with_name("data") / "wp06_helene_ps17_members.json").read_text("utf-8"))


def _facts(queue: QueueResult, proposals: dict[str, str] | None = None) -> dict[str, CaseFacts]:
    return {
        cid: CaseFacts(
            case_id=cid,
            title=c.case.title,
            effective_decide_by_utc=c.case.effective_decide_by_utc,
            on_critical_path=c.case.on_critical_path,
            verdict=c.case.no_regret_verdict,
            prerequisite_ids=tuple(c.case.prerequisite_ids),
            proposal_id=(proposals or {}).get(cid),
            next_advisory_utc=c.case.next_advisory_utc,
            verdict_basis_utc=c.verdict_basis_utc,
            effective_decide_by_p10_utc=c.path.effective["p10"],
        )
        for cid, c in queue.cases.items()
    }


def _queue(advisory: str) -> QueueResult:
    return compute_queue(ps17_specs(INPUTS["advisories"][advisory], INPUTS))


def test_ps17_chain_is_ordered_prerequisites_first_and_names_both_directions() -> None:
    facts = _facts(_queue("N"), {CASE_CREWS: "PRP-CREW", CASE_POWER: "PRP-POWER"})
    links = case_links(CASE_POWER, facts)
    order = [s.decision_case_id for s in links.chain]
    assert set(order) == {CASE_CREWS, CASE_FUEL, CASE_POWER, CASE_PRESSURE, CASE_HOSPITAL}
    assert order.index(CASE_CREWS) < order.index(CASE_POWER)
    assert order.index(CASE_FUEL) < order.index(CASE_POWER)
    assert order[-3:] == [CASE_POWER, CASE_PRESSURE, CASE_HOSPITAL]
    assert [s.order for s in links.chain] == [1, 2, 3, 4, 5]
    assert links.chain_order == 3
    assert links.blocked_by == sorted([CASE_CREWS, CASE_FUEL])
    assert links.blocks == [CASE_PRESSURE]
    assert {s.decision_case_id: s.proposal_id for s in links.chain}[CASE_POWER] == "PRP-POWER"
    crews = case_links(CASE_CREWS, facts)
    assert (crews.blocked_by, crews.blocks, crews.chain_order) == (
        [],
        [CASE_POWER],
        order.index(CASE_CREWS) + 1,
    )


def test_ps17_steps_name_the_assets_where_they_happen_and_the_crews_step_names_none() -> None:
    chain = case_links(CASE_POWER, _facts(_queue("N"))).chain
    places = {s.decision_case_id: s.place_ids for s in chain}
    assert places == {
        CASE_CREWS: None,
        CASE_FUEL: ["PS-17"],
        CASE_POWER: ["PS-17"],
        CASE_PRESSURE: ["WZ-PS17-CEDARFALL"],
        CASE_HOSPITAL: ["HSP-AIK-TALLOWBRANCH"],
    }
    assert "place_ids" not in chain[0].model_dump(mode="json")


def test_every_ps17_case_gets_the_power_timing_with_a_plain_reason() -> None:
    for advisory in ("N", "N+1"):
        facts = _facts(_queue(advisory))
        power = facts[CASE_POWER].verdict
        assert power is not NoRegretVerdict.NOT_APPLICABLE
        first = min(f.effective_decide_by_utc for f in facts.values())
        for cid in facts:
            links = case_links(cid, facts, now=first - timedelta(minutes=1))
            assert links.timing is power, (advisory, cid)
            if cid == CASE_POWER:
                assert links.timing_reason is None
            else:
                assert links.timing_reason and facts[CASE_POWER].title in links.timing_reason
                assert "DC-" not in links.timing_reason


def test_a_passed_decide_by_reads_decide_now_and_an_unlinked_case_explains_na() -> None:
    facts = _facts(_queue("N"))
    crews = facts[CASE_CREWS]
    passed = case_links(CASE_CREWS, facts, now=crews.effective_decide_by_utc + timedelta(minutes=1))
    assert (passed.timing, passed.timing_reason) == (NoRegretVerdict.DECIDE_NOW, PASSED)
    alone = {CASE_CREWS: CaseFacts(**{**crews.__dict__, "prerequisite_ids": ()})}
    links = case_links(CASE_CREWS, alone)
    assert (links.chain, links.chain_order, links.blocked_by, links.blocks) == ([], None, [], [])
    assert (links.timing, links.timing_reason) == (NoRegretVerdict.NOT_APPLICABLE, NO_ENSEMBLE)


def test_unknown_prerequisites_are_ignored() -> None:
    facts = _facts(_queue("N"))
    pressure = facts[CASE_PRESSURE]
    only = {CASE_PRESSURE: CaseFacts(**{**pressure.__dict__, "prerequisite_ids": ("DC-GONE",)})}
    assert case_links(CASE_PRESSURE, only).blocked_by == []


def test_before_next_advisory_names_the_advisory_and_the_earliest_deadline_it_misses() -> None:
    """DR High 6: "Before next advisory" beside deadlines hours after that advisory looked contradictory.
    The basis names the next advisory, the time to act on it and the earliest likely deadline it misses.
    Live demo case at the 11 AM advisory: PS-17 power decided now, bound by the crews' early deadline."""
    facts = _facts(_queue("N+1"))
    crews = facts[CASE_CREWS]
    assert crews.effective_decide_by_p10_utc is not None
    power = replace(
        facts[CASE_POWER],
        verdict=NoRegretVerdict.DECIDE_NOW,
        verdict_basis_utc=crews.effective_decide_by_p10_utc,
    )
    facts = {**facts, CASE_POWER: power}
    assert power.next_advisory_utc is not None
    now = power.next_advisory_utc - timedelta(hours=6)
    for cid in (CASE_POWER, CASE_CREWS, CASE_FUEL, CASE_PRESSURE):
        links = case_links(cid, facts, now)
        assert links.timing is NoRegretVerdict.DECIDE_NOW
        basis = links.timing_basis or ""
        assert basis.startswith("The next advisory at 17:00 ET takes 1 h to act on"), basis
        assert f"as early as {_et(crews.effective_decide_by_p10_utc)} (“{crews.title}”)" in basis, basis
        assert basis.endswith("Decide before the next advisory.")
    assert case_links(CASE_POWER, facts, power.next_advisory_utc).timing_basis is None


def test_can_wait_names_the_advisory_that_still_lands_in_time() -> None:
    facts = _facts(_queue("N"))
    power = facts[CASE_POWER]
    assert power.verdict is NoRegretVerdict.WAIT_FOR_NEXT_ADVISORY and power.next_advisory_utc is not None
    basis = case_links(CASE_POWER, facts, power.next_advisory_utc - timedelta(hours=1)).timing_basis or ""
    assert basis.startswith("The next advisory at 11:00 ET takes 1 h to act on"), basis
    assert basis.endswith("It can wait for that advisory.")


def _et(t: datetime) -> str:
    return t.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M ET")


def test_no_basis_once_the_decide_by_has_passed_or_without_an_ensemble() -> None:
    queue = _queue("N+1")
    facts = _facts(queue)
    crews = facts[CASE_CREWS]
    late = case_links(CASE_CREWS, facts, now=crews.effective_decide_by_utc + timedelta(minutes=1))
    assert late.timing_reason == PASSED and late.timing_basis is None
    alone = {CASE_CREWS: crews}
    assert case_links(CASE_CREWS, alone).timing_basis is None
