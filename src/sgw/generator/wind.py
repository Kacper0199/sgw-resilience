"""Parametric tropical-cyclone wind field.

Profile: Holland, Belanger and Fritz (2010) shape on the Holland (1980) pressure profile,

    V(r) = Vm * s(r)^x,   s(r) = (Rm/r)^B * exp(1 - (Rm/r)^B),

with x = 0.5 inside the radius of maximum wind and, outside it, x fitted per track fix and quadrant so that
V = 34 kt (clipped to [0.3, 2.5] so that a storm just above 34 kt does not get a flat
profile), and tapered linearly to zero between `taper_start` and `taper_end` times R34 (the vortex does
not reach across the basin). R34 is the HURDAT2 34-kt radius (a maximum extent) scaled to a mean extent and
interpolated by azimuth between the quadrant centres.
Vm is the HURDAT2 1-min sustained wind at 10 m, so the profile already includes the storm motion and the
quadrant radii carry its asymmetry. The 3-s gust is `gust_factor * V` (WMO in-land), times a per-site
lognormal exposure multiplier. Units: SI (m/s, km, s since epoch); positions in WGS84 degrees.
Domain of validity: distances up to about 1,500 km (equirectangular local geometry), fixes 3 to 6 h apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

KT = 0.514444
NMI_KM = 1.852
KM_PER_DEG_LAT = 110.57
KM_PER_DEG_LON_EQ = 111.32
TS_KT = 34.0
TS_MS = TS_KT * KT
OUTER_EXPONENT_MIN = 0.3
OUTER_EXPONENT_MAX = 2.5
OUTER_TAPER_START = 2.0
OUTER_TAPER_END = 3.0


def epoch(t: datetime) -> float:
    return t.timestamp()


@dataclass(frozen=True)
class Track:
    """Storm states at fix times. `r34` columns: NE, SE, SW, NW in km (0 = no 34-kt wind in that quadrant)."""

    t: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    vmax: np.ndarray
    rmw: np.ndarray
    r34: np.ndarray

    @classmethod
    def from_rows(cls, rows: list[list[Any]], parse: Any) -> Track:
        t = np.array([epoch(parse(r[0])) for r in rows])
        return cls(
            t=t,
            lat=np.array([float(r[1]) for r in rows]),
            lon=np.array([float(r[2]) for r in rows]),
            vmax=np.array([float(r[3]) * KT for r in rows]),
            rmw=np.array([float(r[5]) * NMI_KM for r in rows]),
            r34=np.array([[float(v) * NMI_KM for v in r[6:10]] for r in rows]),
        )

    def at(self, times: np.ndarray) -> dict[str, np.ndarray]:
        times = np.asarray(times, dtype=float)
        active = (times >= self.t[0]) & (times <= self.t[-1])
        out = {
            "lat": np.interp(times, self.t, self.lat),
            "lon": np.interp(times, self.t, self.lon),
            "vmax": np.where(active, np.interp(times, self.t, self.vmax), 0.0),
            "rmw": np.interp(times, self.t, self.rmw),
            "r34": np.stack([np.interp(times, self.t, self.r34[:, q]) for q in range(4)], axis=1),
        }
        return out

    def heading_rad(self, times: np.ndarray, dt_s: float = 1800.0) -> np.ndarray:
        a = self.at(np.asarray(times) - dt_s)
        b = self.at(np.asarray(times) + dt_s)
        dx, dy = offsets_km(a["lat"], a["lon"], b["lat"], b["lon"])
        return np.arctan2(dx, dy)


def offsets_km(lat0: Any, lon0: Any, lat1: Any, lon1: Any) -> tuple[np.ndarray, np.ndarray]:
    lat0, lon0, lat1, lon1 = (np.asarray(v, dtype=float) for v in (lat0, lon0, lat1, lon1))
    mid = np.radians((lat0 + lat1) / 2.0)
    dx = (lon1 - lon0) * KM_PER_DEG_LON_EQ * np.cos(mid)
    dy = (lat1 - lat0) * KM_PER_DEG_LAT
    return dx, dy


def distance_km(lat0: Any, lon0: Any, lat1: Any, lon1: Any) -> np.ndarray:
    dx, dy = offsets_km(lat0, lon0, lat1, lon1)
    return np.hypot(dx, dy)


def displace(lat: np.ndarray, lon: np.ndarray, dx_km: np.ndarray, dy_km: np.ndarray) -> tuple[Any, Any]:
    new_lat = lat + dy_km / KM_PER_DEG_LAT
    new_lon = lon + dx_km / (KM_PER_DEG_LON_EQ * np.cos(np.radians((lat + new_lat) / 2.0)))
    return new_lat, new_lon


def _shape(r: np.ndarray, rm: np.ndarray, b: float) -> np.ndarray:
    q = (rm / np.maximum(r, 1.0)) ** b
    return q * np.exp(1.0 - q)


def sustained_wind(
    track: Track,
    times: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    *,
    holland_b: float,
    inner_exponent: float,
    r34_fallback: float,
    r34_extent: float = 1.0,
    taper_start: float = OUTER_TAPER_START,
    taper_end: float = OUTER_TAPER_END,
) -> np.ndarray:
    """1-min sustained 10 m wind (m/s), shape (len(times), len(points))."""
    s = track.at(times)
    dx, dy = offsets_km(s["lat"][:, None], s["lon"][:, None], lat[None, :], lon[None, :])
    r = np.hypot(dx, dy)
    az = np.degrees(np.arctan2(dx, dy)) % 360.0
    shifted = (az - 45.0) % 360.0
    q0 = np.floor(shifted / 90.0).astype(int) % 4
    frac = (shifted - 90.0 * np.floor(shifted / 90.0)) / 90.0
    rm = s["rmw"][:, None]
    r34_eff = np.maximum(r34_extent * s["r34"], r34_fallback * s["rmw"][:, None])
    rows = np.arange(len(times))[:, None]
    r34 = r34_eff[rows, q0] * (1.0 - frac) + r34_eff[rows, (q0 + 1) % 4] * frac
    vm = s["vmax"][:, None]
    with np.errstate(divide="ignore", invalid="ignore"):
        x_out = np.where(
            vm > TS_MS,
            np.log(TS_MS / np.maximum(vm, 1e-6)) / np.log(_shape(r34, rm, holland_b)),
            inner_exponent,
        )
    x_out = np.clip(x_out, OUTER_EXPONENT_MIN, OUTER_EXPONENT_MAX)
    x = np.where(r <= rm, inner_exponent, x_out)
    v = vm * _shape(r, rm, holland_b) ** x
    taper = np.clip((taper_end * r34 - r) / ((taper_end - taper_start) * r34), 0.0, 1.0)
    return np.where(vm > 0.0, v * taper, 0.0)


def first_crossing(series: np.ndarray, times: np.ndarray, threshold: Any) -> np.ndarray:
    """First time (epoch s) each column reaches `threshold` (scalar or per column); NaN if never."""
    hit = series >= threshold
    any_hit = hit.any(axis=0)
    idx = np.argmax(hit, axis=0)
    return np.where(any_hit, times[idx], np.nan)


def last_crossing(series: np.ndarray, times: np.ndarray, threshold: Any) -> np.ndarray:
    hit = series >= threshold
    any_hit = hit.any(axis=0)
    idx = hit.shape[0] - 1 - np.argmax(hit[::-1], axis=0)
    return np.where(any_hit, times[idx], np.nan)


def calm_after_peak(series: np.ndarray, times: np.ndarray, threshold: float) -> np.ndarray:
    """First time after each column's peak at which the series is below `threshold`; NaN if it never drops."""
    ipk = np.argmax(series, axis=0)
    below = (series < threshold) & (np.arange(series.shape[0])[:, None] > ipk[None, :])
    any_below = below.any(axis=0)
    return np.where(any_below, times[np.argmax(below, axis=0)], np.nan)
