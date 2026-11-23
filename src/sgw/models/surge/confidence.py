"""Surge confidence: P(an NCEI storm event of the county coincides), logistic on two causal features.

Features at detection: log10 of the excess share of customers out over the baseline, and log1p of the number
of other footprint counties with a surge detected within +-3 h (storms hit many counties at once; equipment
failures hit one). Fitted on train-season surges only; the test Brier score is compared with the train base
rate. The label is incomplete (NCEI misses non-severe storms), so the score ranks surges and is a lower bound
on the probability that weather caused the surge.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression

EXCESS_FLOOR = 1e-5
HIGH = 0.5
MEDIUM = 0.2


def features(excess_share: np.ndarray, concurrent: np.ndarray) -> np.ndarray:
    excess = np.log10(np.maximum(np.asarray(excess_share, dtype=float), EXCESS_FLOOR))
    return np.column_stack([excess, np.log1p(np.asarray(concurrent, dtype=float))])


def fit(excess_share: np.ndarray, concurrent: np.ndarray, explained: np.ndarray) -> dict[str, Any]:
    model = LogisticRegression(C=1.0).fit(
        features(excess_share, concurrent), np.asarray(explained, dtype=int)
    )
    return {
        "features": ["log10_excess_share", "log1p_concurrent_counties"],
        "coef": [float(c) for c in model.coef_[0]],
        "intercept": float(model.intercept_[0]),
        "bands": {"high": HIGH, "medium": MEDIUM},
    }


def predict(coefs: dict[str, Any], excess_share: np.ndarray, concurrent: np.ndarray) -> np.ndarray:
    z = features(excess_share, concurrent) @ np.asarray(coefs["coef"]) + coefs["intercept"]
    return 1.0 / (1.0 + np.exp(-z))


def band(p: float, coefs: dict[str, Any]) -> str:
    if p >= coefs["bands"]["high"]:
        return "high"
    return "medium" if p >= coefs["bands"]["medium"] else "low"
