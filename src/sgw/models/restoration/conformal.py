"""Split conformal calibration of ETR intervals (conformalised quantile regression on log hours).

Calibration storms are split in two disjoint parts. On the first, every quantile is shifted by the median
log error of P50 (a bias correction). On the second, for a nominal level 1 - alpha the shifted (alpha/2,
1 - alpha/2) quantiles q_lo, q_hi are scored by s = max(log q_lo - log y, log y - log q_hi) and the interval
is widened (or narrowed) by the ceil((n + 1)(1 - alpha))-th smallest score. Coverage is then measured on test
storms never used to fit or calibrate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

FLOOR_H = 0.25


def conformal_quantile(scores: np.ndarray, alpha: float) -> float:
    n = len(scores)
    if n == 0:
        raise ValueError("no calibration scores")
    k = math.ceil((n + 1) * (1.0 - alpha))
    if k > n:
        return math.inf
    return float(np.sort(scores)[k - 1])


def cqr_scores(q_lo: np.ndarray, q_hi: np.ndarray, y: np.ndarray) -> np.ndarray:
    ly = np.log(np.maximum(y, FLOOR_H))
    return np.maximum(np.log(np.maximum(q_lo, FLOOR_H)) - ly, ly - np.log(np.maximum(q_hi, FLOOR_H)))


@dataclass(frozen=True)
class Calibrator:
    """Log-scale adjustments learned on calibration storms for one population (regional or global)."""

    widen_80: float
    widen_50: float
    shift_50: float
    n: int

    @classmethod
    def fit(cls, q_shift: np.ndarray, y_shift: np.ndarray, q: np.ndarray, y: np.ndarray) -> Calibrator:
        """`q_*`: [n, 5] model quantiles (P10, P25, P50, P75, P90) in hours; `y_*`: realised hours.
        The shift comes from (`q_shift`, `y_shift`), the conformal scores from the disjoint (`q`, `y`)."""
        shift = float(
            np.median(np.log(np.maximum(y_shift, FLOOR_H)) - np.log(np.maximum(q_shift[:, 2], FLOOR_H)))
        )
        qs = q * math.exp(shift)
        s80 = cqr_scores(qs[:, 0], qs[:, 4], y)
        s50 = cqr_scores(qs[:, 1], qs[:, 3], y)
        return cls(conformal_quantile(s80, 0.2), conformal_quantile(s50, 0.5), shift, len(y))

    def apply(self, q: np.ndarray) -> np.ndarray:
        """Calibrated (P10, P25, P50, P75, P90) in hours, ordered."""
        lq = np.log(np.maximum(np.atleast_2d(q), FLOOR_H)) + self.shift_50
        out = lq.copy()
        out[:, 0] = lq[:, 0] - self.widen_80
        out[:, 4] = lq[:, 4] + self.widen_80
        out[:, 1] = lq[:, 1] - self.widen_50
        out[:, 3] = lq[:, 3] + self.widen_50
        return np.exp(np.sort(out, axis=1))


def coverage(lo: np.ndarray, hi: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((y >= lo) & (y <= hi)))


def clustered_ci(
    covered: np.ndarray, cluster: np.ndarray, n_boot: int = 2000, seed: int = 17
) -> tuple[float, float]:
    """95 percent bootstrap interval of a coverage rate, resampling whole storms (regions share a storm)."""
    ids = np.unique(cluster)
    per = {c: covered[cluster == c] for c in ids}
    r = np.random.default_rng(seed)
    stats = np.empty(n_boot)
    for b in range(n_boot):
        pick = r.choice(ids, size=len(ids), replace=True)
        v = np.concatenate([per[c] for c in pick])
        stats[b] = v.mean()
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))
