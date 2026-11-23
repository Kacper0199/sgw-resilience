"""Modelled gust time series per point, from the same Holland-profile code as `point_features`.

`field.py` stays untouched (A1 parity tests); this module only exposes the series it reduces, for
- the calibrated duration feature `hours_gust_cal_ge_20` (factor x gust >= 20 m/s), and
- the hazard-conditioned label window L2 (first and last time the modelled gust reaches 13 m/s).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sgw.generator.config import Family, load_family
from sgw.generator.truth import wind_kwargs
from sgw.generator.wind import Track, distance_km, sustained_wind
from sgw.models.hazard.field import GUST_BAND_MS, STEP_S, Points, time_grid

L2_GUST_MS = 13.0


@dataclass(frozen=True)
class GustSeries:
    times: np.ndarray
    gust: np.ndarray
    t_close: np.ndarray

    def hours_above(self, threshold_ms: float = GUST_BAND_MS, factor: np.ndarray | float = 1.0) -> np.ndarray:
        scaled = self.gust * np.broadcast_to(np.asarray(factor, dtype=float), self.gust.shape[1:])[None, :]
        return (scaled >= threshold_ms).sum(axis=0) * (STEP_S / 3600.0)

    def windows(
        self, threshold_ms: float = L2_GUST_MS, lead_h: float = 6.0, tail_h: float = 48.0
    ) -> tuple[np.ndarray, np.ndarray]:
        """Per point (start, end), epoch s: first reach - lead to last reach + tail, else closest approach."""
        above = self.gust >= threshold_ms
        any_above = above.any(axis=0)
        first = np.where(any_above, self.times[np.argmax(above, axis=0)], self.t_close)
        last_idx = len(self.times) - 1 - np.argmax(above[::-1], axis=0)
        last = np.where(any_above, self.times[last_idx], self.t_close)
        return first - lead_h * 3600.0, last + tail_h * 3600.0


def gust_series(track: Track, points: Points, fam: Family | None = None) -> GustSeries:
    fam = fam or load_family("A")
    times = time_grid(track)
    v = sustained_wind(track, times, points.lat, points.lon, **wind_kwargs(fam))
    state = track.at(times)
    dist = distance_km(state["lat"][:, None], state["lon"][:, None], points.lat[None, :], points.lon[None, :])
    dist = np.where((state["vmax"] > 0.0)[:, None], dist, np.inf)
    return GustSeries(times=times, gust=fam.f("wind.gust_factor") * v, t_close=times[np.argmin(dist, axis=0)])
