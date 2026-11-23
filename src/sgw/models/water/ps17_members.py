"""PS-17 per-member clock table for WP-12 (`sgw.models.clocks.ps17` input contract), water terms from the
twin.

Per advisory and ensemble member: `exposure_utc`, `crew_ts_onset_utc` and `p_loss_final` come from the hazard
ensemble (WP-06 generator today; WP-11 replaces it); `drain_to_floor_min` comes from the zone twin: the tank
level observed at the advisory issue time (SCADA, known by then), the member's exposure clock time (diurnal
demand), a demand multiplier per member (leak x scale, Latin-hypercube strata with common random numbers
across advisories, so the N -> N+1 shift reflects the forecast only) and the SC floor at the critical service
node (the hospital node for the Cedarfall zone). `generator_runtime_h` comes from the fuel ODE of the
portable unit. The WP-06 reference drain (floor at the station sensor, fixed leak 1.3, full tank) is kept per
member as
`drain_reference_wp06_min` so the change of basis is visible.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from sgw.generator.config import rng
from sgw.models.water.basis import drain_basis, generator_runtime_basis
from sgw.models.water.floors import State, service_floor
from sgw.models.water.params import ARTEFACT_DIR, family, scenario, twin_params
from sgw.models.water.survival import burn_gph, demand_multipliers
from sgw.models.water.telemetry import epoch, load_water_series
from sgw.models.water.twin import zone_twins

LEAD_KEYS = (
    "clocks.crews_lead_min",
    "fuel.truck_lead_min",
    "generator.hookup_lead_min",
    "clocks.pressure_restart_lead_min",
    "clocks.hospital_tanker_lead_min",
)
STATION = "PS-17"
YARD = "STG-RCH-MILLPOND-YARD"
OUT_PATH = ARTEFACT_DIR / "ps17_clock_members.json"


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def hazard_members(labels: tuple[str, ...] = ("N", "N+1")) -> dict[str, dict[str, Any]]:
    """Exposure, crew onset and final loss probability per member from the WP-06 ensemble (deterministic)."""
    from sgw.generator.ensemble import run_ensembles
    from sgw.generator.truth import run_truth

    sc = scenario()
    fam = family(sc["family"])
    truth = run_truth(sc, fam)
    pts, ens = run_ensembles(truth, labels=labels)
    p_star = fam.f("clocks.material_loss_p")
    yard = pts.ids.index(YARD)
    out: dict[str, dict[str, Any]] = {}
    for e in ens:
        members = []
        for m in e.members:
            reached = m.p_loss_path >= p_star
            t_exp = float(e.times[np.argmax(reached)]) if reached.any() else None
            onset = m.onset_t[yard]
            members.append(
                {
                    "exposure_utc": iso(t_exp) if t_exp is not None else None,
                    "crew_ts_onset_utc": None if np.isnan(onset) else iso(float(onset)),
                    "p_loss_final": round(float(m.p_loss_path[-1]), 6),
                }
            )
        out[e.advisory.label] = {
            "issued_utc": iso(e.advisory.issued.timestamp()),
            "next_advisory_utc": iso(e.advisory.next_issued.timestamp()) if e.advisory.next_issued else None,
            "members": members,
        }
    return out


def wntr_critical_counts(station: str, floor: float = 25.0) -> dict[str, int]:
    path = ARTEFACT_DIR / "wntr_drain_grid.json"
    if not path.is_file():
        return {}
    counts: dict[str, int] = {}
    for r in json.loads(path.read_text(encoding="utf-8"))["rows"]:
        node = r.get(f"critical_node_{floor:g}")
        if r["station"] == station and node:
            counts[node] = counts.get(node, 0) + 1
    return counts


def water_terms(
    advisories: dict[str, dict[str, Any]], fixture: str = "helene"
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    from sgw.generator.water import minutes_to_floor

    fam = family()
    tp = twin_params()
    twin = zone_twins()[STATION]
    floor = service_floor(State.SC)
    tank_id = scenario()["named"]["pump_stations"][STATION]["tank"]
    level = load_water_series(fixture).get(f"LT-{tank_id}:level")
    n = max(len(a["members"]) for a in advisories.values())
    mult = demand_multipliers(tp, rng(int(tp["mc.seed"]), "ps17_member_demand"), n, stratified=True)
    out: dict[str, dict[str, Any]] = {}
    for label, adv in advisories.items():
        observed = level.at_or_before(epoch(adv["issued_utc"])) if level else None
        level0 = twin.pm.max_level_ft if observed is None else min(observed, twin.pm.max_level_ft)
        members = []
        for i, m in enumerate(adv["members"]):
            row = dict(m)
            if m["exposure_utc"] is None:
                row.update(
                    drain_to_floor_min=None,
                    drain_reference_wp06_min=None,
                    demand_multiplier=None,
                    critical_node=None,
                )
            else:
                t_exp = epoch(m["exposure_utc"])
                nodes: list[np.ndarray] = []
                d = float(
                    twin.drain_to_floor_min(t_exp, mult[i], floor.psi, level0_ft=level0, nodes_out=nodes)
                )
                row.update(
                    critical_node=twin.pm.node_ids[int(nodes[0])] if int(nodes[0]) >= 0 else None,
                    drain_to_floor_min=round(d, 1),
                    drain_reference_wp06_min=round(minutes_to_floor(t_exp, fam), 1),
                    demand_multiplier=round(float(mult[i]), 4),
                )
            members.append(row)
        out[label] = {**adv, "tank_level0_ft": round(level0, 2), "members": members}
    counts: dict[str, int] = {}
    for adv in out.values():
        for m in adv["members"]:
            if m["critical_node"]:
                counts[m["critical_node"]] = counts.get(m["critical_node"], 0) + 1
    meta = {
        "floor_psi": floor.psi,
        "floor_rule_id": floor.rule_id,
        "floor_citation": floor.citation,
        "critical_node_counts_members": counts,
        "critical_node_counts_wntr": wntr_critical_counts(STATION),
        "drain_basis": drain_basis().model_dump(mode="json"),
        "generator_runtime_basis": generator_runtime_basis().model_dump(mode="json"),
    }
    return out, meta


def build_member_table(fixture: str = "helene") -> dict[str, Any]:
    fam = family()
    advisories, meta = water_terms(hazard_members(), fixture)
    kw = float(scenario()["named"]["portable_generator"]["kw"])
    return {
        "source": "WP-13 water twin over the WP-06 hazard ensemble (seed 61017, family A)",
        "label": "synthetic",
        "material_loss_p": fam.f("clocks.material_loss_p"),
        "no_regret_member_p_loss": fam.f("clocks.no_regret_member_p_loss"),
        "lead_min": {k: int(fam[k]) for k in LEAD_KEYS},
        "hospital_storage_h": fam.f("clocks.hospital_storage_h"),
        "generator_runtime_h": fam.f("generator.portable_tank_gal") / burn_gph(kw, fam),
        "water_twin": meta,
        "advisories": advisories,
    }


def write_member_table(path: Path = OUT_PATH, fixture: str = "helene") -> dict[str, Any]:
    table = build_member_table(fixture)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return table
