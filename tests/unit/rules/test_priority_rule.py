"""Cross-domain priority rule `rule.ps17_pressure_floor` (PLAN section 2, D3: T3 `command` +
`water_operations`, proposer `system:rule:ps17_pressure_floor`)."""

from __future__ import annotations

import json
from pathlib import Path

from sgw.approval.policy import ReferencePolicy
from sgw.contracts.vocab import NoRegretVerdict
from sgw.models.ranking.params import critical_weights
from sgw.rules import priority

NETWORK = json.loads(
    (Path(__file__).resolve().parents[3] / "data" / "fixtures" / "helene" / "network.json").read_text("utf-8")
)
LINK = priority.ps17_link(NETWORK)


def test_link_reads_the_named_assets() -> None:
    assert (LINK.feeder_id, LINK.zone_id, LINK.critical_customer_id) == (
        "FDR-AIK-2207",
        "WZ-PS17-CEDARFALL",
        "HSP-AIK-TALLOWBRANCH",
    )
    assert LINK.feeder_customers == 1840 and LINK.generator_id == "MGEN-HALBERD-500"


def test_fires_only_on_the_critical_path_when_waiting_does_not_fit() -> None:
    kw = {"p_loss": 0.4, "case_id": "DC-D3-PS17-POWER"}
    assert not priority.evaluate(
        LINK, verdict=NoRegretVerdict.WAIT_FOR_NEXT_ADVISORY, on_critical_path=True, **kw
    ).fires
    assert not priority.evaluate(LINK, verdict=NoRegretVerdict.DECIDE_NOW, on_critical_path=False, **kw).fires
    for verdict in (NoRegretVerdict.ACT_NOW, NoRegretVerdict.DECIDE_NOW):
        out = priority.evaluate(LINK, verdict=verdict, on_critical_path=True, **kw)
        assert out.fires and out.target_ids == ("FDR-AIK-2207", "PS-17")
        assert out.params["rule_id"] == "rule.ps17_pressure_floor"


def test_ce_breakdown_counts_the_hospital_through_its_water() -> None:
    out = priority.evaluate(
        LINK,
        verdict=NoRegretVerdict.DECIDE_NOW,
        on_critical_path=True,
        p_loss=0.5,
        case_id="DC-D3-PS17-POWER",
    )
    assert out.breakdown is not None
    hospital = critical_weights()["hospital"]
    assert out.params["ce_customers"] == 1840 and out.params["ce_critical"] == round(hospital)
    assert out.params["ce_expected_impact"] == round(0.5 * (1840 + hospital))


def test_policy_tier_and_proposer_for_the_rule() -> None:
    payload = {
        "action": "propose",
        "subject": {"user_id": priority.PROPOSER},
        "proposal": {
            "action_type": "cross_domain_priority",
            "proposed_by": priority.PROPOSER,
            "requested_by": None,
            "initiator_kind": "system_rule",
            "target_ids": ["FDR-AIK-2207", "PS-17"],
        },
        "facts": {},
        "context": {"degraded_mode": "normal"},
    }
    decision = ReferencePolicy().propose(payload)
    assert decision.allow
    assert decision.classification.tier == "T3"
    assert sorted(decision.classification.required_functions) == ["command", "water_operations"]
