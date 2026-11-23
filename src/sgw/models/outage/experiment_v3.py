"""Can a statistical curve or a small ML model beat the fitted fragility curve? Pre-registered LOSO.

Pre-registration: `docs/models/outage-v3-preregistration.md` (commit 1368966, before any outcome run).
Methods (`sgw.models.outage.glm`): baselines B1 wind threshold, B3 fragility by L1 (headline comparator), B3m
fragility by binomial likelihood, B3w B3 on the ASOS-calibrated wind; variants F1 composite fragility, F2
generalised GLM, M1 boosted residual on F2, and their w versions; S5 nested selection over
{B3, B3m, F1, F2, M1, F1w, F2w, M1w} by the mean inner-LOSO [ln(county MAE) + |ln(P/O)|].

Every fit (including the wind calibration, z-scoring and the GLM's tau^2) uses only the storms of its
training set; a fit on the storms without {s, t} serves outer s / inner t and outer t / inner s.
Outputs (additive; WP-11 and WP-11v2 artefacts untouched): `evals/reports/outage_loso_v3.json` (K17),
`data/artefacts/models/outage/loso_v3_detail.json` and `loso_v3_predictions.csv`.
"""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, wilcoxon

from sgw.contracts.eval_report import EvalReport, MetricRow
from sgw.models.hazard.series import GustSeries, gust_series
from sgw.models.outage.backtest import ARTEFACT_DIR, HINDCAST_LABEL, REPO_ROOT, _git_version
from sgw.models.outage.baseline import WindThreshold
from sgw.models.outage.experiment import PRE_2018, _row, serving_storms
from sgw.models.outage.glm import (
    CAL_WIND,
    F1_COVARIATES,
    F2_COVARIATES,
    MODEL_WIND,
    BoostedResidual,
    GridFragility,
    Prediction,
    ProbitCurve,
    WindCalibration,
    customers,
    storm_wind_bias,
)

POOL = ("B3", "B3m", "F1", "F2", "M1", "F1w", "F2w", "M1w")
METHODS = ("B1", "B3", "B3m", "B3w", "F1", "F2", "M1", "F1w", "F2w", "M1w")
COMPARATORS = ("B1", "B3", "B3m", "B3w", "F2", "F2w")
LARGE_8 = ("dorian", "helene", "ian", "idalia", "irma", "matthew", "michael", "zeta")
CONTRASTS = {"C1": ("F2", "B3"), "C2": ("M1", "F2"), "C3": ("F2w", "F2")}
ML_ARMS = {"M1": ("F2", "B3"), "M1w": ("F2w", "B3w")}
CURVE_ARMS = {"F2": "B3", "F2w": "B3w"}
WP12_BAND = (0.453, 2.209)
WORKERS = 4
REPORT_V3 = REPO_ROOT / "evals" / "reports" / "outage_loso_v3.json"
DETAIL_V3 = ARTEFACT_DIR / "loso_v3_detail.json"
PREDICTIONS_V3 = ARTEFACT_DIR / "loso_v3_predictions.csv"
COMMAND_V3 = "uv run python -m sgw.models.outage.experiment_v3"
PREFIX_V3 = "outage_loso_v3.hindcast_observed_track"
B3_NAME = "fragility_fitted B3 (lognormal on gust, median and beta by customer-weighted L1, per fold)"


def v3_frame() -> pd.DataFrame:
    """24-storm frame with rain, static county covariates and the L2 / gap label columns."""
    from sgw.models.outage.county_static import load_static
    from sgw.models.outage.dataset import extended_frame
    from sgw.models.outage.labels_v3 import load_labels_v3
    from sgw.models.outage.rain import ANTE30_CSV

    frame = extended_frame(rain=True)
    static = load_static()[["fips", "customer_density", "dist_coast_km", "ep_mobile", "land_km2"]]
    frame = frame.merge(static, on="fips", how="left", validate="many_to_one")
    frame = frame.merge(load_labels_v3(), on=["storm", "fips"], how="left", validate="one_to_one")
    if ANTE30_CSV.is_file():
        ante = pd.read_csv(ANTE30_CSV, dtype={"fips": str})
        frame = frame.merge(ante, on=["storm", "fips"], how="left", validate="one_to_one")
    if frame[["customer_density", "peak_frac_l2", "gap_share"]].isna().any().any():
        raise ValueError("v3 frame has missing covariates or labels")
    return frame.sort_values(["storm", "fips"]).reset_index(drop=True)


def storm_series(frame: pd.DataFrame) -> dict[str, tuple[GustSeries, dict[str, int]]]:
    """Per storm: the county gust series and the column of each county (fips) in it."""
    from sgw.models.hazard.hurdat2 import load_track
    from sgw.models.outage.dataset import county_points

    points, _ = county_points()
    col = {f: i for i, f in enumerate(points.ids)}
    return {s: (gust_series(load_track(s), points), col) for s in sorted(frame["storm"].unique())}


def with_calibration(
    frame: pd.DataFrame, cal: WindCalibration, series: dict[str, tuple[GustSeries, dict[str, int]]]
) -> pd.DataFrame:
    factor = cal.factor(frame)
    h20 = np.zeros(len(frame))
    for s, idx in frame.groupby("storm").indices.items():
        ser, col = series[s]
        cols = np.array([col[f] for f in frame["fips"].to_numpy()[idx]])
        full = np.ones(ser.gust.shape[1])
        full[cols] = factor[idx]
        h20[idx] = ser.hours_above(20.0, full)[cols]
    return frame.assign(
        wind_factor=factor,
        peak_gust_cal_ms=factor * frame["peak_gust_ms"].to_numpy(),
        hours_gust_cal_ge_20=h20,
    )


def fit_predict(
    train: pd.DataFrame, tests: dict[str, pd.DataFrame], methods: tuple[str, ...]
) -> dict[str, dict[str, Prediction]]:
    fitted: dict[str, Any] = {}
    if "B1" in methods:
        fitted["B1"] = WindThreshold.fit(train)
    for name, wind in (("B3", MODEL_WIND), ("B3w", CAL_WIND)):
        if name in methods:
            fitted[name] = GridFragility.fit(train, wind)
    if "B3m" in methods:
        fitted["B3m"] = ProbitCurve.fit(train, F1_COVARIATES, MODEL_WIND, storm_effect=False)
    for suffix, wind in (("", MODEL_WIND), ("w", CAL_WIND)):
        if f"F1{suffix}" in methods:
            fitted[f"F1{suffix}"] = ProbitCurve.fit(train, F1_COVARIATES, wind)
        if f"F2{suffix}" in methods or f"M1{suffix}" in methods:
            fitted[f"F2{suffix}"] = ProbitCurve.fit(train, F2_COVARIATES, wind)
        if f"M1{suffix}" in methods:
            fitted[f"M1{suffix}"] = BoostedResidual.fit(train, fitted[f"F2{suffix}"])
    out: dict[str, dict[str, Prediction]] = {}
    for s, test in tests.items():
        out[s] = {}
        for m in methods:
            if m == "B1":
                point = fitted["B1"].predict(test)
                out[s][m] = Prediction(point=point, total=float((customers(test) * point).sum()))
            else:
                out[s][m] = fitted[m].predict(test)
    return out


_STATE: dict[str, Any] = {}


def _init(frame: pd.DataFrame, asos: pd.DataFrame, series: dict[str, Any], methods: tuple[str, ...]) -> None:
    _STATE.update(frame=frame, asos=asos, series=series, methods=methods)


def run_out(out: frozenset[str]) -> tuple[frozenset[str], dict[str, dict[str, Prediction]], dict[str, Any]]:
    """Fit every method on the storms not in `out` and predict each storm of `out`."""
    frame, asos = _STATE["frame"], _STATE["asos"]
    cal = WindCalibration.fit(asos[~asos["storm"].isin(out)])
    full = with_calibration(frame, cal, _STATE["series"])
    train = full[~full["storm"].isin(out)].reset_index(drop=True)
    tests = {s: full[full["storm"] == s].reset_index(drop=True) for s in out}
    info = {"calibration_coef": [round(float(c), 4) for c in cal.coef], "calibration_pairs": cal.n}
    return out, fit_predict(train, tests, _STATE["methods"]), info


def score(test: pd.DataFrame, p: Prediction) -> dict[str, Any]:
    c = customers(test)
    y = test["peak_frac"].to_numpy(dtype=float)
    obs, pred = y * c, p.point * c
    err = np.abs(pred - obs)
    i = int(err.argmax())
    o_tot = float(obs.sum())
    ln_po = float(np.log(max(p.total, 1.0) / o_tot))
    row: dict[str, Any] = {
        "county_mae": round(float(err.mean()), 1),
        "predicted_total": round(p.total),
        "ln_p_over_o": round(ln_po, 4),
        "abs_ln_p_over_o": round(abs(ln_po), 4),
        "rel_total_error": round(abs(p.total - o_tot) / o_tot, 4),
        "spearman": round(float(spearmanr(pred, obs).statistic), 4) if np.ptp(pred) > 0 else None,
        "worst_miss": {
            "county": f"{test['name'].iloc[i]}, {test['st'].iloc[i]}",
            "observed": round(float(obs[i])),
            "predicted": round(float(pred[i])),
        },
    }
    if p.lo80 is not None and p.hi80 is not None and p.lo95 is not None and p.hi95 is not None:
        row["coverage_80"] = round(float(((p.lo80 <= y) & (y <= p.hi80)).mean()), 4)
        row["coverage_95"] = round(float(((p.lo95 <= y) & (y <= p.hi95)).mean()), 4)
        row["point_outside_own_80"] = int(((p.point < p.lo80) | (p.point > p.hi80)).sum())
    if p.total_lo80 is not None and p.total_hi80 is not None:
        row["total_lo80"], row["total_hi80"] = round(p.total_lo80), round(p.total_hi80)
        row["total_hit_80"] = int(p.total_lo80 <= o_tot <= p.total_hi80)
    if p.info:
        row["fit"] = p.info
    return row


def inner_loss(test: pd.DataFrame, p: Prediction) -> float:
    c = customers(test)
    obs = test["peak_frac"].to_numpy(dtype=float) * c
    mae = float(np.abs(p.point * c - obs).mean())
    return float(np.log(max(mae, 1e-9)) + abs(np.log(max(p.total, 1.0) / obs.sum())))


def run(
    frame: pd.DataFrame,
    asos: pd.DataFrame,
    series: dict[str, Any],
    methods: tuple[str, ...] = METHODS,
    nested: bool = True,
) -> dict[str, Any]:
    storms = sorted(frame["storm"].unique())
    outs = [frozenset({s}) for s in storms]
    if nested:
        outs += [frozenset(p) for p in combinations(storms, 2)]
    with ProcessPoolExecutor(WORKERS, initializer=_init, initargs=(frame, asos, series, methods)) as pool:
        results = {o: (preds, info) for o, preds, info in pool.map(run_out, outs, chunksize=4)}
    tests = {s: frame[frame["storm"] == s].reset_index(drop=True) for s in storms}
    rows, preds = [], []
    for s in storms:
        test = tests[s]
        outer, info = results[frozenset({s})]
        row: dict[str, Any] = {
            "storm": s,
            "counties": len(test),
            "observed_total": round(float((test["peak_frac"] * test["customers_mcc"]).sum())),
            "wind_calibration": info,
        }
        for m in methods:
            row[m] = score(test, outer[s][m])
        table = pd.DataFrame(
            {"storm": s, "fips": test["fips"], "obs_out": test["peak_frac"] * customers(test)}
        )
        for m in methods:
            table[f"{m}_out"] = outer[s][m].point * customers(test)
        if nested:
            pool_ = [m for m in POOL if m in methods]
            losses = {
                m: float(
                    np.mean(
                        [inner_loss(tests[t], results[frozenset({s, t})][0][t][m]) for t in storms if t != s]
                    )
                )
                for m in pool_
            }
            chosen = min(pool_, key=lambda m: (losses[m], pool_.index(m)))
            row["S5"] = {
                **row[chosen],
                "variant": chosen,
                "inner_loss": {m: round(v, 4) for m, v in losses.items()},
            }
            table["S5_out"] = table[f"{chosen}_out"]
            p = outer[s][chosen]
            if p.lo80 is not None and p.hi80 is not None:
                table["S5_lo80_out"] = p.lo80 * customers(test)
                table["S5_hi80_out"] = p.hi80 * customers(test)
        rows.append(row)
        preds.append(table)
    return {"storms": rows, "predictions": pd.concat(preds, ignore_index=True)}


def one_sided_p(a: np.ndarray, b: np.ndarray) -> float | None:
    """One-sided Wilcoxon signed-rank on per-storm ln(a / b) (H1: a lower); zero differences dropped."""
    d = np.log(a / b)
    d = d[~np.isclose(d, 0.0, atol=1e-12)]
    if len(d) < 2:
        return None
    return float(wilcoxon(d, alternative="less").pvalue)


def holm(pvalues: dict[str, float | None]) -> dict[str, dict[str, float | None]]:
    known = sorted(((p, k) for k, p in pvalues.items() if p is not None), key=lambda x: x[0])
    m, running = len(known), 0.0
    out: dict[str, dict[str, float | None]] = {}
    for i, (pv, k) in enumerate(known):
        running = max(running, min(1.0, (m - i) * pv))
        out[k] = {"p": round(pv, 5), "multiplier": m - i, "holm_p": round(running, 5)}
    for k, maybe in pvalues.items():
        if maybe is None:
            out[k] = {"p": None, "multiplier": None, "holm_p": None}
    return out


def _vals(rows: list[dict[str, Any]], m: str, key: str) -> np.ndarray:
    return np.array([r[m][key] for r in rows], dtype=float)


def compare(rows: list[dict[str, Any]], a: str, b: str) -> dict[str, Any]:
    ma, mb = _vals(rows, a, "county_mae"), _vals(rows, b, "county_mae")
    la, lb = _vals(rows, a, "abs_ln_p_over_o"), _vals(rows, b, "abs_ln_p_over_o")
    p = one_sided_p(ma, mb)
    pt = one_sided_p(np.exp(la), np.exp(lb))
    ra = np.array([r[a]["spearman"] or 0.0 for r in rows])
    rb = np.array([r[b]["spearman"] or 0.0 for r in rows])
    return {
        "total_closer_wilcoxon_p_one_sided": round(pt, 5) if pt is not None else None,
        "spearman_better": int((ra > rb).sum()),
        "wins_county_mae": int((ma < mb).sum()),
        "losses_county_mae": int((ma > mb).sum()),
        "median_county_mae_ratio": round(float(np.median(ma / mb)), 4),
        "wilcoxon_p_one_sided": round(p, 5) if p is not None else None,
        "closer_total": int((la < lb).sum()),
        "median_abs_ln_po_difference": round(float(np.median(la) - np.median(lb)), 4),
    }


def summarise(rows: list[dict[str, Any]], storms: tuple[str, ...] | None = None) -> dict[str, Any]:
    keep = [r for r in rows if storms is None or r["storm"] in storms]
    methods = [m for m in (*METHODS, "S5", "F2_ante30") if keep and m in keep[0]]
    obs = sum(r["observed_total"] for r in keep)
    out: dict[str, Any] = {"storms": len(keep)}
    for m in methods:
        d: dict[str, Any] = {
            "median_abs_ln_po": round(float(np.median(_vals(keep, m, "abs_ln_p_over_o"))), 4),
            "median_ln_po": round(float(np.median(_vals(keep, m, "ln_p_over_o"))), 4),
            "median_rel_total_error": round(float(np.median(_vals(keep, m, "rel_total_error"))), 4),
            "storms_under_predicted": int(sum(r[m]["predicted_total"] < r["observed_total"] for r in keep)),
            "pooled_p_over_o": round(sum(r[m]["predicted_total"] for r in keep) / obs, 4),
            "median_spearman": round(float(np.median([r[m]["spearman"] or 0.0 for r in keep])), 4),
        }
        if "coverage_80" in keep[0][m]:
            d["mean_coverage_80"] = round(float(np.mean(_vals(keep, m, "coverage_80"))), 4)
            d["mean_coverage_95"] = round(float(np.mean(_vals(keep, m, "coverage_95"))), 4)
            d["point_outside_own_80_rows"] = int(sum(r[m]["point_outside_own_80"] for r in keep))
        if "total_hit_80" in keep[0][m]:
            d["total_hit_80_storms"] = int(sum(r[m]["total_hit_80"] for r in keep))
            d["median_total_band_width_hi_over_lo"] = round(
                float(np.median([r[m]["total_hi80"] / max(r[m]["total_lo80"], 1) for r in keep])), 2
            )
            d["total_band_missed"] = [
                f"{r['storm']} ({'above' if r['observed_total'] > r[m]['total_hi80'] else 'below'})"
                for r in sorted(keep, key=lambda x: -x["observed_total"])
                if not r[m]["total_hit_80"]
            ]
        large = [r for r in keep if r["storm"] in LARGE_8]
        rest = [r for r in keep if r["storm"] not in LARGE_8]
        for name, part in (("large8", large), ("other", rest)):
            if part:
                d[f"pooled_p_over_o_{name}"] = round(
                    sum(r[m]["predicted_total"] for r in part) / sum(r["observed_total"] for r in part), 4
                )
        d["versus"] = {b: compare(keep, m, b) for b in COMPARATORS if b != m and b in keep[0]}
        out[m] = d
    return out


def contrasts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    raw = {
        k: one_sided_p(_vals(rows, a, "county_mae"), _vals(rows, b, "county_mae"))
        for k, (a, b) in CONTRASTS.items()
    }
    return {k: {"a": CONTRASTS[k][0], "b": CONTRASTS[k][1], **v} for k, v in holm(raw).items()}


def ml_bar(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    large: dict[str, Any],
    refit: dict[str, Any] | None,
    tests: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    c2_mult = tests["C2"]["multiplier"] or 1
    for arm, (fcmp, bcmp) in ML_ARMS.items():
        checks: dict[str, bool] = {}
        for cmp in (fcmp, bcmp):
            v = summary[arm]["versus"][cmp]
            checks[f"median_ratio_le_0.90_vs_{cmp}"] = v["median_county_mae_ratio"] <= 0.90
            checks[f"wins_ge_18_vs_{cmp}"] = v["wins_county_mae"] >= 18
            checks[f"abs_ln_po_no_worse_plus_0.05_vs_{cmp}"] = (
                summary[arm]["median_abs_ln_po"] <= summary[cmp]["median_abs_ln_po"] + 0.05
            )
            checks[f"large8_pooled_po_ge_{cmp}"] = (
                large[arm]["pooled_p_over_o"] >= large[cmp]["pooled_p_over_o"]
            )
            checks[f"large8_wins_ge_5_vs_{cmp}"] = large[arm]["versus"][cmp]["wins_county_mae"] >= 5
            if refit is not None:
                r = refit[arm]["versus"][cmp]["median_county_mae_ratio"]
                checks[f"refit_2018_on_median_ratio_le_0.95_vs_{cmp}"] = r <= 0.95
        p_f = summary[arm]["versus"][fcmp]["wilcoxon_p_one_sided"]
        p_b = summary[arm]["versus"][bcmp]["wilcoxon_p_one_sided"]
        p_f_adj = (
            tests["C2"]["holm_p"] if arm == "M1" else (min(1.0, p_f * c2_mult) if p_f is not None else None)
        )
        checks[f"holm_p_lt_0.05_vs_{fcmp}"] = p_f_adj is not None and p_f_adj < 0.05
        checks[f"p_x3_lt_0.05_vs_{bcmp}"] = p_b is not None and p_b * 3 < 0.05
        checks["pooled_po_in_0.67_1.5"] = 0.67 <= summary[arm]["pooled_p_over_o"] <= 1.5
        out[arm] = {
            "comparators": [fcmp, bcmp],
            "p_adjusted_vs_f": p_f_adj,
            "checks": checks,
            "passed": all(checks.values()),
        }
    return out


def curve_bar(summary: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for arm, cmp in CURVE_ARMS.items():
        v = summary[arm]["versus"][cmp]
        checks = {
            "median_abs_ln_po_at_least_0.2_lower": summary[arm]["median_abs_ln_po"]
            <= summary[cmp]["median_abs_ln_po"] - 0.2,
            "closer_total_ge_17": v["closer_total"] >= 17,
            "pooled_po_in_0.67_1.5": 0.67 <= summary[arm]["pooled_p_over_o"] <= 1.5,
            "county_mae_non_inferior_median_ratio_le_1.10": v["median_county_mae_ratio"] <= 1.10,
        }
        out[arm] = {"comparator": cmp, "checks": checks, "passed": all(checks.values())}
    return out


def headline(ml: dict[str, Any], curve: dict[str, Any], tests: dict[str, Any]) -> str:
    for arm in ("M1", "M1w"):
        if ml[arm]["passed"]:
            return arm
    c3 = tests["C3"]["holm_p"]
    if curve["F2w"]["passed"] and c3 is not None and c3 < 0.05:
        return "F2w"
    if curve["F2"]["passed"]:
        return "F2"
    return "B3"


def serving_assessment(
    frame: pd.DataFrame, asos: pd.DataFrame, series: dict[str, Any], method: str
) -> dict[str, Any]:
    known = serving_storms(frame)
    cal = WindCalibration.fit(asos[asos["storm"].isin(known)])
    full = with_calibration(frame, cal, series)
    train = full[full["storm"].isin(known)].reset_index(drop=True)
    helene = full[full["storm"] == "helene"].reset_index(drop=True)
    pred = fit_predict(train, {"helene": helene}, tuple(dict.fromkeys(("B3", method))))["helene"]
    row = score(helene, pred[method])
    band = None
    p = pred[method]
    if p.total_lo80 is not None and p.total_hi80 is not None:
        band = [round(p.total_lo80 / p.total, 3), round(p.total_hi80 / p.total, 3)]
    return {
        "method": method,
        "trained_on": known,
        "helene": row,
        "helene_b3": score(helene, pred["B3"]),
        "storm_scale_band_k_80": band,
        "wp12_current_band_k": list(WP12_BAND),
        "note": "assessment only; not saved as a serving model and not activated",
    }


def k17_rows(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    tests: dict[str, Any],
    ml: dict[str, Any],
    curve: dict[str, Any],
    head: str,
) -> list[MetricRow]:
    out: list[MetricRow] = []
    n = summary["storms"]
    b3 = summary["B3"]
    for m in (*METHODS, "S5"):
        if m == "B3" or m not in summary:
            continue
        v = summary[m]["versus"]["B3"]
        key = f"{PREFIX_V3}.{m}"
        out.append(
            _row(
                f"{key}.storms_beats_b3_county_mae",
                v["wins_county_mae"],
                f"storms of {n} (strict)",
                n,
                n / 2,
                False,
                B3_NAME,
            )
        )
        out.append(
            _row(
                f"{key}.median_county_mae_ratio_vs_b3",
                v["median_county_mae_ratio"],
                "ratio",
                n,
                1.0,
                True,
                B3_NAME,
            )
        )
        out.append(
            _row(
                f"{key}.median_abs_ln_total_ratio",
                summary[m]["median_abs_ln_po"],
                "|ln(forecast total / observed total)|",
                n,
                b3["median_abs_ln_po"],
                True,
                B3_NAME,
            )
        )
        out.append(
            _row(
                f"{key}.pooled_forecast_over_observed",
                summary[m]["pooled_p_over_o"],
                "ratio (sum of forecast totals / sum of observed totals)",
                n,
                1.0,
                False,
                f"1.0 (unbiased); split, quote together: 8 largest storms "
                f"{summary[m].get('pooled_p_over_o_large8')}, other storms "
                f"{summary[m].get('pooled_p_over_o_other')} "
                f"(a pooled value near 1 can be offsetting errors); B3 pooled {b3['pooled_p_over_o']}",
            )
        )
        for part, label in (("large8", "8 largest storms"), ("other", "the other storms")):
            if f"pooled_p_over_o_{part}" in summary[m]:
                out.append(
                    _row(
                        f"{key}.pooled_forecast_over_observed_{part}",
                        summary[m][f"pooled_p_over_o_{part}"],
                        f"ratio (sum of forecast / sum of observed totals, {label})",
                        n,
                        1.0,
                        False,
                        f"1.0 (unbiased); B3 {b3.get(f'pooled_p_over_o_{part}')}",
                    )
                )
        out.append(
            _row(
                f"{key}.storms_closer_total_than_b3",
                v["closer_total"],
                f"storms of {n} with a smaller |ln(P/O)| than B3 (descriptive; one-sided Wilcoxon p "
                f"{v['total_closer_wilcoxon_p_one_sided']})",
                n,
                n / 2,
                False,
                B3_NAME,
            )
        )
        out.append(
            _row(
                f"{key}.storms_spearman_better_than_b3",
                v["spearman_better"],
                f"storms of {n} with a higher county rank correlation than B3 (descriptive)",
                n,
                n / 2,
                False,
                B3_NAME,
            )
        )
        out.append(
            _row(
                f"{key}.storms_under_predicted_total",
                summary[m]["storms_under_predicted"],
                f"storms of {n}",
                n,
                n / 2,
                True,
                "half of the storms (an unbiased forecast)",
            )
        )
        if "mean_coverage_80" in summary[m]:
            out.append(
                _row(
                    f"{key}.mean_county_coverage_80",
                    summary[m]["mean_coverage_80"],
                    "share of counties",
                    n,
                    0.8,
                    False,
                    "nominal 80%",
                )
            )
        if "total_hit_80_storms" in summary[m]:
            out.append(
                _row(
                    f"{key}.storm_total_in_80_band",
                    summary[m]["total_hit_80_storms"],
                    f"storms of {n}; quote with: band about "
                    f"{summary[m]['median_total_band_width_hi_over_lo']}x "
                    f"wide (median hi/lo); missed {', '.join(summary[m]['total_band_missed'])}",
                    n,
                    0.8 * n,
                    False,
                    "nominal 80% of storms",
                )
            )
            out.append(
                _row(
                    f"{key}.median_total_band_width_hi_over_lo",
                    summary[m]["median_total_band_width_hi_over_lo"],
                    "ratio (upper / lower end of the storm-total 80% band, median over storms)",
                    n,
                    1.0,
                    True,
                    "1.0 (a point forecast); width is the price of the coverage",
                )
            )
    for k, t in tests.items():
        if t["holm_p"] is not None:
            out.append(
                _row(
                    f"{PREFIX_V3}.contrast_{k}_{t['a']}_vs_{t['b']}_holm_p",
                    t["holm_p"],
                    "p-value (one-sided Wilcoxon on per-storm ln county MAE ratio, Holm)",
                    n,
                    0.05,
                    True,
                    f"{t['b']} (pre-registered contrast)",
                )
            )
    for arm, res in {**ml, **curve}.items():
        kind = "ml_bar" if arm in ml else "curve_bar"
        out.append(
            _row(
                f"{PREFIX_V3}.{kind}_{arm}_passed",
                float(res["passed"]),
                "1 = all pre-registered checks hold",
                n,
                1.0,
                False,
                "pre-registered bar",
            )
        )
    for r in rows:
        m, b = r[head], r["B3"]
        key = f"{PREFIX_V3}.headline_{head}.{r['storm']}"
        out.append(
            _row(
                f"{key}.county_mae",
                m["county_mae"],
                "customers",
                r["counties"],
                b["county_mae"],
                True,
                B3_NAME,
            )
        )
        out.append(
            _row(
                f"{key}.abs_ln_total_ratio",
                m["abs_ln_p_over_o"],
                "|ln(P/O)|",
                r["counties"],
                b["abs_ln_p_over_o"],
                True,
                B3_NAME,
            )
        )
        if "coverage_80" in m:
            out.append(
                _row(
                    f"{key}.coverage_80",
                    m["coverage_80"],
                    "share of counties",
                    r["counties"],
                    0.8,
                    False,
                    "nominal 80%",
                )
            )
    return out


def run_v3(write: bool = True) -> dict[str, Any]:
    from sgw.models.hazard.asos import load_asos
    from sgw.models.outage.dataset import frame_sha256

    frame = v3_frame()
    asos = load_asos()
    series = storm_series(frame)
    main = run(frame, asos, series)
    rows = main["storms"]
    summary = summarise(rows)
    large = summarise(rows, LARGE_8)
    refit_frame = frame[~frame["storm"].isin(PRE_2018)].reset_index(drop=True)
    refit_rows = run(refit_frame, asos, series)["storms"]
    refit = summarise(refit_rows)
    tests = contrasts(rows)
    ml = ml_bar(rows, summary, large, refit, tests)
    curve = curve_bar(summary)
    head = headline(ml, curve, tests)
    sens: dict[str, Any] = {}
    l2 = frame.assign(peak_frac=frame["peak_frac_l2"])
    sens["labels_l2"] = summarise(run(l2, asos, series, nested=False)["storms"])
    gap = frame[frame["gap_flag"] == 0].reset_index(drop=True)
    sens["without_gap_flagged_rows"] = {
        "rows_dropped": int((frame["gap_flag"] == 1).sum()),
        "summary": summarise(run(gap, asos, series, nested=False)["storms"]),
    }
    if "rain_antecedent_30d_mm" in frame.columns:
        a30 = frame.assign(rain_antecedent_14d_mm=frame["rain_antecedent_30d_mm"])
        a30_rows = run(a30, asos, series, methods=("B3", "F2"), nested=False)["storms"]
        for r, base in zip(a30_rows, rows, strict=True):
            r["F2_ante30"], r["F2"], r["B3"] = r.pop("F2"), base["F2"], base["B3"]
        sens["antecedent_30d"] = summarise(a30_rows)
    serving = serving_assessment(frame, asos, series, head if head != "B3" else "F2")
    report = EvalReport(
        name="outage_loso_v3",
        created_at=pd.Timestamp.now(tz="UTC").to_pydatetime().replace(microsecond=0),
        code_version=_git_version(),
        llm_mode="replay",
        command=COMMAND_V3,
        metrics=k17_rows(rows, summary, tests, ml, curve, head),
    )
    detail = {
        "name": "outage_loso_v3_detail",
        "label": "C: EAGLE-I (CC BY 4.0), HURDAT2, IEM ASOS and IEMRE; 24 storms, LOSO; " + HINDCAST_LABEL,
        "preregistration": "docs/models/outage-v3-preregistration.md (commit 1368966)",
        "headline": head,
        "data_sha256": frame_sha256(frame),
        "summary_all": summary,
        "summary_large_8": large,
        "sensitivity_2018_on_refit": {"summary": refit, "storms": refit_rows},
        "contrasts_holm": tests,
        "ml_bar": ml,
        "curve_bar": curve,
        "sensitivities_outer_only": sens,
        "wind_input_bias_by_storm": storm_wind_bias(asos),
        "serving_candidate_assessment": serving,
        "storms": rows,
    }
    if write:
        REPORT_V3.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        DETAIL_V3.write_text(json.dumps(detail, indent=2) + "\n", encoding="utf-8")
        main["predictions"].round(1).to_csv(PREDICTIONS_V3, index=False, lineterminator="\n")
    return {"report": report, "detail": detail}


def main() -> None:
    detail = run_v3(write=True)["detail"]
    keys = ("headline", "contrasts_holm", "ml_bar", "curve_bar", "serving_candidate_assessment")
    print(json.dumps({k: detail[k] for k in keys}, indent=1))


if __name__ == "__main__":
    main()
