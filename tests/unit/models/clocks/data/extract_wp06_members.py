"""Re-extract the PS-17 per-member clock table from the WP-06 generator (sgw.generator must be importable).

    uv run python tests/unit/models/clocks/data/extract_wp06_members.py > \
        tests/unit/models/clocks/data/wp06_helene_ps17_members.json
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np

from sgw.generator.config import load_family, load_scenario
from sgw.generator.ensemble import run_ensembles
from sgw.generator.scenario import run_truth
from sgw.generator.water import burn_gph, minutes_to_floor

SOURCE = "WP-06 generator 1.0.0 (branch w1/wp-06-generator 59befc7), seed 61017, family A"
LEAD_KEYS = (
    "clocks.crews_lead_min",
    "fuel.truck_lead_min",
    "generator.hookup_lead_min",
    "clocks.pressure_restart_lead_min",
    "clocks.hospital_tanker_lead_min",
)


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    sc = load_scenario("helene")
    fam = load_family(sc["family"])
    truth = run_truth(sc, fam)
    pts, ens = run_ensembles(truth)
    p_star = fam.f("clocks.material_loss_p")
    yard = pts.ids.index("STG-RCH-MILLPOND-YARD")
    out: dict[str, Any] = {
        "source": SOURCE,
        "label": "synthetic",
        "material_loss_p": p_star,
        "no_regret_member_p_loss": fam.f("clocks.no_regret_member_p_loss"),
        "lead_min": {k: int(fam[k]) for k in LEAD_KEYS},
        "hospital_storage_h": fam.f("clocks.hospital_storage_h"),
        "generator_runtime_h": fam.f("generator.portable_tank_gal") / burn_gph(500.0, fam),
        "advisories": {},
    }
    for e in ens:
        if e.advisory.label not in ("N", "N+1"):
            continue
        members = []
        for m in e.members:
            reached = m.p_loss_path >= p_star
            t_exp = float(e.times[np.argmax(reached)]) if reached.any() else None
            onset = m.onset_t[yard]
            members.append(
                {
                    "exposure_utc": iso(t_exp) if t_exp is not None else None,
                    "drain_to_floor_min": round(minutes_to_floor(t_exp, fam), 1)
                    if t_exp is not None
                    else None,
                    "crew_ts_onset_utc": None if np.isnan(onset) else iso(float(onset)),
                    "p_loss_final": round(float(m.p_loss_path[-1]), 6),
                }
            )
        out["advisories"][e.advisory.label] = {
            "issued_utc": iso(e.advisory.issued.timestamp()),
            "next_advisory_utc": iso(e.advisory.next_issued.timestamp()),
            "members": members,
        }
    json.dump(out, sys.stdout, indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
