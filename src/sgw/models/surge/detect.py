"""Outage-surge detectors on 15-min county customers-out series (G1).

Input is a matrix `x` (time x county) of customers out with NaN for feed-gap slots (no county reported), the
EAGLE-I modelled customers per county (`mcc`) and the UTC times. Every detector is causal: the value at slot
t uses slots <= t only, so a run on a series cut at `as_of` returns exactly the surges of the full run that
were detected by then (prefix stability, tested).

Methods:
- `robust_cusum` (the model): residual of log1p(customers out) against the rolling median of the previous
  `window_h`, divided by the rolling IQR scale (floored), fed to a one-sided CUSUM with allowance `k`;
  a surge starts when the statistic reaches `h` and the excess over the baseline level passes a magnitude gate
  (`min_customers` and `min_share` of MCC). The onset estimate is the slot after the statistic last was 0.
  Optional spatial corroboration (`corroborate` > 0): a county's start counts only once at least that many
  other counties started within the last `corroborate_h` (storms hit neighbours, equipment faults do not).
- `fixed_share` (baseline 1): customers out / MCC at or above `share` (with `corroborate` > 0: the ablation
  that adds the model's spatial corroboration to the baseline).
- `rolling_z` (baseline 2): (x - rolling mean) / (rolling sd + 1) at or above `z`, same magnitude gate.

All methods share one segmentation: a surge starts at a start condition outside an active surge, holds the
baseline level of its detection slot, and ends once customers out stayed below that level plus half the
magnitude gate for `end_h` hours.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Literal

import numpy as np
import pandas as pd

STEPS_PER_H = 4
GAP_LOOKBACK_H = 4.0
STAT_CAP_FACTOR = 2.0


def _positive(**values: float) -> None:
    for name, v in values.items():
        if not v > 0:
            raise ValueError(f"{name} must be positive, got {v}")


@dataclass(frozen=True)
class CusumParams:
    method: ClassVar[str] = "robust_cusum"
    window_h: float = 168.0
    k: float = 1.0
    h: float = 6.0
    scale_floor: float = 0.3
    min_customers: float = 100.0
    min_share: float = 0.002
    end_h: float = 6.0
    corroborate: int = 0
    corroborate_h: float = 3.0

    def __post_init__(self) -> None:
        _positive(window_h=self.window_h, k=self.k, h=self.h, scale_floor=self.scale_floor, end_h=self.end_h)
        if self.corroborate < 0:
            raise ValueError(f"corroborate must be >= 0, got {self.corroborate}")


@dataclass(frozen=True)
class FixedShareParams:
    method: ClassVar[str] = "fixed_share"
    share: float = 0.01
    window_h: float = 168.0
    end_h: float = 6.0
    corroborate: int = 0
    corroborate_h: float = 3.0

    def __post_init__(self) -> None:
        _positive(share=self.share, window_h=self.window_h, end_h=self.end_h)


@dataclass(frozen=True)
class RollingZParams:
    method: ClassVar[str] = "rolling_z"
    z: float = 4.0
    window_h: float = 168.0
    min_customers: float = 100.0
    min_share: float = 0.002
    end_h: float = 6.0

    def __post_init__(self) -> None:
        _positive(z=self.z, window_h=self.window_h, end_h=self.end_h)


Params = CusumParams | FixedShareParams | RollingZParams


@dataclass(frozen=True)
class Surge:
    county: int
    onset_at: pd.Timestamp
    detected_at: pd.Timestamp
    ended_at: pd.Timestamp | None
    status: Literal["active", "ended"]
    baseline_customers_out: float
    customers_out_detect: float
    customers_out_last: float
    peak_customers_out: float
    peak_at: pd.Timestamp
    share_out: float
    excess_share_detect: float
    statistic: float
    dq_flags: tuple[str, ...] = field(default_factory=tuple)


def _rolling(frame: pd.DataFrame, window_h: float) -> pd.core.window.rolling.Rolling:
    steps = int(window_h * STEPS_PER_H)
    return frame.rolling(steps, min_periods=max(steps // 4, 1))


def gate(params: Params, mcc: np.ndarray) -> np.ndarray:
    if isinstance(params, FixedShareParams):
        return params.share * mcc
    return np.maximum(params.min_customers, params.min_share * mcc)


def baseline_level(x: np.ndarray, window_h: float) -> np.ndarray:
    """Rolling median of the previous `window_h` (current slot excluded), in customers out."""
    logx = pd.DataFrame(np.log1p(x))
    return np.expm1(_rolling(logx, window_h).median().shift(1).to_numpy())


def log_stats(x: np.ndarray, window_h: float) -> tuple[np.ndarray, np.ndarray]:
    """Rolling median and IQR / 1.349 of log1p(x) over the previous `window_h` (current slot excluded)."""
    roll = _rolling(pd.DataFrame(np.log1p(x)), window_h)
    med = roll.median().shift(1).to_numpy()
    iqr = (roll.quantile(0.75) - roll.quantile(0.25)).shift(1).to_numpy() / 1.349
    return med, iqr


def cusum(resid: np.ndarray, k: float, cap: float) -> tuple[np.ndarray, np.ndarray]:
    """One-sided CUSUM per county (NaN residuals hold the state) and the onset index (slot after last 0)."""
    n, c = resid.shape
    stat = np.zeros((n, c))
    onset = np.zeros((n, c), dtype=np.int64)
    s = np.zeros(c)
    last_zero = np.full(c, -1, dtype=np.int64)
    for t in range(n):
        r = resid[t]
        live = ~np.isnan(r)
        s = np.where(live, np.minimum(np.maximum(0.0, s + np.where(live, r, 0.0) - k), cap), s)
        last_zero = np.where(s == 0.0, t, last_zero)
        stat[t] = s
        onset[t] = last_zero + 1
    return stat, onset


def cusum_statistic(
    x: np.ndarray, params: CusumParams, stats: tuple[np.ndarray, np.ndarray] | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """CUSUM statistic, baseline level (customers) and onset index per slot and county."""
    med, iqr = stats if stats is not None else log_stats(x, params.window_h)
    scale = np.fmax(np.nan_to_num(iqr, nan=params.scale_floor), params.scale_floor)
    stat, onset = cusum((np.log1p(x) - med) / scale, params.k, STAT_CAP_FACTOR * params.h)
    return stat, np.expm1(med), onset


def corroborated(start: np.ndarray, others: int, window_h: float) -> np.ndarray:
    """Start flags kept only where at least `others` other counties had a start within the last `window_h`."""
    if others == 0:
        return start
    w = int(window_h * STEPS_PER_H)
    cs = np.cumsum(start, axis=0, dtype=np.int64)
    lagged = np.vstack([np.zeros((w, start.shape[1]), dtype=np.int64), cs[:-w]]) if w < len(cs) else 0 * cs
    recent = (cs - lagged) > 0
    count = recent.sum(axis=1, keepdims=True) - recent
    return start & (count >= others)


def cusum_start(
    stat: np.ndarray, level: np.ndarray, x: np.ndarray, gate_customers: np.ndarray, params: CusumParams
) -> np.ndarray:
    start = np.nan_to_num((stat >= params.h) & (x - level >= gate_customers), nan=False).astype(bool)
    return corroborated(start, params.corroborate, params.corroborate_h)


def start_condition(
    x: np.ndarray, mcc: np.ndarray, params: Params, stats: tuple[np.ndarray, np.ndarray] | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Start flag, baseline level, onset index and statistic per slot and county."""
    n, c = x.shape
    g = gate(params, mcc)
    index = np.arange(n)[:, None].repeat(c, axis=1)
    if isinstance(params, CusumParams):
        stat, level, onset = cusum_statistic(x, params, stats)
        return cusum_start(stat, level, x, g, params), level, onset, stat
    level = np.expm1(stats[0]) if stats is not None else baseline_level(x, params.window_h)
    if isinstance(params, FixedShareParams):
        stat = x / mcc
        start = corroborated(
            np.nan_to_num(stat >= params.share, nan=False).astype(bool),
            params.corroborate,
            params.corroborate_h,
        )
        return start, level, index, np.nan_to_num(stat)
    stat = rolling_z_stat(x, params.window_h)
    return rolling_z_start(stat, level, x, g, params), level, index, stat


def rolling_z_stat(x: np.ndarray, window_h: float) -> np.ndarray:
    roll = _rolling(pd.DataFrame(x), window_h)
    mean = roll.mean().shift(1).to_numpy()
    sd = roll.std().shift(1).to_numpy()
    return np.nan_to_num((x - mean) / (sd + 1.0))


def rolling_z_start(
    stat: np.ndarray, level: np.ndarray, x: np.ndarray, gate_customers: np.ndarray, params: RollingZParams
) -> np.ndarray:
    return np.nan_to_num((stat >= params.z) & (x - level >= gate_customers), nan=False).astype(bool)


def global_gap(x: np.ndarray) -> np.ndarray:
    return np.isnan(x).all(axis=1)


def segment(
    start: np.ndarray,
    x: np.ndarray,
    level: np.ndarray,
    mcc: np.ndarray,
    times: pd.DatetimeIndex,
    *,
    onset: np.ndarray,
    gap: np.ndarray,
    end_h: float,
    gate_customers: np.ndarray | None = None,
    stat: np.ndarray | None = None,
) -> list[Surge]:
    n, c = x.shape
    g = gate_customers if gate_customers is not None else np.zeros(c)
    end_steps = int(end_h * STEPS_PER_H)
    lookback = int(GAP_LOOKBACK_H * STEPS_PER_H)
    filled = np.where(np.isnan(x), -np.inf, x)
    surges: list[Surge] = []
    for j in range(c):
        candidates = np.flatnonzero(start[:, j])
        t_free = 0
        for t0 in candidates:
            if t0 < t_free:
                continue
            base = float(np.nan_to_num(level[t0, j], nan=0.0))
            above = filled[t0:, j] >= base + 0.5 * g[j]
            if start[t0:, j].any():
                above |= start[t0:, j]
            below_run = np.convolve(~above, np.ones(end_steps, dtype=int), "full")[: len(above)]
            done = np.flatnonzero(below_run >= end_steps)
            stop = t0 + int(done[0]) if len(done) else n
            ended = stop < n
            last_above = t0 + int(np.flatnonzero(above[: stop - t0])[-1]) if ended else n - 1
            span = x[t0 : last_above + 1, j]
            k_peak = int(np.nanargmax(span))
            peak = float(span[k_peak])
            flags: list[str] = []
            if gap[max(0, t0 - lookback) : t0 + 1].any():
                flags.append("after_feed_gap")
            if peak > mcc[j]:
                flags.append("exceeds_mcc")
            last_obs = x[: (stop if ended else n), j]
            last_val = last_obs[~np.isnan(last_obs)][-1] if (~np.isnan(last_obs)).any() else 0.0
            x0 = float(x[t0, j])
            surges.append(
                Surge(
                    county=j,
                    onset_at=times[int(min(onset[t0, j], t0))],
                    detected_at=times[t0],
                    ended_at=times[stop] if ended else None,
                    status="ended" if ended else "active",
                    baseline_customers_out=base,
                    customers_out_detect=x0,
                    customers_out_last=float(last_val),
                    peak_customers_out=peak,
                    peak_at=times[t0 + k_peak],
                    share_out=float(min(peak / mcc[j], 1.0)),
                    excess_share_detect=float(max(x0 - base, 0.0) / mcc[j]),
                    statistic=float(stat[t0, j]) if stat is not None else 0.0,
                    dq_flags=tuple(flags),
                )
            )
            t_free = stop
    return sorted(surges, key=lambda s: (s.detected_at, s.county))


def detect(
    x: np.ndarray,
    mcc: np.ndarray,
    times: pd.DatetimeIndex,
    params: Params,
    stats: tuple[np.ndarray, np.ndarray] | None = None,
) -> list[Surge]:
    """Surges of one method; `stats` (`log_stats` of the same window) skips recomputing rolling stats."""
    if x.ndim != 2 or x.shape != (len(times), len(mcc)):
        raise ValueError(f"x {x.shape} does not match times {len(times)} x counties {len(mcc)}")
    start, level, onset, stat = start_condition(x, mcc, params, stats)
    return segment(
        start,
        x,
        level,
        mcc,
        times,
        onset=onset,
        gap=global_gap(x),
        end_h=params.end_h,
        gate_customers=gate(params, mcc),
        stat=stat,
    )
