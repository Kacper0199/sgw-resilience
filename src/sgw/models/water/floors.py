"""State service-pressure floors and the SC pre-landfall precautionary advisory rule.

SC R.61-58.7.E(7): 25 psi at every service connection under normal operating conditions, 20 psi during
unusually heavy flows (fire, flushing). GA 391-3-5-.10: 20 psi at each service connection under all
conditions of flow. SC DES "Boil Water Notices and Advisories" (2024) lists "prior to a hurricane making
landfall" as a precautionary advisory trigger. Floors apply at the service connection, so the twin checks the
critical service node, not the pump-station sensor. Values come from numbers.yaml; the twin never hard-codes
a psi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sgw.common import numbers as numbers_mod
from sgw.contracts.clocks import ClockBasis
from sgw.contracts.vocab import ClockKind
from sgw.models.water.params import twin_params


class State(StrEnum):
    SC = "SC"
    GA = "GA"


class FlowCondition(StrEnum):
    NORMAL = "normal"
    HEAVY = "heavy_flow"


@dataclass(frozen=True)
class Floor:
    psi: float
    rule_id: str
    citation: str


def service_floor(state: State, condition: FlowCondition = FlowCondition.NORMAL) -> Floor:
    if state is State.SC and condition is FlowCondition.NORMAL:
        psi = float(numbers_mod.value("sc_pressure_floor_psi"))
        return Floor(
            psi, "rule.sc_service_pressure_normal", f"SC R.61-58.7.E(7) {psi:g} psi normal operation"
        )
    if state is State.SC:
        psi = float(numbers_mod.value("sc_pressure_floor_heavy_flow_psi"))
        return Floor(psi, "rule.sc_service_pressure_heavy_flow", f"SC R.61-58.7.E(7) {psi:g} psi heavy flow")
    psi = float(numbers_mod.value("ga_pressure_floor_psi"))
    return Floor(psi, "rule.ga_service_pressure", f"GA 391-3-5-.10 {psi:g} psi all flow conditions")


def floors_for(state: State) -> list[Floor]:
    """Every floor that applies in a state, binding (highest) first."""
    floors = {service_floor(state, c) for c in FlowCondition}
    return sorted(floors, key=lambda f: -f.psi)


@dataclass(frozen=True)
class PreLandfallAdvisory:
    zone_id: str
    due_utc: datetime
    breach_p: float
    basis: ClockBasis


def pre_landfall_advisory(
    *, zone_id: str, state: State, landfall_utc: datetime, breach_p: float, on_backup_or_exposed: bool
) -> PreLandfallAdvisory | None:
    """SC only: a precautionary boil-water advisory is due before landfall for a zone whose pumps are exposed
    or on backup power and whose floor-breach probability within the horizon reaches the policy threshold. A
    rule deadline (landfall), not a model estimate; issuing it stays a T3 human decision (WP-24 owns the
    rules engine)."""
    if state is not State.SC or not on_backup_or_exposed:
        return None
    if breach_p < twin_params().f("rule.pre_landfall_breach_p"):
        return None
    return PreLandfallAdvisory(
        zone_id=zone_id,
        due_utc=landfall_utc,
        breach_p=breach_p,
        basis=ClockBasis(
            kind=ClockKind.RULE_DEADLINE,
            basis_id="rule.sc_bwa_pre_landfall",
            basis_version=twin_params().version,
            citation="SC DES Boil Water Notices and Advisories (2024): precautionary advisory prior to a "
            "hurricane making landfall",
        ),
    )
