"""A1 wind-profile check against observed station gusts (ai-capabilities A1 acceptance).

This is a check of the wind profile, gust factor and ensemble spread width, not of forecast skill: the WP-06
members are perturbations around the true (best-track) storm, so the track error is synthetic. Question asked:
does the member spread of an advisory contain the observed Helene peak gust at the footprint ASOS stations?

Observed: IEM ASOS archive (public METAR), max of the 5-s `gust` and `peak_wind_gust` fields, 2024-09-25..29.
The model gust is a 3-s gust (WMO in-land factor), so a small high bias is expected. VLD stopped reporting at
03:45Z as the eyewall approached, so its value is a lower bound and it is excluded from the count (censored).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from sgw.generator.forecast import member_tracks
from sgw.models.hazard.ensemble import scenario_hazard
from sgw.models.hazard.field import Points, point_features, splice
from sgw.models.hazard.hurdat2 import OPEN_DIR

STATIONS_CSV = OPEN_DIR / "asos_helene_peak_gust.csv"


def station_check(label: str, scenario: str = "helene") -> dict[str, Any]:
    st = pd.read_csv(STATIONS_CSV)
    hz = scenario_hazard(scenario)
    adv = hz.advisory(label)
    pts = Points(tuple(st["station"]), st["lat"].to_numpy(), st["lon"].to_numpy())
    _, members, _ = member_tracks(hz.analysis, adv, hz.scenario, hz.family, hz.seed)
    gust = np.stack(
        [point_features(splice(hz.analysis, m), pts, hz.family)["peak_gust_ms"].to_numpy() for m in members]
    )
    analysis = point_features(hz.analysis, pts, hz.family)["peak_gust_ms"].to_numpy()
    rows = []
    for j, r in enumerate(st.itertuples()):
        censored = "censored" in str(r.field)
        lo, hi = float(gust[:, j].min()), float(gust[:, j].max())
        rows.append(
            {
                "station": r.station,
                "observed_ms": float(r.peak_gust_ms),
                "censored": censored,
                "member_min_ms": round(lo, 1),
                "member_p50_ms": round(float(np.median(gust[:, j])), 1),
                "member_max_ms": round(hi, 1),
                "best_track_model_ms": round(float(analysis[j]), 1),
                "inside_spread": lo <= float(r.peak_gust_ms) <= hi,
            }
        )
    scored = [r for r in rows if not r["censored"]]
    return {
        "advisory": label,
        "members": len(members),
        "stations_scored": len(scored),
        "inside_spread": sum(r["inside_spread"] for r in scored),
        "stations": rows,
    }
