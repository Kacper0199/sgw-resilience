"""Named baselines for the outage backtest.

- `wind_threshold`: the rule a planner uses without a model: counties whose peak gust reaches T lose a share
  `a` of customers, the others `b`. T, a and b are fitted on the training storms of each fold
  (customer-weighted shares; T on a 1 m/s grid minimising the absolute error in customers), so the
  baseline gets the same data as the model.
- `fragility_prior`: the physics prior with no fitting, lognormal on gust with median and dispersion from
  numbers.yaml (`fragility_median_gust_ms`, beta 0.4 from the project fact base).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

from sgw.common import numbers as numbers_mod

THRESHOLD_GRID_MS = np.arange(10.0, 51.0, 1.0)
FRAGILITY_BETA = 0.4


@dataclass(frozen=True)
class WindThreshold:
    threshold_ms: float
    share_above: float
    share_below: float

    @classmethod
    def fit(cls, frame: pd.DataFrame) -> WindThreshold:
        gust = frame["peak_gust_ms"].to_numpy(dtype=float)
        customers = frame["customers_mcc"].to_numpy(dtype=float)
        out = frame["peak_frac"].to_numpy(dtype=float) * customers
        best: tuple[float, WindThreshold] | None = None
        for t in THRESHOLD_GRID_MS:
            above = gust >= t
            a = out[above].sum() / customers[above].sum() if above.any() else 0.0
            b = out[~above].sum() / customers[~above].sum() if (~above).any() else 0.0
            err = float(np.abs(np.where(above, a, b) * customers - out).sum())
            if best is None or err < best[0]:
                best = (err, cls(float(t), float(a), float(b)))
        assert best is not None
        return best[1]

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        gust = frame["peak_gust_ms"].to_numpy(dtype=float)
        return np.where(gust >= self.threshold_ms, self.share_above, self.share_below)


def fragility_prior(frame: pd.DataFrame) -> np.ndarray:
    median = float(numbers_mod.value("fragility_median_gust_ms"))
    gust = np.maximum(frame["peak_gust_ms"].to_numpy(dtype=float), 1e-6)
    return np.asarray(norm.cdf(np.log(gust / median) / FRAGILITY_BETA))
