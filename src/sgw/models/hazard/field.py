"""A1 hazard field: per-point wind features from one storm track, shared by training and serving.

`point_features` is the only place the outage model's hazard features are computed. The backtest calls it on
HURDAT2 best tracks of real storms; the risk publisher calls it on the forecast members of a synthetic
advisory. One function on both paths is the guard against train-serving skew. Wind comes from the WP-06
Holland-2010 profile (`sgw.generator.wind.sustained_wind`) with the family-A wind parameters.

Features (per point):
- `peak_gust_ms`: maximum 3-s gust (gust factor x 1-min sustained wind).
- `hours_gust_ge_20`: hours with gust >= 20 m/s (tree-fall onset band, assumption).
- `hours_ts`: hours with sustained wind >= 34 kt.
- `min_dist_km`: closest approach of the storm centre while the storm is active.
- `speed_kmh_closest`: storm translation speed at the closest approach (slow storms rain longer).
- `vmax_ms_closest`: storm intensity at the closest approach.
- `hours_centre_within_200km` (WP-11v2 candidate, not in `HAZARD_FEATURES`): hours the active storm centre
  spends within `RAIN_RADIUS_KM` of the point, a track-only proxy for rain totals (slow, close storms rain
  longer).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from sgw.generator.config import Family, load_family
from sgw.generator.truth import wind_kwargs
from sgw.generator.wind import TS_MS, Track, distance_km, sustained_wind

STEP_S = 900.0
GUST_BAND_MS = 20.0
RAIN_RADIUS_KM = 200.0
HAZARD_FEATURES = (
    "peak_gust_ms",
    "hours_gust_ge_20",
    "hours_ts",
    "min_dist_km",
    "speed_kmh_closest",
    "vmax_ms_closest",
)
EXTRA_FEATURES = ("hours_centre_within_200km",)


@dataclass(frozen=True)
class Points:
    ids: tuple[str, ...]
    lat: np.ndarray
    lon: np.ndarray


def time_grid(track: Track, start: float | None = None, end: float | None = None) -> np.ndarray:
    lo = track.t[0] if start is None else max(start, track.t[0])
    hi = track.t[-1] if end is None else min(end, track.t[-1])
    return np.arange(lo, hi + 1.0, STEP_S)


def point_features(
    track: Track, points: Points, fam: Family | None = None, times: np.ndarray | None = None
) -> pd.DataFrame:
    fam = fam or load_family("A")
    times = time_grid(track) if times is None else times
    v = sustained_wind(track, times, points.lat, points.lon, **wind_kwargs(fam))
    gust = fam.f("wind.gust_factor") * v
    step_h = STEP_S / 3600.0
    state = track.at(times)
    active = state["vmax"] > 0.0
    dist = distance_km(state["lat"][:, None], state["lon"][:, None], points.lat[None, :], points.lon[None, :])
    dist = np.where(active[:, None], dist, np.inf)
    i_close = np.argmin(dist, axis=0)
    heading_a = track.at(times - 1800.0)
    heading_b = track.at(times + 1800.0)
    speed = distance_km(heading_a["lat"], heading_a["lon"], heading_b["lat"], heading_b["lon"])
    frame = pd.DataFrame(
        {
            "point_id": list(points.ids),
            "peak_gust_ms": gust.max(axis=0),
            "hours_gust_ge_20": (gust >= GUST_BAND_MS).sum(axis=0) * step_h,
            "hours_ts": (v >= TS_MS).sum(axis=0) * step_h,
            "min_dist_km": np.minimum(dist.min(axis=0), 3000.0),
            "speed_kmh_closest": speed[i_close],
            "vmax_ms_closest": state["vmax"][i_close],
            "hours_centre_within_200km": (dist <= RAIN_RADIUS_KM).sum(axis=0) * step_h,
        }
    )
    return frame.round(4)


def splice(analysis: Track, forecast: Track) -> Track:
    """Analysis fixes before the forecast's first time, then the forecast: what an operator knows at issue."""
    keep = analysis.t < forecast.t[0]
    return Track(
        t=np.concatenate([analysis.t[keep], forecast.t]),
        lat=np.concatenate([analysis.lat[keep], forecast.lat]),
        lon=np.concatenate([analysis.lon[keep], forecast.lon]),
        vmax=np.concatenate([analysis.vmax[keep], forecast.vmax]),
        rmw=np.concatenate([analysis.rmw[keep], forecast.rmw]),
        r34=np.concatenate([analysis.r34[keep], forecast.r34]),
    )
