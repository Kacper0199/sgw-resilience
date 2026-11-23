"""Hurricane Ian scenario pack (`data/scenarios/ian-2022`): the pack loads, keeps its moments inside
the window, labels every number scripted, gives each moment open decisions with future deadlines, gives every
signing function a decision, and never reuses a Helene id."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sgw.api.clock import scenario_def
from sgw.api.scenario_info import scenario_jumps, scenario_period
from sgw.approval import policy_data
from sgw.contracts.approval import tier_rule
from sgw.models.clocks import zone_cases
from sgw.models.clocks.lead_times import registry
from sgw.models.clocks.service import compute_queue
from sgw.rules import injects
from sgw.scenarios import packs, reads

LABEL = "Scripted exercise data (synthetic)"


@pytest.fixture(scope="module")
def ian() -> packs.Pack:
    return packs.load("ian")


def test_the_pack_is_the_ian_clock_and_period(ian: packs.Pack) -> None:
    sdef = scenario_def("ian")
    assert (sdef.window_start, sdef.window_end) == (ian.window_start, ian.window_end)
    assert sdef.bookmark("landfall") == datetime(2022, 9, 30, 18, 5, tzinfo=UTC)
    period = scenario_period("ian")
    assert period.title == "Hurricane Ian" and period.data_note == LABEL
    assert period.label == "28 Sep – 3 Oct 2022"
    assert [j.label for j in scenario_jumps("ian")] == [m.label for m in ian.moments]
    assert not packs.is_pack("helene") and packs.get("helene") is None


def test_every_inject_is_scripted_with_a_known_lead_and_its_own_ids(ian: packs.Pack) -> None:
    leads = registry()
    helene = {h.key for h in injects.load().hits}
    for hit in ian.msel.hits:
        assert hit.params["data_label"] == LABEL
        assert hit.clock is not None and hit.clock.lead_key in leads
        assert hit.key not in helene and "IAN-" in hit.case_id
        assert zone_cases.proposal_base(hit.key, ian.proposal_prefix).startswith("PRP-IAN-")
    assert all(a.name.endswith("(synthetic)") for a in ian.msel.assets)
    targets = {t for h in ian.msel.hits for t in h.target_ids}
    assert targets - ian.asset_ids == {"SGW-ELECTRIC-TERRITORY"}


@pytest.mark.parametrize("index", [0, 1, 2])
def test_each_moment_has_open_decisions_with_future_deadlines(ian: packs.Pack, index: int) -> None:
    now = ian.moments[index].at
    hits = injects.active(now, ian.msel.hits)
    assert len(hits) >= 3
    queue = compute_queue([zone_cases.case_spec(h, ian.msel.regions[h.case_id]) for h in hits], now=now)
    for case_id, case in queue.cases.items():
        assert case.clock.decide_by_utc > now, case_id


def test_every_signing_function_gets_a_decision_and_the_policy_allows_each_proposer(ian: packs.Pack) -> None:
    functions = {f.value for h in ian.msel.hits for f in tier_rule(h.action_type).approver_functions}
    assert {"command", "operations", "logistics", "water_operations", "compliance"} <= functions
    rules = policy_data.build()["rules"]
    for hit in ian.msel.hits:
        assert hit.proposer in rules[hit.action_type.value]["proposers"], hit.key


def test_the_scripted_curve_and_reads(ian: packs.Pack) -> None:
    before, landfall, after = (m.at for m in ian.moments)
    assert ian.customers_out(before) == 0
    hour = ian.feed_hour(landfall)
    assert hour is not None
    assert reads.county_outages(ian, landfall).customers_out_now == ian.customers_out(hour)
    assert sum(ian.counties_out(landfall).values()) == ian.customers_out(landfall)
    peak_at, peak = ian.peak()
    assert peak_at == dict(ian.bookmarks)["peak"] and peak > ian.customers_out(after) > 0
    st = reads.status(ian, after)
    assert st is not None and st.trend == "falling"
    brief = reads.brief(ian, after, [])
    assert brief.caveat.startswith(LABEL) and {n.key for n in brief.numbers} == {
        "customers_out",
        "critical_facilities",
        "water_zones_advisory",
        "crews_working",
    }
    advisories = reads.advisories(ian, landfall)
    detail = reads.advisory(ian, advisories[-1].advisory_label, landfall)
    assert detail.cone.radius_nmi == [] and len(detail.official_track) == 1
    assert detail.analysis_track[-1][0] <= landfall.strftime("%Y-%m-%dT%H:%M:%SZ")
    with pytest.raises(reads.NotIssued):
        reads.advisory(ian, ian.advisories()[-1].label, before)


def test_the_crew_roster_adds_up_to_the_scripted_counts(ian: packs.Pack) -> None:
    for moment in ian.moments:
        roster = ian.roster(moment.at)
        counts = ian.crew_counts(moment.at)
        assert len(roster) == sum(counts.values())
        for status, n in counts.items():
            assert sum(1 for c in roster if c.status == status) == n
        assert all(c.location_id in ian.asset_ids for c in roster if c.status == "staged")
        assert len({c.crew_id for c in roster}) == len(roster)
    items = reads.crews(ian, ian.moments[2].at)
    assert all(i.actions == [] and i.provenance is not None for i in items)
