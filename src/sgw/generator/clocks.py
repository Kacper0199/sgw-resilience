"""Reference decision clocks per advisory (expected signatures for WP-12; WP-12 owns the production clocks).

PS-17 chain, seeded as prerequisite edges (critical path):

    DC-D3-PS17-FUEL (fuel truck) -> DC-D3-PS17-POWER (generator hookup) -> DC-D3-PS17-PRESSURE (pressure hold)
    -> DC-D3-HSP-TALLOWBRANCH-WATER (hospital supply);   DC-D2-CREWS-AIK (crews staged) -> DC-D3-PS17-POWER.

Consequence of losing PS-17 power: the time PS-17 becomes exposed plus the drain time of the full zone tank
to the state floor. Exposure per member is the first time its loss probability P_m(t) reaches
`material_loss_p`; P10/P50/P90 are taken over the members that reach it (stronger or earlier wind at the
PS-17 feeder gives an earlier exposure, which is the causal chain of the hinge). Conditional loss-time
quantiles were rejected: given a loss, it happens mostly in the fast and strong members, so a weaker
forecast moved the clock earlier. Every clock is consequence minus lead time (O-03) via
`sgw.contracts.clocks.build_clock`; propagation uses `sgw.contracts.clocks.propagate`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from sgw.common import numbers as numbers_mod
from sgw.contracts.base import ppm_from_fraction, utc_iso
from sgw.contracts.clocks import (
    ClockBasis,
    ClockNode,
    DecisionCase,
    DecisionClock,
    build_clock,
    no_regret_verdict,
    propagate,
)
from sgw.contracts.vocab import ClockKind, DecisionStep, Domain
from sgw.generator.config import Family
from sgw.generator.ensemble import AdvisoryEnsemble, PointSet
from sgw.generator.water import burn_gph, minutes_to_floor

CASE_CREWS = "DC-D2-CREWS-AIK"
CASE_FUEL = "DC-D3-PS17-FUEL"
CASE_POWER = "DC-D3-PS17-POWER"
CASE_PRESSURE = "DC-D3-PS17-PRESSURE"
CASE_HOSPITAL = "DC-D3-HSP-TALLOWBRANCH-WATER"
PREREQUISITES: dict[str, tuple[str, ...]] = {
    CASE_CREWS: (),
    CASE_FUEL: (),
    CASE_POWER: (CASE_FUEL, CASE_CREWS),
    CASE_PRESSURE: (CASE_POWER,),
    CASE_HOSPITAL: (CASE_PRESSURE,),
}
BASIS_VERSION = "1.0-synthetic"


def _basis(basis_id: str, citation: str | None = None) -> ClockBasis:
    return ClockBasis(
        kind=ClockKind.MODEL_ESTIMATE, basis_id=basis_id, basis_version=BASIS_VERSION, citation=citation
    )


def _minute(t: float) -> datetime:
    return datetime.fromtimestamp(round(t / 60.0) * 60.0, tz=UTC)


def loss_quantiles(ens: AdvisoryEnsemble, p_star: float) -> tuple[float, list[float] | None]:
    """(P(loss) averaged over members, [t10, t50, t90] of the member exposure times or None). A member's
    exposure time is the first time its loss probability reaches `p_star`; members that never reach it do not
    vote; fewer than a third of the members reaching it means no clock."""
    paths = np.stack([m.p_loss_path for m in ens.members])
    p_loss = float(paths[:, -1].mean())
    reached = paths >= p_star
    hit = reached.any(axis=1)
    if hit.sum() < len(ens.members) / 3:
        return p_loss, None
    onset = ens.times[np.argmax(reached[hit], axis=1)]
    return p_loss, [float(np.percentile(onset, q)) for q in (10, 50, 90)]


def onset_quantiles(ens: AdvisoryEnsemble, col: int) -> list[float] | None:
    onsets = np.array([m.onset_t[col] for m in ens.members])
    onsets = onsets[~np.isnan(onsets)]
    if len(onsets) < len(ens.members) / 2:
        return None
    return [float(np.percentile(onsets, q)) for q in (10, 50, 90)]


def _ordered(values: list[float]) -> list[float]:
    return list(np.maximum.accumulate(np.asarray(values)))


def advisory_clocks(
    ens: AdvisoryEnsemble,
    pts: PointSet,
    fam: Family,
    region_id: str = "SC-45003",
    yard: str = "STG-RCH-MILLPOND-YARD",
) -> dict[str, Any] | None:
    p_loss, loss_q = loss_quantiles(ens, fam.f("clocks.material_loss_p"))
    crew_q = onset_quantiles(ens, pts.ids.index(yard))
    if loss_q is None or crew_q is None:
        return None
    member_threshold = fam.f("clocks.no_regret_member_p_loss")
    share = float(np.mean([m.p_loss_path[-1] >= member_threshold for m in ens.members]))
    floor_q = _ordered([t + minutes_to_floor(t, fam) * 60.0 for t in loss_q])
    gen_runtime_h = fam.f("generator.portable_tank_gal") / burn_gph(500.0, fam)
    fuel_q = [t + gen_runtime_h * 3600.0 for t in loss_q]
    hosp_q = [t + fam.f("clocks.hospital_storage_h") * 3600.0 for t in floor_q]
    floor_psi = f"{fam.f('water.floor_psi'):g}"
    floor_cite = f"SC R.61-58.7.E(7) {floor_psi} psi floor"
    specs: dict[str, tuple[list[float], int, ClockBasis, ClockBasis, str]] = {
        CASE_CREWS: (
            crew_q,
            int(fam["clocks.crews_lead_min"]),
            _basis("hazard.ts_wind_onset"),
            _basis("lead_time.crew_mobilise_and_stage", "SOP-ELE-2.1"),
            "Crews travel into tropical-storm winds or arrive after the first feeder trips.",
        ),
        CASE_FUEL: (
            fuel_q,
            int(fam["fuel.truck_lead_min"]),
            _basis("water_twin.portable_generator_fuel"),
            _basis("lead_time.fuel_truck_dispatch", "SOP-WTR-4.4"),
            "The PS-17 portable generator runs dry before the fuel truck arrives.",
        ),
        CASE_POWER: (
            floor_q,
            int(fam["generator.hookup_lead_min"]),
            _basis("water_twin.ps17_pressure_floor", floor_cite),
            _basis("lead_time.portable_generator_hookup", "SOP-WTR-4.2"),
            f"Hospital zone pressure falls below the {floor_psi} psi floor before a generator runs at PS-17.",
        ),
        CASE_PRESSURE: (
            floor_q,
            int(fam["clocks.pressure_restart_lead_min"]),
            _basis("water_twin.ps17_pressure_floor", floor_cite),
            _basis("lead_time.pump_restart_refill", "SOP-WTR-4.2"),
            "The Cedarfall zone drops below the state floor; a boil-water decision follows.",
        ),
        CASE_HOSPITAL: (
            hosp_q,
            int(fam["clocks.hospital_tanker_lead_min"]),
            _basis("water_twin.hospital_storage"),
            _basis("lead_time.potable_water_tanker", "SOP-WTR-6.1"),
            "Tallowbranch hospital exhausts onsite water storage without a tanker.",
        ),
    }
    clocks: dict[str, DecisionClock] = {}
    for cid, (q, lead, cons, lead_basis, if_late) in specs.items():
        q = _ordered(q)
        clocks[cid] = build_clock(
            consequence_p10_utc=_minute(q[0]),
            consequence_utc=_minute(q[1]),
            consequence_p90_utc=_minute(q[2]),
            consequence_basis=cons,
            action_lead_time_min=lead,
            lead_time_basis=lead_basis,
            if_late=if_late,
        )
    nodes = [
        ClockNode(
            case_id=cid,
            decide_by_utc=c.decide_by_utc,
            action_lead_time_min=c.action_lead_time_min,
            prerequisite_ids=PREREQUISITES[cid],
        )
        for cid, c in clocks.items()
    ]
    prop = propagate(nodes)
    threshold = int(numbers_mod.value("policy_no_regret_act_now_ppm"))
    next_adv = ens.advisory.next_issued
    cases = {}
    for cid, c in clocks.items():
        is_power = cid == CASE_POWER
        share_ppm = ppm_from_fraction(share) if is_power else None
        verdict = no_regret_verdict(
            share_ppm=share_ppm,
            effective_decide_by_utc=prop[cid].effective_decide_by_utc,
            next_advisory_utc=next_adv if is_power else None,
            act_now_threshold_ppm=threshold,
        )
        cases[cid] = DecisionCase(
            decision_case_id=cid,
            step=DecisionStep.D2 if cid == CASE_CREWS else DecisionStep.D3,
            title=TITLES[cid],
            domain=Domain.ELECTRIC if cid == CASE_CREWS else Domain.WATER,
            region_id=region_id,
            clock=c,
            prerequisite_ids=list(PREREQUISITES[cid]),
            effective_decide_by_utc=prop[cid].effective_decide_by_utc,
            on_critical_path=prop[cid].on_critical_path,
            no_regret_share_ppm=share_ppm,
            no_regret_verdict=verdict,
            next_advisory_utc=next_adv if is_power else None,
        )
    return {
        "advisory_label": ens.advisory.label,
        "issued_utc": utc_iso(ens.advisory.issued),
        "ps17_p_loss_ppm": ppm_from_fraction(min(max(p_loss, 0.0), 1.0)),
        "ps17_loss_p10_p50_p90_utc": [utc_iso(_minute(t)) for t in loss_q],
        "cases": {cid: case.model_dump(mode="json") for cid, case in cases.items()},
        "bound_by": {cid: prop[cid].bound_by_case_id for cid in clocks},
    }


TITLES = {
    CASE_CREWS: "Pre-position crews at Sandhill and Millpond yards",
    CASE_FUEL: "Dispatch the fuel truck to PS-17",
    CASE_POWER: "Hook up the portable generator at PS-17",
    CASE_PRESSURE: "Hold Cedarfall zone pressure above the state floor",
    CASE_HOSPITAL: "Secure water supply to Tallowbranch hospital",
}


def shift_minutes(
    a: dict[str, Any], b: dict[str, Any], case: str = CASE_POWER, effective: bool = False
) -> float:
    def t(x: dict[str, Any]) -> datetime:
        c = x["cases"][case]
        value = c["effective_decide_by_utc"] if effective else c["clock"]["decide_by_utc"]
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    return (t(b) - t(a)) / timedelta(minutes=1)
