"""Methods: probit fragility curves with a storm effect, a boosted residual, the wind calibration.

Pre-registration: `docs/models/outage-v3-preregistration.md` (fixed before any outcome run).
- `ProbitCurve.fit`: quasi-binomial probit GLM on `peak_frac` with customer weights. With `storm_effect`, one
  indicator per training storm (no global intercept) and a DerSimonian-Laird random-effects step on the
  storm coefficients gives the population intercept and tau^2. Sign rule: gust, duration and antecedent rain
  slopes must be positive, else the covariate is dropped and the fit repeated.
- County point = Phi(eta_0) (the median storm, u = 0); storm total from the marginal mean
  Phi(eta_0 / sqrt(1 + tau^2)); county intervals from quantiles of the training probit residuals; storm-total
  80% band at u = +-1.2816 tau.
- `BoostedResidual`: LightGBM cross-entropy on top of F2, initialised at each training storm's conditional
  mean Phi(eta_0 + u_s); predictions at u = 0, totals marginalised with F2's tau^2.
- `WindCalibration`: OLS of ln(observed / modelled ASOS peak gust) on the modelled gust, distance to the
  coast, intensity and translation speed; label-free, fitted on the training storms' stations only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import norm

from sgw.models.outage.experiment import FittedFragility

PROBIT_CLIP = 1e-5
INIT_CLIP = 1e-6
Z80 = float(norm.ppf(0.9))
QUANTILES = {"80": (0.10, 0.90), "95": (0.025, 0.975)}
POSITIVE = ("ln_gust", "ln1p_h20", "z_ante")
F1_COVARIATES = ("ln_gust",)
F2_COVARIATES = ("ln_gust", "ln1p_h20", "z_ante", "ln_density")
M1_FEATURES = (*F2_COVARIATES, "vmax_ms_closest", "speed_kmh_closest", "ep_mobile")
M1_MONOTONE = {"ln_gust": 1, "ln1p_h20": 1, "z_ante": 1}
M1_PARAMS: dict[str, Any] = {
    "objective": "cross_entropy",
    "n_estimators": 100,
    "learning_rate": 0.05,
    "num_leaves": 3,
    "min_child_samples": 50,
    "subsample": 1.0,
    "colsample_bytree": 1.0,
    "random_state": 20241,
    "deterministic": True,
    "force_row_wise": True,
    "n_jobs": 1,
    "verbose": -1,
}
CAL_FACTOR = (0.25, 2.0)
CAL_MIN_REPORT_SHARE = 0.75
CAL_MIN_MODEL_GUST_MS = 13.0
GUST_FLOOR_MS = 0.1


@dataclass(frozen=True)
class WindInputs:
    """Which columns carry the wind: the A1 model wind, or the ASOS-calibrated one (w variants)."""

    gust: str = "peak_gust_ms"
    h20: str = "hours_gust_ge_20"


MODEL_WIND = WindInputs()
CAL_WIND = WindInputs("peak_gust_cal_ms", "hours_gust_cal_ge_20")


@dataclass(frozen=True)
class Prediction:
    """Per test county: point and interval fractions; per storm: total and its 80% band (customers)."""

    point: np.ndarray
    total: float
    lo80: np.ndarray | None = None
    hi80: np.ndarray | None = None
    lo95: np.ndarray | None = None
    hi95: np.ndarray | None = None
    total_lo80: float | None = None
    total_hi80: float | None = None
    info: dict[str, Any] = field(default_factory=dict)


def covariates(
    frame: pd.DataFrame, wind: WindInputs, z: tuple[float, float], names: tuple[str, ...]
) -> pd.DataFrame:
    cols = {
        "ln_gust": np.log(np.maximum(frame[wind.gust].to_numpy(dtype=float), GUST_FLOOR_MS)),
        "ln1p_h20": np.log1p(frame[wind.h20].to_numpy(dtype=float)),
        "z_ante": (frame["rain_antecedent_14d_mm"].to_numpy(dtype=float) - z[0]) / z[1],
        "ln_density": np.log(frame["customer_density"].to_numpy(dtype=float)),
        "vmax_ms_closest": frame["vmax_ms_closest"].to_numpy(dtype=float),
        "speed_kmh_closest": frame["speed_kmh_closest"].to_numpy(dtype=float),
        "ep_mobile": frame["ep_mobile"].to_numpy(dtype=float),
    }
    return pd.DataFrame({n: cols[n] for n in names}, index=frame.index)


def z_stats(frame: pd.DataFrame) -> tuple[float, float]:
    ante = frame["rain_antecedent_14d_mm"].to_numpy(dtype=float)
    return float(ante.mean()), float(ante.std()) or 1.0


def customers(frame: pd.DataFrame) -> np.ndarray:
    return frame["customers_mcc"].to_numpy(dtype=float)


def probit_residual_quantiles(y: np.ndarray, eta0: np.ndarray) -> dict[str, tuple[float, float]]:
    r = norm.ppf(np.clip(y, PROBIT_CLIP, 1.0 - PROBIT_CLIP)) - eta0
    return {k: (float(np.quantile(r, lo)), float(np.quantile(r, hi))) for k, (lo, hi) in QUANTILES.items()}


def _intervals(eta0: np.ndarray, rq: dict[str, tuple[float, float]]) -> dict[str, Any]:
    return {
        "lo80": norm.cdf(eta0 + rq["80"][0]),
        "hi80": norm.cdf(eta0 + rq["80"][1]),
        "lo95": norm.cdf(eta0 + rq["95"][0]),
        "hi95": norm.cdf(eta0 + rq["95"][1]),
    }


def dersimonian_laird(u: np.ndarray, se2: np.ndarray) -> tuple[float, float]:
    """Random-effects mean and between-storm variance tau^2 from per-storm estimates and their variances."""
    w = 1.0 / np.maximum(se2, 1e-12)
    mean_fe = float((w * u).sum() / w.sum())
    q = float((w * (u - mean_fe) ** 2).sum())
    c = float(w.sum() - (w**2).sum() / w.sum())
    tau2 = max(0.0, (q - (len(u) - 1)) / c) if c > 0 else 0.0
    ws = 1.0 / (se2 + tau2)
    return float((ws * u).sum() / ws.sum()), tau2


@dataclass
class ProbitCurve:
    """Probit fragility: eta_0 = intercept + x . coef; tau^2 = 0 without the storm effect."""

    names: tuple[str, ...]
    wind: WindInputs
    z: tuple[float, float]
    intercept: float
    coef: np.ndarray
    tau2: float
    rq: dict[str, tuple[float, float]]
    storm_u: dict[str, float]
    dropped: tuple[str, ...] = ()

    @classmethod
    def fit(
        cls,
        train: pd.DataFrame,
        names: tuple[str, ...],
        wind: WindInputs = MODEL_WIND,
        storm_effect: bool = True,
    ) -> ProbitCurve:
        z = z_stats(train)
        y = train["peak_frac"].to_numpy(dtype=float)
        c = customers(train)
        weights = c / c.mean()
        keep = list(names)
        dropped: list[str] = []
        while True:
            x = covariates(train, wind, z, tuple(keep))
            if storm_effect:
                dummies = pd.get_dummies(train["storm"], dtype=float)
                exog = pd.concat([dummies, x], axis=1)
            else:
                exog = sm.add_constant(x, has_constant="add")
            res = sm.GLM(
                y, exog, family=sm.families.Binomial(link=sm.families.links.Probit()), var_weights=weights
            ).fit(scale="X2")
            bad = [n for n in keep if n in POSITIVE and res.params[n] <= 0.0]
            if not bad:
                break
            dropped += bad
            keep = [n for n in keep if n not in bad]
        coef = np.array([res.params[n] for n in keep])
        if storm_effect:
            storms = list(dummies.columns)
            u = res.params[storms].to_numpy()
            se2 = np.diag(res.cov_params().loc[storms, storms].to_numpy())
            intercept, tau2 = dersimonian_laird(u, se2)
            storm_u = {s: float(v - intercept) for s, v in zip(storms, u, strict=True)}
        else:
            intercept, tau2, storm_u = float(res.params["const"]), 0.0, {}
        eta0 = intercept + x[keep].to_numpy() @ coef if keep else np.full(len(train), intercept)
        return cls(
            tuple(keep),
            wind,
            z,
            intercept,
            coef,
            tau2,
            probit_residual_quantiles(y, eta0),
            storm_u,
            tuple(dropped),
        )

    def eta0(self, frame: pd.DataFrame) -> np.ndarray:
        if not self.names:
            return np.full(len(frame), self.intercept)
        return self.intercept + covariates(frame, self.wind, self.z, self.names).to_numpy() @ self.coef

    def predict(self, test: pd.DataFrame) -> Prediction:
        eta0 = self.eta0(test)
        c = customers(test)
        marginal = norm.cdf(eta0 / np.sqrt(1.0 + self.tau2))
        band: dict[str, Any] = {}
        if self.tau2 > 0:
            tau = np.sqrt(self.tau2)
            band = {
                "total_lo80": float((c * norm.cdf(eta0 - Z80 * tau)).sum()),
                "total_hi80": float((c * norm.cdf(eta0 + Z80 * tau)).sum()),
            }
        return Prediction(
            point=norm.cdf(eta0),
            total=float((c * marginal).sum()),
            **_intervals(eta0, self.rq),
            **band,
            info={
                "tau2": round(self.tau2, 4),
                "dropped": list(self.dropped),
                "coef": {n: round(float(v), 4) for n, v in zip(self.names, self.coef, strict=True)},
                "intercept": round(self.intercept, 4),
            },
        )


@dataclass
class GridFragility:
    """B3 / B3w: the WP-11v2 lognormal curve fitted by customer-weighted L1, on a chosen wind column."""

    curve: FittedFragility
    wind: WindInputs
    rq: dict[str, tuple[float, float]]

    @classmethod
    def fit(cls, train: pd.DataFrame, wind: WindInputs = MODEL_WIND) -> GridFragility:
        frame = train.assign(peak_gust_ms=train[wind.gust])
        curve = FittedFragility.fit(frame)
        eta0 = cls._eta(curve, frame)
        rq = probit_residual_quantiles(train["peak_frac"].to_numpy(dtype=float), eta0)
        return cls(curve, wind, rq)

    @staticmethod
    def _eta(curve: FittedFragility, frame: pd.DataFrame) -> np.ndarray:
        gust = np.maximum(frame["peak_gust_ms"].to_numpy(dtype=float), 1e-6)
        return np.log(gust / curve.median_ms) / curve.beta

    def predict(self, test: pd.DataFrame) -> Prediction:
        eta0 = self._eta(self.curve, test.assign(peak_gust_ms=test[self.wind.gust]))
        point = norm.cdf(eta0)
        return Prediction(
            point=point,
            total=float((customers(test) * point).sum()),
            **_intervals(eta0, self.rq),
            info={"median_ms": self.curve.median_ms, "beta": self.curve.beta},
        )


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, INIT_CLIP, 1.0 - INIT_CLIP)
    return np.log(p / (1.0 - p))


@dataclass
class BoostedResidual:
    """M1 / M1w: a small monotone GBM on F2 (u = 0 at prediction; totals marginalised with F2 tau^2)."""

    base: ProbitCurve
    booster: lgb.Booster
    rq: dict[str, tuple[float, float]]

    @classmethod
    def fit(cls, train: pd.DataFrame, base: ProbitCurve) -> BoostedResidual:
        u = train["storm"].map(base.storm_u).fillna(0.0).to_numpy(dtype=float)
        eta_cond = base.eta0(train) + u
        init = _logit(norm.cdf(eta_cond))
        x = covariates(train, base.wind, base.z, M1_FEATURES)
        c = customers(train)
        model = lgb.LGBMRegressor(
            **M1_PARAMS, monotone_constraints=[M1_MONOTONE.get(n, 0) for n in M1_FEATURES]
        )
        model.fit(x, train["peak_frac"].to_numpy(dtype=float), sample_weight=c / c.mean(), init_score=init)
        out = cls(base, model.booster_, {})
        p0 = out._p0(train)
        out.rq = probit_residual_quantiles(
            train["peak_frac"].to_numpy(dtype=float), norm.ppf(np.clip(p0, PROBIT_CLIP, 1.0 - PROBIT_CLIP))
        )
        return out

    def _p0(self, frame: pd.DataFrame) -> np.ndarray:
        x = covariates(frame, self.base.wind, self.base.z, M1_FEATURES)
        raw = np.asarray(self.booster.predict(x, raw_score=True))
        return 1.0 / (1.0 + np.exp(-(_logit(norm.cdf(self.base.eta0(frame))) + raw)))

    def predict(self, test: pd.DataFrame) -> Prediction:
        p0 = self._p0(test)
        eta0 = norm.ppf(np.clip(p0, PROBIT_CLIP, 1.0 - PROBIT_CLIP))
        c = customers(test)
        tau2 = self.base.tau2
        band: dict[str, Any] = {}
        if tau2 > 0:
            tau = np.sqrt(tau2)
            band = {
                "total_lo80": float((c * norm.cdf(eta0 - Z80 * tau)).sum()),
                "total_hi80": float((c * norm.cdf(eta0 + Z80 * tau)).sum()),
            }
        return Prediction(
            point=p0,
            total=float((c * norm.cdf(eta0 / np.sqrt(1.0 + tau2))).sum()),
            **_intervals(eta0, self.rq),
            **band,
            info={"tau2": round(tau2, 4), "base_dropped": list(self.base.dropped)},
        )


CAL_COLUMNS = ("ln_model", "log1p_coast", "vmax_ms_closest", "speed_kmh_closest")


def _cal_design(frame: pd.DataFrame, gust_col: str) -> np.ndarray:
    return np.column_stack(
        [
            np.log(np.maximum(frame[gust_col].to_numpy(dtype=float), GUST_FLOOR_MS)),
            np.log1p(frame["dist_coast_km"].to_numpy(dtype=float)),
            frame["vmax_ms_closest"].to_numpy(dtype=float),
            frame["speed_kmh_closest"].to_numpy(dtype=float),
        ]
    )


@dataclass(frozen=True)
class WindCalibration:
    coef: np.ndarray
    lo: np.ndarray
    hi: np.ndarray
    n: int

    @staticmethod
    def usable(asos: pd.DataFrame) -> pd.DataFrame:
        obs = pd.to_numeric(asos["obs_peak_gust_ms"], errors="coerce")
        ok = (
            (asos["report_share"] >= CAL_MIN_REPORT_SHARE)
            & (asos["peak_gust_ms"] >= CAL_MIN_MODEL_GUST_MS)
            & obs.notna()
            & (obs > 0)
        )
        return asos[ok].assign(obs_peak_gust_ms=obs[ok])

    @classmethod
    def fit(cls, asos: pd.DataFrame) -> WindCalibration:
        rows = cls.usable(asos)
        x = _cal_design(rows, "peak_gust_ms")
        y = np.log(
            rows["obs_peak_gust_ms"].to_numpy(dtype=float) / rows["peak_gust_ms"].to_numpy(dtype=float)
        )
        design = np.column_stack([np.ones(len(x)), x])
        coef, *_ = np.linalg.lstsq(design, y, rcond=None)
        return cls(coef, x.min(axis=0), x.max(axis=0), len(rows))

    def factor(self, frame: pd.DataFrame) -> np.ndarray:
        x = np.clip(_cal_design(frame, "peak_gust_ms"), self.lo, self.hi)
        return np.clip(np.exp(self.coef[0] + x @ self.coef[1:]), *CAL_FACTOR)


def storm_wind_bias(asos: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Per storm, label-free: geometric mean model / observed peak gust over the usable stations."""
    rows = WindCalibration.usable(asos)
    out = {}
    for storm, g in rows.groupby("storm"):
        ratio = g["peak_gust_ms"].to_numpy(dtype=float) / g["obs_peak_gust_ms"].to_numpy(dtype=float)
        out[str(storm)] = {
            "stations": len(g),
            "geo_mean_model_over_obs": round(float(np.exp(np.log(ratio).mean())), 3),
        }
    return out
