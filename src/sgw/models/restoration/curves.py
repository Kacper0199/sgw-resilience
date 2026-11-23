"""Customers-out series from outage intervals, and the restoration times read from them.

`t50`/`t90` follow the EAGLE-I definition used by the Helene validation table: hours from the series peak
until customers out first fall to 50 / 10 percent of that peak (90 percent of the peak restored).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from sgw.models.restoration.process import SECONDARY, ProcessRun


@dataclass(frozen=True)
class Intervals:
    """Customer groups out of service over [start, end); `end` is inf while unrestored."""

    key: np.ndarray
    customers: np.ndarray
    start: np.ndarray
    end: np.ndarray


def run_intervals(run: ProcessRun, by: str = "region") -> Intervals:
    w = run.world
    out_start, out_end = run.section_out
    keys = w.region if by == "region" else w.fips
    sec = run.jobs.kind == SECONDARY
    parent = run.jobs.section[sec]
    sec_customers = np.zeros(len(w.customers))
    np.add.at(sec_customers, parent, run.jobs.customers[sec])
    out = ~np.isnan(out_start)
    primary = np.flatnonzero(out)
    return Intervals(
        key=np.concatenate([keys[primary], keys[parent]]),
        customers=np.concatenate([w.customers[primary] - sec_customers[primary], run.jobs.customers[sec]]),
        start=np.concatenate([out_start[primary], out_start[parent]]),
        end=np.concatenate([out_end[primary], run.secondary_out_end]),
    )


def series(iv: Intervals, keys: list[object], grid: np.ndarray) -> np.ndarray:
    """Customers out per key at each grid time: shape [len(keys), len(grid)]."""
    pos = {k: i for i, k in enumerate(keys)}
    rows = np.array([pos.get(k, -1) for k in iv.key.tolist()], dtype=int)
    keep = rows >= 0
    n = len(grid)
    delta = np.zeros((len(keys), n + 1))
    s = np.searchsorted(grid, iv.start[keep], side="left")
    e = np.searchsorted(grid, np.where(np.isfinite(iv.end[keep]), iv.end[keep], np.inf), side="left")
    np.add.at(delta, (rows[keep], s), iv.customers[keep])
    np.add.at(delta, (rows[keep], e), -iv.customers[keep])
    return np.cumsum(delta, axis=1)[:, :n]


def hours_to_share(curve: np.ndarray, grid: np.ndarray, restored_share: float) -> tuple[float, float, float]:
    """(peak customers, peak time, hours from peak to `restored_share` of the peak restored; nan if never)."""
    peak = float(curve.max()) if len(curve) else 0.0
    if peak <= 0:
        return 0.0, math.nan, math.nan
    ip = int(np.argmax(curve))
    hit = np.flatnonzero(curve[ip:] <= (1.0 - restored_share) * peak * (1.0 + 1e-9))
    if not len(hit):
        return peak, float(grid[ip]), math.nan
    return peak, float(grid[ip]), float((grid[ip + hit[0]] - grid[ip]) / 3600.0)


def run_grid(run: ProcessRun, horizon_days: float, step_s: float) -> np.ndarray:
    t0 = run.world.start_t
    return np.arange(t0, t0 + horizon_days * 86400.0 + 1.0, step_s)


def county_times(
    run: ProcessRun, horizon_days: float = 30.0, step_s: float = 900.0
) -> dict[str, dict[str, float]]:
    grid = run_grid(run, horizon_days, step_s)
    iv = run_intervals(run, by="fips")
    keys = sorted(set(run.world.fips.tolist()))
    s = series(iv, list(keys), grid)
    out: dict[str, dict[str, float]] = {}
    for i, k in enumerate(keys):
        peak, tpeak, t50 = hours_to_share(s[i], grid, 0.5)
        if peak <= 0:
            continue
        _, _, t90 = hours_to_share(s[i], grid, 0.9)
        out[str(k)] = {"peak_out": peak, "peak_utc": tpeak, "t50_h": t50, "t90_h": t90}
    return out


def censored_median(values: list[float]) -> float:
    """Median with nan read as 'not reached in the window' (above every finite value)."""
    if not values:
        return math.nan
    arr = np.array([math.inf if math.isnan(v) else v for v in values])
    return float(np.median(arr))
