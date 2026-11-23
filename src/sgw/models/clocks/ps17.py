"""PS-17 chain (O-02): case specs from a per-member advisory table.

Input contract (one advisory): `issued_utc`, `next_advisory_utc`, and per ensemble member `exposure_utc`
(first time the member's P(PS-17 power loss) reaches the material threshold, or null), `drain_to_floor_min`
(zone tank drain from that time to the state floor), `crew_ts_onset_utc` (tropical-storm wind onset at the
staging yard) and `p_loss_final`; plus `generator_runtime_h`, `hospital_storage_h` and
`no_regret_member_p_loss` for the scenario. WP-11 (hazard ensemble, outage) and WP-13 (water continuity)
produce these fields; the WP-06 generator produces the same table for the synthetic Helene world.

Consequence bases: a table from the water twin carries its K16 bases under `water_twin`
(`drain_basis`: zone drain to the state floor at the critical service node; `generator_runtime_basis`), and
the clocks cite them. A table without them (the WP-06 station-sensor drain) keeps the WP-06 basis ids, so
a clock never cites the twin for numbers the twin did not produce.

Chain (prerequisite edges): fuel truck -> generator hookup -> pressure hold -> hospital supply; crews ->
generator hookup.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sgw.contracts.clocks import ClockBasis
from sgw.contracts.golden import HOSPITAL, PS17, ZONE
from sgw.contracts.vocab import ClockKind, DecisionStep, Domain
from sgw.models.clocks.service import CaseSpec
from sgw.models.clocks.waterfall import AddOnTerm, ConsequenceSpec

CASE_CREWS = "DC-D2-CREWS-AIK"
CASE_FUEL = "DC-D3-PS17-FUEL"
CASE_POWER = "DC-D3-PS17-POWER"
CASE_PRESSURE = "DC-D3-PS17-PRESSURE"
CASE_HOSPITAL = "DC-D3-HSP-TALLOWBRANCH-WATER"
CASE_PLACES: Mapping[str, tuple[str, ...]] = {
    CASE_FUEL: (PS17,),
    CASE_POWER: (PS17,),
    CASE_PRESSURE: (ZONE,),
    CASE_HOSPITAL: (HOSPITAL,),
}
REGION = "SC-45003"
BASIS_VERSION = "1.0-synthetic"
FLOOR_CITATION = "SC R.61-58.7.E(7) 25 psi floor"


def _basis(basis_id: str, citation: str | None = None) -> ClockBasis:
    return ClockBasis(
        kind=ClockKind.MODEL_ESTIMATE, basis_id=basis_id, basis_version=BASIS_VERSION, citation=citation
    )


@dataclass(frozen=True)
class WaterBases:
    drain: ClockBasis
    floor: ClockBasis
    fuel: ClockBasis
    from_twin: bool


def water_bases(scenario: Mapping[str, Any]) -> WaterBases:
    """The drain, floor and generator-runtime bases of a member table: the water twin's own K16 bases when
    the table carries them, else the WP-06 ids the numbers came from."""
    twin = scenario.get("water_twin") or {}
    if "drain_basis" in twin and "generator_runtime_basis" in twin:
        drain = ClockBasis.model_validate(twin["drain_basis"])
        rule_id = twin.get("floor_rule_id", "rule")
        cite = twin.get("floor_citation", drain.citation)
        floor = drain.model_copy(update={"citation": f"{rule_id}: {cite}"})
        return WaterBases(drain, floor, ClockBasis.model_validate(twin["generator_runtime_basis"]), True)
    return WaterBases(
        drain=_basis("water_twin.ps17_tank_drain"),
        floor=_basis("water_twin.ps17_pressure_floor", FLOOR_CITATION),
        fuel=_basis("water_twin.portable_generator_fuel"),
        from_twin=False,
    )


def _utc(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


def ps17_specs(advisory: Mapping[str, Any], scenario: Mapping[str, Any]) -> list[CaseSpec]:
    members = advisory["members"]
    exposure = [_utc(m["exposure_utc"]) for m in members]
    crews = [_utc(m["crew_ts_onset_utc"]) for m in members]
    drain = [m["drain_to_floor_min"] for m in members]
    needed = [m["p_loss_final"] >= scenario["no_regret_member_p_loss"] for m in members]
    next_adv = _utc(advisory["next_advisory_utc"])
    exposure_basis = _basis("outage.ps17_feeder_exposure")
    bases = water_bases(scenario)
    drain_term = AddOnTerm("zone tank drain to the state floor", bases.drain, drain)
    floor = bases.floor

    def exposed(basis: ClockBasis, *terms: AddOnTerm) -> ConsequenceSpec:
        return ConsequenceSpec(
            consequence_basis=basis,
            anchor_label="PS-17 feeder exposure (P(loss) reaches the material threshold)",
            anchor_basis=exposure_basis,
            anchor_utc=exposure,
            terms=terms,
        )

    runtime = AddOnTerm(
        "portable generator runtime on one tank",
        bases.fuel,
        60.0 * float(scenario["generator_runtime_h"]),
    )
    storage = AddOnTerm(
        "hospital onsite storage after the zone floor",
        _basis("water_twin.hospital_storage"),
        60.0 * float(scenario["hospital_storage_h"]),
    )
    return [
        CaseSpec(
            case_id=CASE_CREWS,
            step=DecisionStep.D2,
            title="Pre-position crews at Sandhill and Millpond yards",
            domain=Domain.ELECTRIC,
            region_id=REGION,
            consequence=ConsequenceSpec(
                consequence_basis=_basis("hazard.ts_wind_onset"),
                anchor_label="tropical-storm wind onset at Millpond yard",
                anchor_basis=_basis("hazard.ts_wind_onset"),
                anchor_utc=crews,
                min_member_share=0.5,
            ),
            lead_key="crew_mobilise_and_stage",
            if_late="Crews travel into tropical-storm winds or arrive after the first feeder trips.",
        ),
        CaseSpec(
            case_id=CASE_FUEL,
            step=DecisionStep.D3,
            title="Dispatch the fuel truck to PS-17",
            domain=Domain.WATER,
            region_id=REGION,
            consequence=exposed(bases.fuel, runtime),
            lead_key="fuel_truck_dispatch",
            if_late="The PS-17 portable generator runs dry before the fuel truck arrives.",
        ),
        CaseSpec(
            case_id=CASE_POWER,
            step=DecisionStep.D3,
            title="Hook up the portable generator at PS-17",
            domain=Domain.WATER,
            region_id=REGION,
            consequence=exposed(floor, drain_term),
            lead_key="portable_generator_hookup",
            if_late="Hospital zone pressure falls below the 25 psi floor before a generator runs at PS-17.",
            prerequisite_ids=(CASE_FUEL, CASE_CREWS),
            member_needed=needed,
            next_advisory_utc=next_adv,
        ),
        CaseSpec(
            case_id=CASE_PRESSURE,
            step=DecisionStep.D3,
            title="Hold Cedarfall zone pressure above the state floor",
            domain=Domain.WATER,
            region_id=REGION,
            consequence=exposed(floor, drain_term),
            lead_key="pump_restart_refill",
            if_late="The Cedarfall zone drops below the state floor; a boil-water decision follows.",
            prerequisite_ids=(CASE_POWER,),
        ),
        CaseSpec(
            case_id=CASE_HOSPITAL,
            step=DecisionStep.D3,
            title="Secure water supply to Tallowbranch hospital",
            domain=Domain.WATER,
            region_id=REGION,
            consequence=exposed(_basis("water_twin.hospital_storage"), drain_term, storage),
            lead_key="potable_water_tanker",
            if_late="Tallowbranch hospital exhausts onsite water storage without a tanker.",
            prerequisite_ids=(CASE_PRESSURE,),
        ),
    ]
