"""Pre-registered variants on the extended storm set: LOSO, nested selection, every variant reported.

Pre-registration: the test plan was fixed before the first run (see docs/models/outage-forecast.md).
- V1 WP-11 model and features; V2 V1 boosted from the fragility prior; V3 V1 + rain residence proxy; V4 both;
  V5 blend w * V1 + (1 - w) * fragility prior, w chosen on the inner storms.
- S: per outer storm, the variant among V1-V4 with the lowest mean inner-LOSO county MAE (inner folds use the
  training storms only), and the interval space (linear or log CQR) whose inner leave-one-storm-out 80%
  coverage is closest to 0.80 on average.
- Round 2: V6 / V7 blend V1 / V3 with the fragility curve fitted on the same training storms; S2 selects
  among V1, V3, V5, V6, V7 the same way. V6 and V7, and S2's pool, were registered after round 1 had shown
  B3 best, so S (pool fixed before any run) and S2 are both reported; S2 equals B3 on most storms (blend
  weight 0). Round 3 (diagnostic, needs the rain table): V8 = V1 + observed rain, V9 its blend, S3
  selection; never on the serving path.
- Baselines: wind threshold (fitted per fold), fragility prior (unfitted), fragility fitted per fold.

Outputs (additive; the WP-11 report and serving model are untouched): the K17 report
`evals/reports/outage_loso_v2.json` (S and S2 side by side), the detail and predictions under
`data/artefacts/models/outage/`, and the candidate serving model `a2v2-excl-helene` (S2 procedure on the
storms that ended before Helene's window; not activated).

Fits on the same storm subset are shared (a model trained without {a, b} serves outer a / inner b and outer
b / inner a), which makes the nested loop affordable; LightGBM runs deterministic, so sharing changes nothing.
"""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm, spearmanr, wilcoxon

from sgw.contracts.eval_report import EvalReport, MetricRow
from sgw.contracts.vocab import EvalSplit, NumberLabel
from sgw.models.hazard.field import EXTRA_FEATURES
from sgw.models.hazard.hurdat2 import EXTENDED_STORMS, STORMS
from sgw.models.outage.backtest import ARTEFACT_DIR, HINDCAST_LABEL, REPO_ROOT, _git_version
from sgw.models.outage.baseline import WindThreshold, fragility_prior
from sgw.models.outage.model import (
    FEATURES,
    INTERVALS,
    OutageModel,
    RawModels,
    apply_offset,
    design,
    fit_raw,
    offsets_from_parts,
    wind_band,
)

VARIANTS: dict[str, dict[str, Any]] = {
    "V1": {"features": FEATURES, "prior_offset": False},
    "V2": {"features": FEATURES, "prior_offset": True},
    "V3": {"features": (*FEATURES, *EXTRA_FEATURES), "prior_offset": False},
    "V4": {"features": (*FEATURES, *EXTRA_FEATURES), "prior_offset": True},
}
RAIN_VARIANTS: dict[str, dict[str, Any]] = {
    "V8": {"features": (*FEATURES, "rain_window_mm", "rain_antecedent_14d_mm"), "prior_offset": False},
}
ROUND1_POOL = ("V1", "V2", "V3", "V4")
ROUND2_POOL = ("V1", "V3", "V5", "V6", "V7")
ROUND3_POOL = ("V1", "V3", "V5", "V6", "V7", "V8", "V9")
BLEND_WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)
SPACES = ("linear", "log")
FRAGILITY_MEDIANS = np.arange(20.0, 81.0, 1.0)
FRAGILITY_BETAS = np.round(np.arange(0.2, 0.81, 0.05), 2)
LARGE_STORM_OUT = 300_000
PRE_2018 = ("colin_2016", "hermine", "julia", "matthew", "irma")
DETAIL_PATH = ARTEFACT_DIR / "loso_v2_detail.json"
PREDICTIONS_PATH = ARTEFACT_DIR / "loso_v2_predictions.csv"
WORKERS = 4
REPORT_V2 = REPO_ROOT / "evals" / "reports" / "outage_loso_v2.json"
SERVING_CANDIDATE = "a2v2-excl-helene"
COMMAND_V2 = "uv run sgw models backtest-outage-v2"
PREFIX_V2 = "outage_loso_v2.hindcast_observed_track"
B1_NAME = "wind_threshold (T, a, b fitted on the training storms of each fold)"
B3_NAME = "fragility_fitted (lognormal on gust; median and beta fitted on the training storms of each fold)"


@dataclass(frozen=True)
class FittedFragility:
    median_ms: float
    beta: float

    @classmethod
    def fit(cls, frame: pd.DataFrame) -> FittedFragility:
        gust = np.maximum(frame["peak_gust_ms"].to_numpy(dtype=float), 1e-6)
        customers = frame["customers_mcc"].to_numpy(dtype=float)
        out = frame["peak_frac"].to_numpy(dtype=float) * customers
        best: tuple[float, FittedFragility] | None = None
        for m in FRAGILITY_MEDIANS:
            z = np.log(gust / m)
            for b in FRAGILITY_BETAS:
                err = float(np.abs(norm.cdf(z / b) * customers - out).sum())
                if best is None or err < best[0]:
                    best = (err, cls(float(m), float(b)))
        assert best is not None
        return best[1]

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        gust = np.maximum(frame["peak_gust_ms"].to_numpy(dtype=float), 1e-6)
        return np.asarray(norm.cdf(np.log(gust / self.median_ms) / self.beta))


def _fit_job(args: tuple[pd.DataFrame, tuple[str, ...], bool]) -> RawModels:
    from sgw.models.outage import model as model_mod

    model_mod.BASE_PARAMS["n_jobs"] = 1
    frame, features, prior_offset = args
    return fit_raw(frame, features, prior_offset)


class FitCache:
    """Raw models keyed by (variant, storms left out)."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.models: dict[tuple[str, frozenset[str]], RawModels] = {}

    def prefit(self, keys: list[tuple[str, frozenset[str]]]) -> None:
        todo = [k for k in dict.fromkeys(keys) if k not in self.models]
        jobs = [
            (
                self.frame[~self.frame["storm"].isin(out)].reset_index(drop=True),
                VARIANTS[v]["features"],
                VARIANTS[v]["prior_offset"],
            )
            for v, out in todo
        ]
        with ProcessPoolExecutor(max_workers=WORKERS) as pool:
            for key, model in zip(todo, pool.map(_fit_job, jobs, chunksize=4), strict=True):
                self.models[key] = model

    def get(self, variant: str, out: frozenset[str]) -> RawModels:
        key = (variant, out)
        if key not in self.models:
            spec = VARIANTS[variant]
            train = self.frame[~self.frame["storm"].isin(out)].reset_index(drop=True)
            self.models[key] = fit_raw(train, spec["features"], spec["prior_offset"])
        return self.models[key]


def _predict(
    cache: FitCache, variant: str, out: frozenset[str], test: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray]:
    return cache.get(variant, out).predict(design(test, VARIANTS[variant]["features"]), test)


def county_mae(frac_pred: np.ndarray, test: pd.DataFrame) -> float:
    customers = test["customers_mcc"].to_numpy(dtype=float)
    return float(np.abs((frac_pred - test["peak_frac"].to_numpy(dtype=float)) * customers).mean())


def _offsets(
    parts: list[tuple[str, np.ndarray, np.ndarray, np.ndarray]], space: str
) -> dict[str, dict[str, float]]:
    return offsets_from_parts(parts, space)


def interval_fit_score(parts: list[tuple[str, np.ndarray, np.ndarray, np.ndarray]], space: str) -> float:
    """Mean |coverage_80 - 0.80| over inner storms, each scored with offsets from the other inner storms."""
    gaps = []
    for i, (_, y, q, band) in enumerate(parts):
        others = parts[:i] + parts[i + 1 :]
        off = _offsets(others, space)["80"]
        lo, hi = apply_offset(q, "80", np.array([off[str(b)] for b in band]), space)
        gaps.append(abs(float(((lo <= y) & (y <= hi)).mean()) - 0.8))
    return float(np.mean(gaps))


def intervals_for(
    q: np.ndarray, test: pd.DataFrame, parts: list[tuple[str, np.ndarray, np.ndarray, np.ndarray]], space: str
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    offsets = _offsets(parts, space)
    band = wind_band(test["peak_gust_ms"].to_numpy())
    out = {
        name: apply_offset(q, name, np.array([offsets[name][str(b)] for b in band]), space)
        for name in INTERVALS
    }
    out["80"] = (np.minimum(out["80"][0], out["50"][0]), np.maximum(out["80"][1], out["50"][1]))
    out["95"] = (np.minimum(out["95"][0], out["80"][0]), np.maximum(out["95"][1], out["80"][1]))
    return out


def score(
    test: pd.DataFrame, frac: np.ndarray, intervals: dict[str, tuple[np.ndarray, np.ndarray]] | None
) -> dict[str, Any]:
    customers = test["customers_mcc"].to_numpy(dtype=float)
    obs = test["peak_frac"].to_numpy(dtype=float) * customers
    pred = frac * customers
    err = np.abs(pred - obs)
    i = int(err.argmax())
    out: dict[str, Any] = {
        "county_mae": round(float(err.mean()), 1),
        "spearman": round(float(spearmanr(pred, obs).statistic), 4) if np.ptp(pred) > 0 else None,
        "predicted_total": round(float(pred.sum())),
        "rel_total_error": round(float(abs(pred.sum() - obs.sum()) / obs.sum()), 4)
        if obs.sum() > 0
        else None,
        "worst_miss": {
            "county": f"{test['name'].iloc[i]}, {test['st'].iloc[i]}",
            "observed": round(float(obs[i])),
            "predicted": round(float(pred[i])),
        },
    }
    if intervals is not None:
        for name in ("80", "95"):
            lo, hi = intervals[name]
            y = test["peak_frac"].to_numpy(dtype=float)
            out[f"coverage_{name}"] = round(float(((lo <= y) & (y <= hi)).mean()), 4)
    return out


_FRAGILITY: dict[frozenset[str], FittedFragility] = {}


def fragility_cache(frame: pd.DataFrame, out: frozenset[str]) -> FittedFragility:
    if out not in _FRAGILITY:
        _FRAGILITY[out] = FittedFragility.fit(frame[~frame["storm"].isin(out)])
    return _FRAGILITY[out]


def run(frame: pd.DataFrame, storms: list[str] | None = None) -> dict[str, Any]:
    """Rounds 1-2 always; round 3 (rain, diagnostic) only when the frame carries the rain features."""
    storms = storms or sorted(frame["storm"].unique())
    rain = "rain_window_mm" in frame.columns
    VARIANTS.pop("V8", None)
    if rain:
        VARIANTS.update(RAIN_VARIANTS)
    cache = FitCache(frame)
    keys = [(v, frozenset({s})) for v in VARIANTS for s in storms]
    keys += [(v, frozenset(p)) for v in VARIANTS for p in combinations(storms, 2)]
    cache.prefit(keys)
    _FRAGILITY.clear()
    rows: list[dict[str, Any]] = []
    preds: list[pd.DataFrame] = []
    for s in storms:
        train = frame[frame["storm"] != s]
        test = frame[frame["storm"] == s].reset_index(drop=True)
        inner_storms = [t for t in storms if t != s]
        inner_tests = {t: frame[frame["storm"] == t].reset_index(drop=True) for t in inner_storms}
        row: dict[str, Any] = {
            "storm": s,
            "counties": len(test),
            "observed_total": round(float((test["peak_frac"] * test["customers_mcc"]).sum())),
        }
        wt, ff = WindThreshold.fit(train), FittedFragility.fit(train)
        row["B1_wind_threshold"] = score(test, wt.predict(test), None)
        row["B2_fragility_prior"] = score(test, fragility_prior(test), None)
        row["B3_fragility_fitted"] = {
            **score(test, ff.predict(test), None),
            "median_ms": ff.median_ms,
            "beta": ff.beta,
        }
        out_pred = pd.DataFrame(
            {"storm": s, "fips": test["fips"], "obs_out": test["peak_frac"] * test["customers_mcc"]}
        )
        inner_mae: dict[str, float] = {}
        variant_q: dict[str, np.ndarray] = {}
        variant_parts: dict[str, list[tuple[str, np.ndarray, np.ndarray, np.ndarray]]] = {}
        variant_mean: dict[str, np.ndarray] = {}
        inner_means: dict[str, dict[str, np.ndarray]] = {}
        for v in VARIANTS:
            parts, maes, means = [], [], {}
            for t in inner_storms:
                it = inner_tests[t]
                m, q = _predict(cache, v, frozenset({s, t}), it)
                means[t] = m
                maes.append(county_mae(m, it))
                parts.append(
                    (t, it["peak_frac"].to_numpy(dtype=float), q, wind_band(it["peak_gust_ms"].to_numpy()))
                )
            inner_mae[v] = float(np.mean(maes))
            mean, q = _predict(cache, v, frozenset({s}), test)
            variant_mean[v], variant_q[v], variant_parts[v], inner_means[v] = mean, q, parts, means
            space = min(SPACES, key=lambda sp: interval_fit_score(parts, sp))
            row[v] = {
                **score(test, mean, intervals_for(q, test, parts, "linear")),
                "coverage_log_space": score(test, mean, intervals_for(q, test, parts, "log"))["coverage_80"],
                "inner_county_mae": round(inner_mae[v], 1),
                "interval_space_selected": space,
            }
            out_pred[f"{v}_out"] = mean * test["customers_mcc"].to_numpy()
        blend_mae = {
            w: float(
                np.mean(
                    [
                        county_mae(
                            w * inner_means["V1"][t] + (1 - w) * fragility_prior(inner_tests[t]),
                            inner_tests[t],
                        )
                        for t in inner_storms
                    ]
                )
            )
            for w in BLEND_WEIGHTS
        }
        w = min(BLEND_WEIGHTS, key=lambda k: (blend_mae[k], -k))
        blend = w * variant_mean["V1"] + (1 - w) * fragility_prior(test)
        row["V5"] = {
            **score(test, blend, intervals_for(variant_q["V1"], test, variant_parts["V1"], "linear")),
            "weight_model": w,
            "inner_county_mae": round(blend_mae[w], 1),
            "note": "intervals are V1's",
        }
        out_pred["V5_out"] = blend * test["customers_mcc"].to_numpy()
        inner_mae["V5"] = blend_mae[w]
        ff_inner = {
            t: fragility_cache(frame, frozenset({s, t})).predict(inner_tests[t]) for t in inner_storms
        }
        for name, base in (("V6", "V1"), ("V7", "V3")):
            wmaes = {
                k: float(
                    np.mean(
                        [
                            county_mae(k * inner_means[base][t] + (1 - k) * ff_inner[t], inner_tests[t])
                            for t in inner_storms
                        ]
                    )
                )
                for k in BLEND_WEIGHTS
            }
            wk = min(BLEND_WEIGHTS, key=lambda k: (wmaes[k], -k))
            pred = wk * variant_mean[base] + (1 - wk) * ff.predict(test)
            sp = min(SPACES, key=lambda x: interval_fit_score(variant_parts[base], x))
            row[name] = {
                **score(test, pred, intervals_for(variant_q[base], test, variant_parts[base], sp)),
                "weight_model": wk,
                "inner_county_mae": round(wmaes[wk], 1),
                "interval_space": sp,
                "note": f"intervals are {base}'s",
            }
            inner_mae[name] = wmaes[wk]
            variant_mean[name] = pred
            out_pred[f"{name}_out"] = pred * test["customers_mcc"].to_numpy()
        variant_mean["V5"] = blend
        if rain:
            maes8 = {
                k: float(
                    np.mean(
                        [
                            county_mae(k * inner_means["V8"][t] + (1 - k) * ff_inner[t], inner_tests[t])
                            for t in inner_storms
                        ]
                    )
                )
                for k in BLEND_WEIGHTS
            }
            w8 = min(BLEND_WEIGHTS, key=lambda k: (maes8[k], -k))
            pred9 = w8 * variant_mean["V8"] + (1 - w8) * ff.predict(test)
            sp9 = min(SPACES, key=lambda x: interval_fit_score(variant_parts["V8"], x))
            row["V9"] = {
                **score(test, pred9, intervals_for(variant_q["V8"], test, variant_parts["V8"], sp9)),
                "weight_model": w8,
                "inner_county_mae": round(maes8[w8], 1),
                "note": "intervals are V8's",
            }
            inner_mae["V9"], variant_mean["V9"] = maes8[w8], pred9
            out_pred["V9_out"] = pred9 * test["customers_mcc"].to_numpy()
            chosen3 = min(ROUND3_POOL, key=lambda k: (inner_mae[k], k))
            base3 = {"V5": "V1", "V6": "V1", "V7": "V3", "V9": "V8"}.get(chosen3, chosen3)
            sp3 = min(SPACES, key=lambda x: interval_fit_score(variant_parts[base3], x))
            int3 = intervals_for(variant_q[base3], test, variant_parts[base3], sp3)
            row["S3"] = {
                **score(test, variant_mean[chosen3], int3),
                "variant": chosen3,
                "interval_space": sp3,
            }
            out_pred["S3_out"] = variant_mean[chosen3] * test["customers_mcc"].to_numpy()
        pool2 = ROUND2_POOL
        chosen2 = min(pool2, key=lambda k: (inner_mae[k], k))
        base2 = {"V5": "V1", "V6": "V1", "V7": "V3"}.get(chosen2, chosen2)
        sp2 = min(SPACES, key=lambda x: interval_fit_score(variant_parts[base2], x))
        int2 = intervals_for(variant_q[base2], test, variant_parts[base2], sp2)
        row["S2"] = {**score(test, variant_mean[chosen2], int2), "variant": chosen2, "interval_space": sp2}
        out_pred["S2_out"] = variant_mean[chosen2] * test["customers_mcc"].to_numpy()
        out_pred["S2_lo80_out"] = int2["80"][0] * test["customers_mcc"].to_numpy()
        out_pred["S2_hi80_out"] = int2["80"][1] * test["customers_mcc"].to_numpy()
        chosen = min(ROUND1_POOL, key=lambda k: (inner_mae[k], k))
        space = min(SPACES, key=lambda sp: interval_fit_score(variant_parts[chosen], sp))
        sel_int = intervals_for(variant_q[chosen], test, variant_parts[chosen], space)
        row["S"] = {**score(test, variant_mean[chosen], sel_int), "variant": chosen, "interval_space": space}
        out_pred["S_out"] = variant_mean[chosen] * test["customers_mcc"].to_numpy()
        out_pred["S_lo80_out"] = sel_int["80"][0] * test["customers_mcc"].to_numpy()
        out_pred["S_hi80_out"] = sel_int["80"][1] * test["customers_mcc"].to_numpy()
        out_pred["B1_out"] = wt.predict(test) * test["customers_mcc"].to_numpy()
        out_pred["B3_out"] = ff.predict(test) * test["customers_mcc"].to_numpy()
        rows.append(row)
        preds.append(out_pred)
    return {"storms": rows, "predictions": pd.concat(preds, ignore_index=True)}


def versus(rows: list[dict[str, Any]], a: str, b: str) -> dict[str, Any]:
    """County MAE of a against b per storm: equal, better, worse; Wilcoxon test on the untied log ratios."""
    ratios = np.array([r[a]["county_mae"] / r[b]["county_mae"] for r in rows])
    same = np.isclose(ratios, 1.0, rtol=1e-9)
    untied = np.log(ratios[~same])
    p = float(wilcoxon(untied).pvalue) if len(untied) >= 2 else None
    return {
        "same": int(same.sum()),
        "better": int((ratios < 1.0)[~same].sum()),
        "worse": int((ratios > 1.0)[~same].sum()),
        "wilcoxon_p_untied": round(p, 4) if p is not None else None,
    }


def bias_and_rank(rows: list[dict[str, Any]], v: str) -> dict[str, Any]:
    """Signed bias of the storm total and county ranking against the wind threshold."""
    pred = sum(r[v]["predicted_total"] for r in rows)
    obs = sum(r["observed_total"] for r in rows)
    rho = [r[v]["spearman"] if r[v]["spearman"] is not None else 0.0 for r in rows]
    rho_b1 = [r["B1_wind_threshold"]["spearman"] or 0.0 for r in rows]
    return {
        "storms_under_predicted_total": sum(r[v]["predicted_total"] < r["observed_total"] for r in rows),
        "pooled_predicted_over_observed": round(pred / obs, 4) if obs else None,
        "storms_spearman_better_than_B1": sum(a > b for a, b in zip(rho, rho_b1, strict=True)),
        "median_spearman": round(float(np.median(rho)), 4),
    }


def large_storms(rows: list[dict[str, Any]]) -> list[str]:
    """Descriptive subset (threshold chosen after the results were seen; never used for selection)."""
    return [r["storm"] for r in rows if r["observed_total"] >= LARGE_STORM_OUT]


def summarise(rows: list[dict[str, Any]], storms: list[str] | None = None) -> dict[str, Any]:
    keep = [r for r in rows if storms is None or r["storm"] in storms]
    out: dict[str, Any] = {"storms": len(keep)}
    variants = ["V1", "V2", "V3", "V4", "V5", "V6", "V7", "S", "S2"]
    variants += [v for v in ("V8", "V9", "S3") if keep and v in keep[0]]
    for v in variants:
        d: dict[str, Any] = {}
        for b in ("B1_wind_threshold", "B2_fragility_prior", "B3_fragility_fitted"):
            d[f"beats_{b}_county_mae"] = sum(r[v]["county_mae"] < r[b]["county_mae"] for r in keep)
            d[f"beats_{b}_total"] = sum(
                (r[v]["rel_total_error"] or 0) < (r[b]["rel_total_error"] or 0) for r in keep
            )
        d["median_mae_ratio_vs_B1"] = round(
            float(np.median([r[v]["county_mae"] / r["B1_wind_threshold"]["county_mae"] for r in keep])), 4
        )
        d["median_rel_total_error"] = round(float(np.median([r[v]["rel_total_error"] for r in keep])), 4)
        d["mean_coverage_80"] = round(float(np.mean([r[v]["coverage_80"] for r in keep])), 4)
        d.update(bias_and_rank(keep, v))
        out[v] = d
    out["S2_vs_B3_county_mae"] = versus(keep, "S2", "B3_fragility_fitted")
    for b in ("B1_wind_threshold", "B2_fragility_prior", "B3_fragility_fitted"):
        out[b] = {
            "median_rel_total_error": round(float(np.median([r[b]["rel_total_error"] for r in keep])), 4),
            **bias_and_rank(keep, b),
        }
        if b != "B1_wind_threshold":
            out[b]["beats_B1_wind_threshold_county_mae"] = sum(
                r[b]["county_mae"] < r["B1_wind_threshold"]["county_mae"] for r in keep
            )
            out[b]["median_mae_ratio_vs_B1"] = round(
                float(np.median([r[b]["county_mae"] / r["B1_wind_threshold"]["county_mae"] for r in keep])), 4
            )
    return out


def select_and_fit(train: pd.DataFrame) -> tuple[OutageModel, dict[str, Any]]:
    """The S2 procedure on one training set: inner LOSO picks the variant, blend weight and interval space."""
    storms = sorted(train["storm"].unique())
    train = train.reset_index(drop=True)
    cache = FitCache(train)
    bases = ("V1", "V3")
    cache.prefit([(v, frozenset({t})) for v in bases for t in storms])
    tests = {t: train[train["storm"] == t].reset_index(drop=True) for t in storms}
    ff_inner = {t: FittedFragility.fit(train[train["storm"] != t]).predict(tests[t]) for t in storms}
    prior = {t: fragility_prior(tests[t]) for t in storms}
    means: dict[str, dict[str, np.ndarray]] = {}
    parts: dict[str, list[tuple[str, np.ndarray, np.ndarray, np.ndarray]]] = {}
    for v in bases:
        means[v], parts[v] = {}, []
        for t in storms:
            m, q = _predict(cache, v, frozenset({t}), tests[t])
            means[v][t] = m
            y = tests[t]["peak_frac"].to_numpy(dtype=float)
            parts[v].append((t, y, q, wind_band(tests[t]["peak_gust_ms"].to_numpy())))

    def inner(v: str, w: float, other: dict[str, np.ndarray]) -> float:
        return float(np.mean([county_mae(w * means[v][t] + (1 - w) * other[t], tests[t]) for t in storms]))

    options: dict[str, tuple[float, str, float, str]] = {}
    for name, base, other, curve in (
        ("V1", "V1", None, ""),
        ("V3", "V3", None, ""),
        ("V5", "V1", prior, "prior"),
        ("V6", "V1", ff_inner, "fitted"),
        ("V7", "V3", ff_inner, "fitted"),
    ):
        if other is None:
            options[name] = (inner(base, 1.0, ff_inner), base, 1.0, curve)
        else:
            w = min(BLEND_WEIGHTS, key=lambda k: (inner(base, k, other), -k))
            options[name] = (inner(base, w, other), base, w, curve)
    chosen = min(ROUND2_POOL, key=lambda k: (options[k][0], k))
    mae, base, w, curve = options[chosen]
    space = min(SPACES, key=lambda x: interval_fit_score(parts[base], x))
    spec = VARIANTS[base]

    def fitter(frame: pd.DataFrame) -> RawModels:
        return cache.get(base, frozenset(storms) - set(frame["storm"].unique()))

    model = OutageModel.fit(train, spec["features"], interval_space=space, fitter=fitter)
    blend = None
    if w < 1.0:
        if curve == "fitted":
            ff = FittedFragility.fit(train)
            blend = {"weight": w, "median_ms": ff.median_ms, "beta": ff.beta}
        else:
            from sgw.common import numbers as numbers_mod
            from sgw.models.outage.baseline import FRAGILITY_BETA

            blend = {
                "weight": w,
                "median_ms": float(numbers_mod.value("fragility_median_gust_ms")),
                "beta": FRAGILITY_BETA,
            }
    model.blend = blend
    info = {
        "variant": chosen,
        "base": base,
        "weight_model": w,
        "interval_space": space,
        "inner_county_mae": {k: round(v[0], 1) for k, v in options.items()},
        "trained_on": storms,
    }
    return model, info


def serving_storms(frame: pd.DataFrame, replayed: str = "helene") -> list[str]:
    """Storms whose window ended before the replayed storm's window began (what an operator knew then)."""
    starts = pd.to_datetime(frame.groupby("storm")["window_start_utc"].first())
    ends = pd.to_datetime(frame.groupby("storm")["window_end_utc"].first())
    return sorted(s for s in ends.index if s != replayed and ends[s] < starts[replayed])


def _row(metric: str, value: float, unit: str, n: int, baseline: float, lower: bool, name: str) -> MetricRow:
    threshold = baseline
    return MetricRow(
        metric=metric,
        value=round(float(value), 4),
        unit=unit,
        n=n,
        split=EvalSplit.REAL_LOSO,
        label=NumberLabel.C,
        baseline_name=name,
        baseline_value=round(float(baseline), 4),
        threshold=round(float(threshold), 4),
        direction="lower_is_better" if lower else "higher_is_better",
        passed=value <= threshold if lower else value >= threshold,
    )


def k17_rows(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    large: dict[str, Any] | None = None,
    refit: dict[str, Any] | None = None,
) -> list[MetricRow]:
    """Headline S2 per storm: county MAE, Spearman, coverage, total error (vs B1 and B3), worst miss."""
    out: list[MetricRow] = []
    for r in rows:
        m, b1, b3, n = r["S2"], r["B1_wind_threshold"], r["B3_fragility_fitted"], r["counties"]
        key = f"{PREFIX_V2}.{r['storm']}"
        out.append(
            _row(f"{key}.county_mae", m["county_mae"], "customers", n, b1["county_mae"], True, B1_NAME)
        )
        out.append(
            _row(
                f"{key}.county_mae_vs_fragility_fitted",
                m["county_mae"],
                "customers",
                n,
                b3["county_mae"],
                True,
                B3_NAME,
            )
        )
        out.append(
            _row(
                f"{key}.spearman",
                m["spearman"] or 0.0,
                "rank correlation",
                n,
                b1["spearman"] or 0.0,
                False,
                B1_NAME,
            )
        )
        for level in ("80", "95"):
            out.append(
                _row(
                    f"{key}.coverage_{level}",
                    m[f"coverage_{level}"],
                    "share of counties",
                    n,
                    int(level) / 100,
                    False,
                    f"nominal coverage of the {level}% storm-grouped CQR interval",
                )
            )
        out.append(
            _row(
                f"{key}.rel_total_error",
                m["rel_total_error"],
                "ratio",
                n,
                b1["rel_total_error"],
                True,
                B1_NAME,
            )
        )
        out.append(
            _row(
                f"{key}.rel_total_error_vs_fragility_fitted",
                m["rel_total_error"],
                "ratio",
                n,
                b3["rel_total_error"],
                True,
                B3_NAME,
            )
        )
        worst = abs(m["worst_miss"]["observed"] - m["worst_miss"]["predicted"])
        worst_b = abs(b1["worst_miss"]["observed"] - b1["worst_miss"]["predicted"])
        out.append(_row(f"{key}.worst_miss", worst, "customers", n, worst_b, True, B1_NAME))
    s2, total = summary["S2"], summary["storms"]
    out.append(
        _row(
            f"{PREFIX_V2}.storms_s2_beats_wind_threshold_county_mae",
            s2["beats_B1_wind_threshold_county_mae"],
            f"storms of {total} (strict)",
            total,
            total / 2,
            False,
            B1_NAME,
        )
    )
    out.append(
        _row(
            f"{PREFIX_V2}.storms_s2_beats_fragility_fitted_county_mae",
            s2["beats_B3_fragility_fitted_county_mae"],
            f"storms of {total} (strict)",
            total,
            total / 2,
            False,
            B3_NAME,
        )
    )
    out.append(
        _row(
            f"{PREFIX_V2}.storms_s2_under_predicted_total",
            s2["storms_under_predicted_total"],
            f"storms of {total} (forecast total below observed)",
            total,
            total / 2,
            True,
            "half of the storms (an unbiased forecast)",
        )
    )
    out.append(
        _row(
            f"{PREFIX_V2}.s2_share_of_observed_outages_forecast",
            s2["pooled_predicted_over_observed"],
            "ratio (sum of forecast totals / sum of observed totals, all storms)",
            total,
            1.0,
            False,
            "1.0 (unbiased); wind threshold pooled "
            f"{summary['B1_wind_threshold']['pooled_predicted_over_observed']}",
        )
    )
    out.append(
        _row(
            f"{PREFIX_V2}.storms_s2_spearman_better_than_wind_threshold",
            s2["storms_spearman_better_than_B1"],
            f"storms of {total} (strict)",
            total,
            total / 2,
            False,
            B1_NAME,
        )
    )
    out.append(
        _row(
            f"{PREFIX_V2}.s2_median_spearman",
            s2["median_spearman"],
            "rank correlation",
            total,
            summary["B1_wind_threshold"]["median_spearman"],
            False,
            B1_NAME,
        )
    )
    if large is not None:
        lg, n_lg = large["S2"], large["storms"]
        out.append(
            _row(
                f"{PREFIX_V2}.large_storms.storms_s2_beats_wind_threshold_county_mae",
                lg["beats_B1_wind_threshold_county_mae"],
                f"storms of {n_lg} with >= {LARGE_STORM_OUT:,} observed (descriptive, set post hoc)",
                n_lg,
                n_lg / 2,
                False,
                B1_NAME,
            )
        )
        out.append(
            _row(
                f"{PREFIX_V2}.large_storms.s2_median_county_mae_ratio_vs_wind_threshold",
                lg["median_mae_ratio_vs_B1"],
                "ratio (descriptive subset)",
                n_lg,
                1.0,
                True,
                B1_NAME,
            )
        )
    if refit is not None:
        n_rf = refit["storms"]
        for label, block in (
            ("s2", refit["S2"]),
            ("pre_registered_s", refit["S"]),
            ("fragility_fitted", refit["B3_fragility_fitted"]),
        ):
            key = f"{PREFIX_V2}.sensitivity_2018_on_refit.{label}"
            out.append(
                _row(
                    f"{key}.storms_beats_wind_threshold_county_mae",
                    block["beats_B1_wind_threshold_county_mae"],
                    f"storms of {n_rf} (2016-2017 dropped from training and testing)",
                    n_rf,
                    n_rf / 2,
                    False,
                    B1_NAME,
                )
            )
            out.append(
                _row(
                    f"{key}.median_county_mae_ratio_vs_wind_threshold",
                    block["median_mae_ratio_vs_B1"],
                    "ratio",
                    n_rf,
                    1.0,
                    True,
                    B1_NAME,
                )
            )
    vs = summary["S2_vs_B3_county_mae"]
    for name, value in (("same", vs["same"]), ("worse", vs["worse"])):
        out.append(
            _row(
                f"{PREFIX_V2}.storms_s2_{name}_as_fragility_fitted_county_mae",
                value,
                f"storms of {total} (S2 = fitted fragility curve when its blend weight is 0)",
                total,
                total / 2,
                name == "worse",
                B3_NAME,
            )
        )
    out.append(
        _row(
            f"{PREFIX_V2}.s2_vs_fragility_fitted_wilcoxon_p",
            vs["wilcoxon_p_untied"] if vs["wilcoxon_p_untied"] is not None else 1.0,
            "p-value (two-sided, untied log MAE ratios)",
            vs["better"] + vs["worse"],
            0.05,
            True,
            B3_NAME,
        )
    )
    s = summary["S"]
    pre = f"{PREFIX_V2}.pre_registered_s"
    out.append(
        _row(
            f"{pre}.storms_beats_wind_threshold_county_mae",
            s["beats_B1_wind_threshold_county_mae"],
            f"storms of {total} (strict)",
            total,
            total / 2,
            False,
            B1_NAME,
        )
    )
    out.append(
        _row(
            f"{pre}.median_county_mae_ratio_vs_wind_threshold",
            s["median_mae_ratio_vs_B1"],
            "ratio",
            total,
            1.0,
            True,
            B1_NAME,
        )
    )
    out.append(
        _row(
            f"{PREFIX_V2}.s2_median_county_mae_ratio_vs_wind_threshold",
            s2["median_mae_ratio_vs_B1"],
            "ratio",
            total,
            1.0,
            True,
            B1_NAME,
        )
    )
    for r in rows:
        m, b1, n = r["S"], r["B1_wind_threshold"], r["counties"]
        key = f"{pre}.{r['storm']}"
        out.append(
            _row(f"{key}.county_mae", m["county_mae"], "customers", n, b1["county_mae"], True, B1_NAME)
        )
        out.append(
            _row(
                f"{key}.rel_total_error",
                m["rel_total_error"],
                "ratio",
                n,
                b1["rel_total_error"],
                True,
                B1_NAME,
            )
        )
        out.append(
            _row(
                f"{key}.coverage_80",
                m["coverage_80"],
                "share of counties",
                n,
                0.8,
                False,
                "nominal coverage of the 80% storm-grouped CQR interval",
            )
        )
    return out


def run_v2(write: bool = True) -> dict[str, Any]:
    from sgw.models.outage.dataset import extended_frame, frame_sha256
    from sgw.models.outage.rain import RAIN_CSV

    rain = RAIN_CSV.is_file()
    frame = extended_frame(rain=rain)
    result = run(frame)
    rows = result["storms"]
    wind_frame = extended_frame()
    refit_rows = run(wind_frame[~wind_frame["storm"].isin(PRE_2018)].reset_index(drop=True))["storms"]
    refit = summarise(refit_rows)
    known = serving_storms(wind_frame)
    serving, info = select_and_fit(wind_frame[wind_frame["storm"].isin(known)])
    helene = wind_frame[wind_frame["storm"] == "helene"].reset_index(drop=True)
    fc = serving.predict(helene)
    info["helene"] = score(helene, fc.mean, fc.intervals)
    data_sha = frame_sha256(wind_frame)
    serving.meta = {"name": SERVING_CANDIDATE, "data_sha256": data_sha, "version": "2.0-candidate"}
    summary = summarise(rows)
    report = EvalReport(
        name="outage_loso_v2",
        created_at=pd.Timestamp.now(tz="UTC").to_pydatetime().replace(microsecond=0),
        code_version=_git_version(),
        llm_mode="replay",
        command=COMMAND_V2,
        metrics=k17_rows(rows, summary, summarise(rows, large_storms(rows)), refit),
    )
    detail = {
        "name": "outage_loso_v2_detail",
        "label": "C: EAGLE-I (CC BY 4.0) and HURDAT2; 24 storms, storm-grouped LOSO; " + HINDCAST_LABEL,
        "headline": (
            "two results: S (pool V1-V4 fixed before any run: the gradient-boosted model) and S2 "
            "(pool V1, V3, V5-V7; V6, V7 and the pool registered after round 1 had shown the fitted "
            "fragility curve B3 best). S2 equals B3 on most storms (blend weight 0), so S2's gain over "
            "the wind threshold is the fitted curve's, not the gradient-boosted model's"
        ),
        "data_sha256": data_sha,
        "storms_all": [s.name for s in EXTENDED_STORMS],
        "summary_all": summary,
        "summary_wp11_storms": summarise(rows, [s.name for s in STORMS]),
        "summary_2018_on_test_folds_only": summarise(
            rows, [r["storm"] for r in rows if r["storm"] not in PRE_2018]
        ),
        "summary_large_storms_descriptive": summarise(rows, large_storms(rows)),
        "sensitivity_2018_on_refit": {
            "note": "2016-2017 storms dropped from training and testing (sparser EAGLE-I reporting)",
            "summary": refit,
            "storms": [
                {k: r[k] for k in ("storm", "S", "S2", "B1_wind_threshold", "B3_fragility_fitted")}
                for r in refit_rows
            ],
        },
        "serving_candidate": info,
        "rain_round": "included (diagnostic only)" if rain else "not run (no rain table)",
        "storms": rows,
    }
    if write:
        REPORT_V2.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        ARTEFACT_DIR.mkdir(parents=True, exist_ok=True)
        DETAIL_PATH.write_text(json.dumps(detail, indent=2) + "\n", encoding="utf-8")
        result["predictions"].round(1).to_csv(PREDICTIONS_PATH, index=False, lineterminator="\n")
        serving.save(ARTEFACT_DIR / SERVING_CANDIDATE)
    return {"report": report, "detail": detail, "serving": serving}


def main() -> None:
    detail = run_v2(write=True)["detail"]
    keys = ("summary_all", "summary_wp11_storms", "summary_2018_on", "serving_candidate")
    print(json.dumps({k: detail[k] for k in keys}, indent=1))


if __name__ == "__main__":
    main()
