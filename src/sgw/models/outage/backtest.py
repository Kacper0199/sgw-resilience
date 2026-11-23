"""Leave-one-storm-out hindcast of A2 on four real storms, the wind-threshold baseline beside it.

Hindcast, observed track: the held-out storm's features come from its post-season HURDAT2 best track, so the
errors measure the outage model given the true wind, not operational forecast error. Each fold trains the
model, its conformal offsets and the baseline on three storms and scores the fourth; nothing from the held-out
storm reaches training. Four storms give directional evidence only (no significance claim, PA-ai-02).

Outputs: the K17 report `evals/reports/outage_loso.json` (per storm, headline first: county MAE, Spearman
rank correlation, 80% and 95% coverage; then total error against the wind threshold and the fragility prior,
worst miss and the ablation), the per-county predictions and a detail file (worst misses by name, observed
totals capped and uncapped, SHAP importance, fitted baselines) under `data/artefacts/models/outage/`, and the
serving model for the Helene replay: the fold trained without Helene.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from sgw.contracts.eval_report import EvalReport, MetricRow
from sgw.contracts.vocab import EvalSplit, NumberLabel
from sgw.models.hazard.hurdat2 import REPO_ROOT, STORMS
from sgw.models.outage.baseline import WindThreshold, fragility_prior
from sgw.models.outage.dataset import frame_sha256, training_frame
from sgw.models.outage.model import FEATURES, STORM_LEVEL_FEATURES, OutageModel

REPORT_PATH = REPO_ROOT / "evals" / "reports" / "outage_loso.json"
ARTEFACT_DIR = REPO_ROOT / "data" / "artefacts" / "models" / "outage"
SERVING_MODEL = "a2-excl-helene"
BASELINE_NAME = "wind_threshold (T, a, b fitted on the 3 training storms of each fold)"
COMMAND = "uv run sgw models backtest-outage"
FRAGILITY_NAME = (
    "fragility_prior (lognormal on gust, median 50 m/s, beta 0.4; not fitted here, but lightly tuned: "
    "the median was set with Helene/EAGLE-I evidence, R02 hazard-interdependency 9.7)"
)
PREFIX = "outage_loso.hindcast_observed_track"
LOWER = "lower_is_better"
HIGHER = "higher_is_better"
HINDCAST_LABEL = (
    "hindcast, observed track: features of the held-out storm come from its post-season HURDAT2 best track, "
    "not from the forecasts available at the time, so the errors understate operational forecast error"
)
BOOTSTRAP = 2000
BOOTSTRAP_SEED = 7
COVERAGE_TARGET = 0.8


@dataclass
class FoldResult:
    storm: str
    frame: pd.DataFrame
    baseline: WindThreshold
    model: OutageModel
    shap_importance: dict[str, float]


def run_fold(frame: pd.DataFrame, held: str, features: tuple[str, ...] = FEATURES) -> FoldResult:
    train = frame[frame["storm"] != held].reset_index(drop=True)
    test = frame[frame["storm"] == held].reset_index(drop=True).copy()
    model = OutageModel.fit(train, features)
    baseline = WindThreshold.fit(train)
    fc = model.predict(test)
    customers = test["customers_mcc"].to_numpy(dtype=float)
    test["obs_out"] = test["peak_frac"] * customers
    test["model_mean_out"] = fc.mean * customers
    test["model_p50_out"] = fc.p50 * customers
    for name, (lo, hi) in fc.intervals.items():
        test[f"model_lo{name}_out"] = lo * customers
        test[f"model_hi{name}_out"] = hi * customers
    test["baseline_out"] = baseline.predict(test) * customers
    test["fragility_out"] = fragility_prior(test) * customers
    shap_values = model.shap(test)
    importance = {f: round(float(np.abs(shap_values[f]).mean()), 4) for f in features}
    return FoldResult(held, test, baseline, model, importance)


def rel_total_error(pred: np.ndarray, obs: np.ndarray) -> float:
    return float(abs(pred.sum() - obs.sum()) / obs.sum())


def bootstrap_ci(pred: np.ndarray, obs: np.ndarray) -> tuple[float, float]:
    """County resample within one storm only: says nothing about storm-to-storm variation."""
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    idx = rng.integers(0, len(obs), size=(BOOTSTRAP, len(obs)))
    stats = np.abs(pred[idx].sum(axis=1) - obs[idx].sum(axis=1)) / obs[idx].sum(axis=1)
    lo, hi = np.quantile(stats, [0.05, 0.95])
    return float(lo), float(hi)


def worst_miss(test: pd.DataFrame, column: str) -> dict[str, Any]:
    err = (test[column] - test["obs_out"]).abs()
    i = int(err.idxmax())
    row = test.loc[i]
    return {
        "fips": row["fips"],
        "county": f"{row['name']}, {row['st']}",
        "observed_out": round(float(row["obs_out"])),
        "predicted_out": round(float(row[column])),
        "abs_error": round(float(err[i])),
        "peak_gust_ms": round(float(row["peak_gust_ms"]), 1),
    }


def storm_summary(fold: FoldResult) -> dict[str, Any]:
    t = fold.frame
    obs = t["obs_out"].to_numpy()
    out: dict[str, Any] = {"storm": fold.storm, "counties": len(t), "observed_total_out": round(obs.sum())}
    for key, column in (
        ("model", "model_mean_out"),
        ("baseline", "baseline_out"),
        ("fragility", "fragility_out"),
    ):
        pred = t[column].to_numpy()
        out[key] = {
            "predicted_total_out": round(pred.sum()),
            "rel_total_error": round(rel_total_error(pred, obs), 4),
            "county_mae_out": round(float(np.abs(pred - obs).mean()), 1),
            "spearman": round(float(spearmanr(pred, obs).statistic), 4) if np.ptp(pred) > 0 else None,
            "worst_miss": worst_miss(t, column),
        }
    for name in ("50", "80", "95"):
        inside = (t[f"model_lo{name}_out"] <= obs) & (obs <= t[f"model_hi{name}_out"])
        out["model"][f"coverage_{name}"] = round(float(inside.mean()), 4)
    out["model"]["ci90_rel_total_error_county_resample_within_storm_only"] = [
        round(v, 4) for v in bootstrap_ci(t["model_mean_out"].to_numpy(), obs)
    ]
    out["observed_total_out_uncapped"] = int(t["peak_excess"].sum())
    out["baseline_fit"] = {
        "threshold_ms": fold.baseline.threshold_ms,
        "share_above": round(fold.baseline.share_above, 4),
        "share_below": round(fold.baseline.share_below, 4),
    }
    out["shap_mean_abs"] = fold.shap_importance
    out["model"]["trained_on"] = fold.model.trained_on
    return out


def _git_version() -> str:
    try:
        return subprocess.run(  # noqa: S603
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _row(
    metric: str, value: float, unit: str, n: int, baseline: float, direction: str, **kw: Any
) -> MetricRow:
    threshold = kw.pop("threshold", baseline)
    passed = value <= threshold if direction == "lower_is_better" else value >= threshold
    return MetricRow(
        metric=metric,
        value=round(value, 4),
        unit=unit,
        n=n,
        split=EvalSplit.REAL_LOSO,
        label=NumberLabel.C,
        baseline_name=kw.pop("baseline_name", BASELINE_NAME),
        baseline_value=round(baseline, 4),
        threshold=round(threshold, 4),
        direction=direction,  # type: ignore[arg-type]
        passed=passed,
        **kw,
    )


def metric_rows(summaries: list[dict[str, Any]], ablation: list[dict[str, Any]]) -> list[MetricRow]:
    """Headline first: county MAE, Spearman, 80% and 95% coverage per storm; total error second."""
    rows: list[MetricRow] = []
    wins = 0
    abl = {a["storm"]: a for a in ablation}
    for s in summaries:
        m, b, n, name = s["model"], s["baseline"], s["counties"], s["storm"]
        key = f"{PREFIX}.{name}"
        wins += int(m["rel_total_error"] < b["rel_total_error"])
        rows.append(
            _row(f"{key}.county_mae", m["county_mae_out"], "customers", n, b["county_mae_out"], LOWER)
        )
        rows.append(
            _row(f"{key}.spearman", m["spearman"], "rank correlation", n, b["spearman"] or 0.0, HIGHER)
        )
        for level in ("80", "95"):
            rows.append(
                _row(
                    f"{key}.coverage_{level}",
                    m[f"coverage_{level}"],
                    "share of counties",
                    n,
                    int(level) / 100,
                    HIGHER,
                    baseline_name=f"nominal coverage of the {level}% storm-grouped CQR interval",
                )
            )
        rows.append(
            _row(f"{key}.rel_total_error", m["rel_total_error"], "ratio", n, b["rel_total_error"], LOWER)
        )
        rows.append(
            _row(
                f"{key}.rel_total_error_vs_fragility_prior",
                m["rel_total_error"],
                "ratio",
                n,
                s["fragility"]["rel_total_error"],
                LOWER,
                baseline_name=FRAGILITY_NAME,
            )
        )
        rows.append(
            _row(
                f"{key}.worst_miss",
                m["worst_miss"]["abs_error"],
                "customers",
                n,
                b["worst_miss"]["abs_error"],
                LOWER,
            )
        )
        rows.append(
            _row(
                f"{key}.county_mae_ablation_without_storm_level_features",
                abl[name]["county_mae_out"],
                "customers",
                n,
                b["county_mae_out"],
                LOWER,
            )
        )
    rows.append(
        _row(
            f"{PREFIX}.storms_model_beats_baseline_rel_total_error",
            float(wins),
            "storms (strictly lower; ties are not wins)",
            len(summaries),
            float(len(summaries) - wins),
            HIGHER,
            threshold=3.0,
        )
    )
    return rows


def run_backtest(
    write: bool = True, report_path: Path = REPORT_PATH, artefacts: Path = ARTEFACT_DIR
) -> dict[str, Any]:
    frame = training_frame()
    data_sha = frame_sha256(frame)
    folds = [run_fold(frame, s.name) for s in STORMS]
    summaries = [storm_summary(f) for f in folds]
    reduced = tuple(f for f in FEATURES if f not in STORM_LEVEL_FEATURES)
    ablation = []
    for f in (run_fold(frame, s.name, reduced) for s in STORMS):
        a = storm_summary(f)
        ablation.append(
            {
                "storm": a["storm"],
                "rel_total_error": a["model"]["rel_total_error"],
                "county_mae_out": a["model"]["county_mae_out"],
                "spearman": a["model"]["spearman"],
                "coverage_80": a["model"]["coverage_80"],
                "coverage_95": a["model"]["coverage_95"],
            }
        )
    report = EvalReport(
        name="outage_loso",
        created_at=datetime.now(tz=UTC).replace(microsecond=0),
        code_version=_git_version(),
        llm_mode="replay",
        command=COMMAND,
        metrics=metric_rows(summaries, ablation),
    )
    detail = {
        "name": "outage_loso_detail",
        "label": (
            "C: computed from EAGLE-I (CC BY 4.0) and HURDAT2; directional, 4 storms, no significance claim; "
            + HINDCAST_LABEL
        ),
        "intervals": "storm-grouped CQR, uncalibrated across storm types; coverage reported per storm",
        "fragility_baseline": FRAGILITY_NAME,
        "data_sha256": data_sha,
        "unit": (
            "county x storm; target = peak customers out above the pre-storm level, capped at MCC customers"
        ),
        "note_totals": "sum of non-simultaneous county peaks, not the footprint simultaneous peak",
        "storms": summaries,
        "ablation_without_storm_level_features": {
            "features": list(reduced),
            "note": (
                "sensitivity run, not the headline: the headline feature set was fixed before the first run; "
                "this run drops the two features that are nearly constant within a storm"
            ),
            "storms": ablation,
        },
    }
    if write:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        artefacts.mkdir(parents=True, exist_ok=True)
        (artefacts / "loso_detail.json").write_text(json.dumps(detail, indent=2) + "\n", encoding="utf-8")
        cols = [
            "storm",
            "fips",
            "name",
            "st",
            "customers_mcc",
            "peak_gust_ms",
            "obs_out",
            "model_mean_out",
            "model_p50_out",
            "model_lo80_out",
            "model_hi80_out",
            "baseline_out",
            "fragility_out",
        ]
        preds = pd.concat([f.frame[cols] for f in folds], ignore_index=True).round(1)
        preds.to_csv(artefacts / "loso_predictions.csv", index=False, lineterminator="\n")
        serving = next(f for f in folds if f.storm == "helene").model
        serving.meta = {"name": SERVING_MODEL, "data_sha256": data_sha, "version": "1.0"}
        serving.save(artefacts / SERVING_MODEL)
    return {"report": report, "detail": detail, "folds": folds}
