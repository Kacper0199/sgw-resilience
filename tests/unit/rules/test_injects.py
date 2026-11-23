"""Exercise injects (`data/synthetic/helene_injects.yaml`): every inject is well formed, labelled
synthetic, targets a known asset, gives each storm moment a real decision load with open clocks, and gives
every signing function something to sign."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sgw.approval import policy_data
from sgw.contracts.approval import EXERCISE_INJECT, tier_rule
from sgw.contracts.vocab import ActionType
from sgw.models.clocks import zone_cases
from sgw.models.clocks.lead_times import registry
from sgw.models.clocks.service import compute_queue
from sgw.rules import injects, zones

MOMENTS = {
    "at-n1": datetime(2024, 9, 26, 15, 5, tzinfo=UTC),
    "morning-after": datetime(2024, 9, 27, 12, 0, tzinfo=UTC),
    "etr-published": datetime(2024, 9, 28, 18, 0, tzinfo=UTC),
    "notices-lifted": datetime(2024, 9, 30, 12, 0, tzinfo=UTC),
}
NEVER = {ActionType.BOIL_WATER_NOTICE, ActionType.LIFT_BOIL_WATER_NOTICE, ActionType.PUBLISH_GLOBAL_ETR}


def test_every_inject_is_labelled_synthetic_and_has_a_known_lead_time() -> None:
    found = injects.load()
    assert found.hits and found.proposer == EXERCISE_INJECT
    leads = registry()
    for hit in found.hits:
        assert hit.params["data_label"] == "Scripted exercise inject (synthetic)"
        assert hit.params["known_at_utc"].endswith("Z")
        assert hit.clock is not None and hit.clock.lead_key in leads
        assert hit.case_id.startswith(f"DC-{hit.clock.step.value}-EX-")
        assert hit.action_type not in NEVER
    for asset in found.assets:
        assert asset.name.endswith("(synthetic)")


def test_targets_are_inject_assets_or_named_helene_assets() -> None:
    found = injects.load()
    named = zones.world().network["named"]
    known = {a.asset_id for a in found.assets} | {"SGW-ELECTRIC-TERRITORY", str(named["substation"]["id"])}
    known |= set(named["feeders"]) | set(named["yards"])
    for hit in found.hits:
        assert set(hit.target_ids) <= known, hit.key


def test_inject_ids_never_collide_with_the_story() -> None:
    story_cases = {h.case_id for h in zones.timeline()}
    for hit in injects.load().hits:
        assert hit.case_id not in story_cases
        assert zone_cases.proposal_base(hit.key, zone_cases.INJECT_PREFIX).startswith("PRP-EX-")


@pytest.mark.parametrize("moment", sorted(MOMENTS))
def test_each_storm_moment_has_several_open_inject_decisions(moment: str) -> None:
    now = MOMENTS[moment]
    found = injects.load()
    hits = injects.active(now)
    assert len(hits) >= 6, moment
    queue = compute_queue([zone_cases.case_spec(h, found.regions[h.case_id]) for h in hits], now=now)
    for case_id, case in queue.cases.items():
        assert case.clock.decide_by_utc > now, f"{case_id} is already past its decide-by at {moment}"


def test_every_signing_function_gets_an_inject() -> None:
    functions = {f.value for h in injects.load().hits for f in tier_rule(h.action_type).approver_functions}
    assert {"command", "operations", "logistics", "water_operations"} <= functions


def test_the_inject_proposer_is_in_the_policy_data() -> None:
    rules = policy_data.build()["rules"]
    allowed = {a for a, r in rules.items() if EXERCISE_INJECT in r["proposers"]}
    assert {h.action_type.value for h in injects.load().hits} <= allowed
    assert not allowed & {a.value for a in NEVER}


def test_a_window_out_of_order_is_refused() -> None:
    raw = {
        "version": "x",
        "proposer": EXERCISE_INJECT,
        "incident_id": "INC",
        "label": "Scripted exercise inject (synthetic)",
        "assets": [],
        "injects": [
            {
                "id": "EX-99",
                "title": "t",
                "action_type": "work_order_draft",
                "step": "D2",
                "domain": "electric",
                "region": "SC-45003",
                "targets": [],
                "known_at": "2024-09-27T10:00:00Z",
                "resolved_at": "2024-09-27T09:00:00Z",
                "anchor_utc": "2024-09-27T12:00:00Z",
                "anchor_label": "a",
                "lead_key": "silent_outage_patrol",
                "if_late": "x",
                "rationale": "r",
            }
        ],
    }
    with pytest.raises(ValueError, match="known_at must be before resolved_at"):
        injects.parse(raw)
