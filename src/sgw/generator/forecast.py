"""Synthetic advisories and per-advisory ensembles.

An advisory issued at tau forecasts the storm state at tau + L as the truth state displaced by an along-track
and a cross-track error and with an intensity error. Errors are z * sigma(L): sigma(L) is the NHC cone radius
divided by sqrt(2 ln 3) (two-thirds inside the cone), intensity sigma grows to its 24-h value; z follows an
AR(1) process over a 12-h lead grid. The official forecast has one draw per advisory (or the seeded override);
each ensemble member adds a draw around the official forecast. Member m reuses the same draw in every advisory
(common random numbers), so differences between advisories come from the official forecast and the shrinking
lead time, not from resampling noise. Radii and RMW follow the truth
(no size error, an assumption).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from sgw.generator.config import Family, parse_utc, rng
from sgw.generator.wind import KT, Track, displace, epoch


@dataclass(frozen=True)
class Advisory:
    label: str
    forecast_id: str
    issued: datetime
    next_issued: datetime | None


def advisory_label(k: int) -> str:
    return "N" if k == 0 else (f"N+{k}" if k > 0 else f"N{k}")


def forecast_id(label: str) -> str:
    return "ADV-HELENE-SYN-" + label.replace("+", "P")


def advisories(scenario: dict[str, Any]) -> list[Advisory]:
    a = scenario["advisories"]
    first, last, n_utc = parse_utc(a["first_utc"]), parse_utc(a["last_utc"]), parse_utc(a["n_utc"])
    step = timedelta(hours=int(a["every_h"]))
    times = []
    t = first
    while t <= last:
        times.append(t)
        t += step
    out = []
    for i, t in enumerate(times):
        k = round((t - n_utc) / step)
        label = advisory_label(k)
        out.append(Advisory(label, forecast_id(label), t, times[i + 1] if i + 1 < len(times) else None))
    return out


def _sigma_km(lead_h: np.ndarray, fam: Family) -> np.ndarray:
    radius = np.interp(lead_h, fam.arr("forecast.cone_lead_h"), fam.arr("forecast.cone_radius_nmi"))
    return radius * 1.852 / fam.f("forecast.cone_to_sigma")


def _ar1_z(r: np.random.Generator, lead_h: np.ndarray, rho: float) -> np.ndarray:
    grid = np.arange(0.0, lead_h.max() + 12.0, 12.0)
    z = np.empty(len(grid))
    z[0] = r.standard_normal()
    for k in range(1, len(grid)):
        z[k] = rho * z[k - 1] + np.sqrt(1.0 - rho**2) * r.standard_normal()
    return np.interp(lead_h, grid, z)


def error_draw(r: np.random.Generator, lead_h: np.ndarray, fam: Family) -> dict[str, np.ndarray]:
    rho = fam.f("forecast.lead_ar1_rho_per_12h")
    return {k: _ar1_z(r, lead_h, rho) for k in ("along_z", "cross_z", "intensity_z")}


def forecast_track(
    truth: Track, issued: datetime, fam: Family, z: dict[str, np.ndarray], lead_h: np.ndarray
) -> Track:
    times = epoch(issued) + lead_h * 3600.0
    st = truth.at(times)
    heading = truth.heading_rad(times)
    sig = _sigma_km(lead_h, fam)
    along = z["along_z"] * sig
    cross = z["cross_z"] * sig
    dx = along * np.sin(heading) + cross * np.cos(heading)
    dy = along * np.cos(heading) - cross * np.sin(heading)
    lat, lon = displace(st["lat"], st["lon"], dx, dy)
    sig_i = fam.f("forecast.intensity_sigma_kt") * KT * np.minimum(1.0, lead_h / 24.0)
    vmax = np.maximum(st["vmax"] + z["intensity_z"] * sig_i, 0.0)
    return Track(t=times, lat=lat, lon=lon, vmax=vmax, rmw=st["rmw"], r34=st["r34"])


def lead_grid(fam: Family, step_h: float = 3.0) -> np.ndarray:
    return np.arange(0.0, fam.f("forecast.horizon_h") + step_h, step_h)


def official_errors(
    adv: Advisory, scenario: dict[str, Any], fam: Family, seed: int, lead_h: np.ndarray
) -> tuple[dict[str, np.ndarray], bool]:
    overrides = scenario["advisories"].get("official_error_overrides", {})
    if adv.label in overrides:
        o = overrides[adv.label]
        return {k: np.full(len(lead_h), float(o[k])) for k in ("along_z", "cross_z", "intensity_z")}, True
    return error_draw(rng(seed, "forecast", "official", adv.label), lead_h, fam), False


def member_tracks(
    truth: Track, adv: Advisory, scenario: dict[str, Any], fam: Family, seed: int
) -> tuple[Track, list[Track], bool]:
    lead_h = lead_grid(fam)
    z_off, pinned = official_errors(adv, scenario, fam, seed, lead_h)
    official = forecast_track(truth, adv.issued, fam, z_off, lead_h)
    members = []
    for m in range(int(fam["forecast.members"])):
        dz = error_draw(rng(seed, "forecast", "member", m), lead_h, fam)
        members.append(forecast_track(truth, adv.issued, fam, {k: z_off[k] + dz[k] for k in z_off}, lead_h))
    return official, members, pinned
