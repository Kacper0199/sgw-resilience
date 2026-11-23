"""Cross-domain priority rule `rule.ps17_pressure_floor` (D3, T3 `command` + `water_operations`).

When a water pump station that feeds a critical customer's service connection has its generator-hookup clock
on the critical path and the no-regret test says waiting for the next advisory does not fit (`act_now` or
`decide_now`), the rule proposes priority for the station's feeder restoration and its portable generator.
The proposer is the rule (`system:rule:ps17_pressure_floor`, K8), never a person; the approvers decide. The
card carries the CE breakdown of the feeder with the hospital counted through its water supply.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sgw.contracts.vocab import NoRegretVerdict
from sgw.models.ranking.ce import ImpactBreakdown, ImpactInput, RankPolicy, expected_impact

RULE_ID = "rule.ps17_pressure_floor"
PROPOSER = "system:rule:ps17_pressure_floor"
FIRES_ON = frozenset({NoRegretVerdict.ACT_NOW, NoRegretVerdict.DECIDE_NOW})


@dataclass(frozen=True)
class StationLink:
    station_id: str
    feeder_id: str
    feeder_customers: int
    zone_id: str
    critical_customer_id: str
    critical_kind: str
    generator_id: str


@dataclass(frozen=True)
class PriorityOutcome:
    fires: bool
    reason: str
    target_ids: tuple[str, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)
    breakdown: ImpactBreakdown | None = None


def ps17_link(network: Mapping[str, Any]) -> StationLink:
    """PS-17's feeder, zone, hospital and portable generator from the named assets of the Helene world."""
    named = network["named"]
    station = named["pump_stations"]["PS-17"]
    hospital = named["hospital"]
    if hospital["zone"] != station["zone"]:
        raise ValueError("the hospital is not in PS-17's zone")
    return StationLink(
        station_id="PS-17",
        feeder_id=str(station["feeder"]),
        feeder_customers=int(named["feeders"][station["feeder"]]["customers"]),
        zone_id=str(station["zone"]),
        critical_customer_id=str(hospital["id"]),
        critical_kind="hospital",
        generator_id=str(named["portable_generator"]["id"]),
    )


def evaluate(
    link: StationLink,
    *,
    verdict: NoRegretVerdict,
    on_critical_path: bool,
    p_loss: float,
    case_id: str,
    policy: RankPolicy | None = None,
) -> PriorityOutcome:
    if not on_critical_path:
        return PriorityOutcome(False, "generator hookup is not on the critical path")
    if verdict not in FIRES_ON:
        return PriorityOutcome(
            False, f"no-regret verdict {verdict.value}: waiting for the next advisory fits"
        )
    breakdown = expected_impact(
        ImpactInput(
            entity_id=link.feeder_id,
            p_loss=p_loss,
            customers=link.feeder_customers,
            critical_facilities=(link.critical_kind,),
        ),
        policy or RankPolicy.default(),
    )
    return PriorityOutcome(
        fires=True,
        reason=f"no-regret verdict {verdict.value} on the critical path; "
        f"{link.critical_customer_id} depends on {link.station_id} for water",
        target_ids=(link.feeder_id, link.station_id),
        params={
            "rule_id": RULE_ID,
            "decision_case_id": case_id,
            "priority": ["feeder_restoration", "portable_generator"],
            "station_id": link.station_id,
            "zone_id": link.zone_id,
            "critical_customer_id": link.critical_customer_id,
            "generator_id": link.generator_id,
            "verdict": verdict.value,
            "ce_customers": round(breakdown.customers_ce),
            "ce_critical": round(breakdown.critical_ce),
            "ce_expected_impact": breakdown.expected_impact_ce,
        },
        breakdown=breakdown,
    )
