"""A2 county outage model: LightGBM Tweedie mean plus quantile models, CQR conformal fans, TreeSHAP drivers.

Unit: county x storm. Target: peak fraction of MCC customers out (`peak_frac`, 0..1). Hazard features come
from `sgw.models.hazard.field.point_features` on both the training and the serving path.

- Mean: Tweedie objective (many near-zero counties, a heavy upper tail); used for totals.
- Quantiles at `ALPHAS`, rearranged so they never cross (Chernozhukov et al. 2010).
- Conformal (storm-grouped CQR, uncalibrated across storm types): conformalised quantile regression
  (Romano et al. 2019) per nested central interval (50/80/95%); scores from an inner leave-one-storm-out
  over the training storms (storm-grouped, so they carry between-storm error a random split would hide),
  Mondrian by wind band with a pooled fallback when a band has fewer than `MIN_BAND_N` scores. Three
  training storms cannot calibrate a storm unlike them: coverage is reported per storm.
- Monotone constraints on the mean model: more wind or longer wind never lowers it; a farther track never
  raises it. LightGBM refuses monotone constraints with the quantile objective, so the quantile models are
  unconstrained (their crossing is repaired by rearrangement, their calibration by the conformal step).
- Hyperparameters are fixed a priori: with three training storms per fold any tuning would be fitted to noise.

Options (selected by nested leave-one-storm-out, never on the held-out storm):
- `prior_offset`: the mean model boosts from the fragility prior, init score ln(max(prior, PRIOR_FLOOR))
  on the Tweedie log link, so the trees learn a correction to the physics curve instead of the whole curve.
- `interval_space="log"`: CQR scores on ln(y + LOG_EPS) instead of y, so interval width scales with the
  size of the outage (scale-aware) instead of one absolute width per wind band.
- `blend`: mean = weight * model mean + (1 - weight) * a lognormal fragility curve on gust fitted on the same
  training storms (`median_ms`, `beta`); quantiles and intervals stay the model's.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import norm

from sgw.models.hazard.field import EXTRA_FEATURES, HAZARD_FEATURES
from sgw.models.outage.baseline import fragility_prior

FEATURES: tuple[str, ...] = (*HAZARD_FEATURES, "log_customers")
KNOWN_FEATURES: tuple[str, ...] = (*FEATURES, *EXTRA_FEATURES)
PRIOR_FLOOR = 1e-4
LOG_EPS = 1e-3
INTERVAL_SPACES = ("linear", "log")
MONOTONE = {
    "hours_centre_within_200km": 1,
    "rain_window_mm": 1,
    "rain_antecedent_14d_mm": 1,
    "peak_gust_ms": 1,
    "hours_gust_ge_20": 1,
    "hours_ts": 1,
    "min_dist_km": -1,
    "speed_kmh_closest": 0,
    "vmax_ms_closest": 0,
    "log_customers": 0,
}
ALPHAS: tuple[float, ...] = (0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975)
INTERVALS: dict[str, tuple[float, float]] = {"50": (0.25, 0.75), "80": (0.1, 0.9), "95": (0.025, 0.975)}
WIND_BANDS_MS: tuple[float, ...] = (20.0, 30.0)
MIN_BAND_N = 30
SEED = 20241
BASE_PARAMS: dict[str, Any] = {
    "n_estimators": 300,
    "learning_rate": 0.03,
    "num_leaves": 7,
    "min_child_samples": 15,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.9,
    "reg_lambda": 1.0,
    "random_state": SEED,
    "deterministic": True,
    "force_row_wise": True,
    "n_jobs": 2,
    "verbose": -1,
}
MEAN_PARAMS: dict[str, Any] = {"objective": "tweedie", "tweedie_variance_power": 1.3}


STORM_LEVEL_FEATURES: tuple[str, ...] = ("speed_kmh_closest", "vmax_ms_closest")


def design(frame: pd.DataFrame, features: tuple[str, ...] = FEATURES) -> pd.DataFrame:
    return frame.loc[:, list(features)].astype(float)


def wind_band(gust: np.ndarray) -> np.ndarray:
    return np.digitize(np.asarray(gust, dtype=float), WIND_BANDS_MS)


def prior_init(frame: pd.DataFrame) -> np.ndarray:
    return np.log(np.maximum(fragility_prior(frame), PRIOR_FLOOR))


def _fit_one(
    x: pd.DataFrame, y: np.ndarray, params: dict[str, Any], init_score: np.ndarray | None = None
) -> lgb.Booster:
    monotone = [MONOTONE[str(c)] for c in x.columns]
    constraints = {} if params.get("objective") == "quantile" else {"monotone_constraints": monotone}
    model = lgb.LGBMRegressor(**BASE_PARAMS, **params, **constraints)
    model.fit(x, y, init_score=init_score)
    return model.booster_


@dataclass
class RawModels:
    mean: lgb.Booster
    quantiles: dict[float, lgb.Booster]
    prior_offset: bool = False

    def predict_mean(self, x: pd.DataFrame, frame: pd.DataFrame) -> np.ndarray:
        if self.prior_offset:
            raw = np.asarray(self.mean.predict(x, raw_score=True)) + prior_init(frame)
            return np.clip(np.exp(raw), 0.0, 1.0)
        return np.clip(np.asarray(self.mean.predict(x)), 0.0, 1.0)

    def predict(self, x: pd.DataFrame, frame: pd.DataFrame | None = None) -> tuple[np.ndarray, np.ndarray]:
        mean = self.predict_mean(x, x if frame is None else frame)
        q = np.column_stack([np.asarray(self.quantiles[a].predict(x)) for a in ALPHAS])
        return mean, np.clip(np.sort(q, axis=1), 0.0, 1.0)


def fit_mean(
    frame: pd.DataFrame, features: tuple[str, ...] = FEATURES, prior_offset: bool = False
) -> lgb.Booster:
    x, y = design(frame, features), frame["peak_frac"].to_numpy(dtype=float)
    return _fit_one(x, y, MEAN_PARAMS, prior_init(frame) if prior_offset else None)


def fit_raw(
    frame: pd.DataFrame, features: tuple[str, ...] = FEATURES, prior_offset: bool = False
) -> RawModels:
    x, y = design(frame, features), frame["peak_frac"].to_numpy(dtype=float)
    return RawModels(
        mean=fit_mean(frame, features, prior_offset),
        quantiles={a: _fit_one(x, y, {"objective": "quantile", "alpha": a}) for a in ALPHAS},
        prior_offset=prior_offset,
    )


def to_space(v: np.ndarray, space: str) -> np.ndarray:
    return np.log(np.asarray(v, dtype=float) + LOG_EPS) if space == "log" else np.asarray(v, dtype=float)


def from_space(v: np.ndarray, space: str) -> np.ndarray:
    return np.exp(v) - LOG_EPS if space == "log" else v


def cqr_scores(y: np.ndarray, q: np.ndarray, interval: str, space: str = "linear") -> np.ndarray:
    lo, hi = INTERVALS[interval]
    ty, tq = to_space(y, space), to_space(q, space)
    return np.maximum(tq[:, ALPHAS.index(lo)] - ty, ty - tq[:, ALPHAS.index(hi)])


def apply_offset(
    q: np.ndarray, interval: str, off: np.ndarray, space: str = "linear"
) -> tuple[np.ndarray, np.ndarray]:
    lo, hi = INTERVALS[interval]
    tq = to_space(q, space)
    return (
        np.clip(from_space(tq[:, ALPHAS.index(lo)] - off, space), 0.0, 1.0),
        np.clip(from_space(tq[:, ALPHAS.index(hi)] + off, space), 0.0, 1.0),
    )


def _conformal_q(scores: np.ndarray, coverage: float) -> float:
    n = len(scores)
    if n == 0:
        return 0.0
    level = min(1.0, math.ceil((n + 1) * coverage) / n)
    return float(np.quantile(scores, level, method="higher"))


def inner_quantiles(
    frame: pd.DataFrame,
    features: tuple[str, ...] = FEATURES,
    fitter: Any = None,
) -> list[tuple[str, np.ndarray, np.ndarray, np.ndarray]]:
    """Leave-one-storm-out over the training storms: (storm, y, quantiles, wind band) per inner storm.

    `fitter(train_frame)` may return cached raw models (the backtest shares fits on the same storm subset)."""
    storms = sorted(frame["storm"].unique())
    if len(storms) < 2:
        raise ValueError("conformal calibration needs at least two training storms")
    fit = fitter or (lambda train: fit_raw(train, features))
    parts = []
    for held in storms:
        inner = fit(frame[frame["storm"] != held])
        test = frame[frame["storm"] == held]
        _, q = inner.predict(design(test, features), test)
        parts.append(
            (held, test["peak_frac"].to_numpy(dtype=float), q, wind_band(test["peak_gust_ms"].to_numpy()))
        )
    return parts


def offsets_from_parts(
    parts: list[tuple[str, np.ndarray, np.ndarray, np.ndarray]], space: str = "linear"
) -> dict[str, dict[str, float]]:
    y = np.concatenate([p[1] for p in parts])
    q = np.vstack([p[2] for p in parts])
    band = np.concatenate([p[3] for p in parts])
    out: dict[str, dict[str, float]] = {}
    for name, (lo, hi) in INTERVALS.items():
        coverage = hi - lo
        scores = cqr_scores(y, q, name, space)
        pooled = _conformal_q(scores, coverage)
        out[name] = {"pooled": pooled}
        for b in range(len(WIND_BANDS_MS) + 1):
            s = scores[band == b]
            out[name][str(b)] = _conformal_q(s, coverage) if len(s) >= MIN_BAND_N else pooled
    return out


def conformal_offsets(
    frame: pd.DataFrame, features: tuple[str, ...] = FEATURES, space: str = "linear", fitter: Any = None
) -> dict[str, dict[str, float]]:
    """Inner leave-one-storm-out CQR scores on the training storms; one offset per interval and wind band."""
    return offsets_from_parts(inner_quantiles(frame, features, fitter), space)


@dataclass
class Forecast:
    mean: np.ndarray
    quantiles: np.ndarray
    intervals: dict[str, tuple[np.ndarray, np.ndarray]]

    @property
    def p50(self) -> np.ndarray:
        return self.quantiles[:, ALPHAS.index(0.5)]


@dataclass
class OutageModel:
    raw: RawModels
    offsets: dict[str, dict[str, float]]
    trained_on: list[str]
    features: tuple[str, ...] = FEATURES
    meta: dict[str, Any] = field(default_factory=dict)
    interval_space: str = "linear"
    blend: dict[str, float] | None = None

    def blended_mean(self, mean: np.ndarray, frame: pd.DataFrame) -> np.ndarray:
        if not self.blend:
            return mean
        gust = np.maximum(frame["peak_gust_ms"].to_numpy(dtype=float), 1e-6)
        curve = norm.cdf(np.log(gust / self.blend["median_ms"]) / self.blend["beta"])
        w = self.blend["weight"]
        return np.clip(w * mean + (1.0 - w) * curve, 0.0, 1.0)

    @classmethod
    def fit(
        cls,
        frame: pd.DataFrame,
        features: tuple[str, ...] = FEATURES,
        prior_offset: bool = False,
        interval_space: str = "linear",
        fitter: Any = None,
    ) -> OutageModel:
        fit = fitter or (lambda train: fit_raw(train, features, prior_offset))
        return cls(
            raw=fit(frame),
            offsets=conformal_offsets(frame, features, interval_space, fit),
            trained_on=sorted(frame["storm"].unique()),
            features=features,
            interval_space=interval_space,
        )

    def predict(self, frame: pd.DataFrame) -> Forecast:
        mean, q = self.raw.predict(design(frame, self.features), frame)
        mean = self.blended_mean(mean, frame)
        band = wind_band(frame["peak_gust_ms"].to_numpy())
        intervals = {}
        for name in INTERVALS:
            off = np.array([self.offsets[name][str(b)] for b in band])
            intervals[name] = apply_offset(q, name, off, self.interval_space)
        lo95, hi95 = intervals["95"]
        lo80, hi80 = intervals["80"]
        lo50, hi50 = intervals["50"]
        intervals["80"] = (np.minimum(lo80, lo50), np.maximum(hi80, hi50))
        intervals["95"] = (np.minimum(lo95, intervals["80"][0]), np.maximum(hi95, intervals["80"][1]))
        return Forecast(mean=mean, quantiles=q, intervals=intervals)

    def shap(self, frame: pd.DataFrame) -> pd.DataFrame:
        """TreeSHAP contributions of the mean model (log link scale), one column per feature."""
        import shap

        x = design(frame, self.features)
        values = shap.TreeExplainer(self.raw.mean).shap_values(x)
        return pd.DataFrame(np.asarray(values), columns=list(self.features), index=frame.index)

    def save(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.raw.mean.save_model(str(folder / "mean.txt"))
        for a, m in self.raw.quantiles.items():
            m.save_model(str(folder / f"q{int(round(a * 1000)):04d}.txt"))
        card = {
            "trained_on": self.trained_on,
            "features": list(self.features),
            "alphas": list(ALPHAS),
            "intervals": {k: list(v) for k, v in INTERVALS.items()},
            "interval_method": (
                "storm-grouped CQR, uncalibrated across storm types (coverage reported per storm)"
            ),
            "interval_space": self.interval_space,
            "blend": self.blend,
            "prior_offset": self.raw.prior_offset,
            "wind_bands_ms": list(WIND_BANDS_MS),
            "conformal_offsets": self.offsets,
            "params": {**BASE_PARAMS, "mean": MEAN_PARAMS, "monotone": MONOTONE},
            **self.meta,
        }
        (folder / "card.json").write_text(json.dumps(card, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load(folder: Path) -> OutageModel:
    card = json.loads((folder / "card.json").read_text(encoding="utf-8"))
    unknown = set(card["features"]) - set(KNOWN_FEATURES)
    if unknown:
        raise ValueError(f"{folder}: model uses features the code does not compute: {sorted(unknown)}")
    raw = RawModels(
        mean=lgb.Booster(model_file=str(folder / "mean.txt")),
        quantiles={
            a: lgb.Booster(model_file=str(folder / f"q{int(round(a * 1000)):04d}.txt")) for a in ALPHAS
        },
        prior_offset=bool(card.get("prior_offset", False)),
    )
    meta = {k: v for k, v in card.items() if k in ("name", "data_sha256", "version")}
    return OutageModel(
        raw=raw,
        offsets=card["conformal_offsets"],
        trained_on=card["trained_on"],
        features=tuple(card["features"]),
        meta=meta,
        interval_space=str(card.get("interval_space", "linear")),
        blend=card.get("blend"),
    )
