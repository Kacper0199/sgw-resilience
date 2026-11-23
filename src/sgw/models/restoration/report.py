"""K17 report `evals/reports/etr.json`: Helene t50/t90 calibration and family-A ETR coverage, with baselines.

Row naming says what was fitted: `*_in_sample` rows are the three calibration targets themselves (not a test);
`*_not_fitted` rows compare Helene features the calibration never saw; `etr90.*` rows are scored on family-A
test storms that neither the model fit nor the conformal calibration used.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from sgw.contracts.eval_report import EvalReport, MetricRow
from sgw.contracts.vocab import EvalSplit, NumberLabel
from sgw.generator.config import REPO_ROOT
from sgw.models.restoration.calibrate import CalibrationReport
from sgw.models.restoration.evaluate import Evaluation
from sgw.models.restoration.params import default_params

REPORT_PATH = REPO_ROOT / "evals" / "reports" / "etr.json"
COMMAND = "uv run sgw restoration eval"
GENERATOR_BASELINE = "WP-06 generator restoration (no secondary jobs, no shifts)"
FITTED_REL_TOL = 0.05
NOT_FITTED_REL_TOL = 0.25
WEEK_SHARE_TOL = 0.10
COV50_TARGET = 0.5
WIDTH80_MAX_REL = 1.0
WIDTH50_MAX_REL = 0.5
STORY_ROWS = ("county_t50_median", "county_t90_median", "county_t90_peak_weighted_median")


def code_version() -> str:
    git = shutil.which("git")
    if git is None:
        return "unknown"
    try:
        out = subprocess.run(  # noqa: S603
            [git, "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out.stdout.strip()


def _row(
    metric: str,
    value: float,
    unit: str,
    n: int,
    baseline_name: str,
    baseline_value: float,
    threshold: float,
    direction: str,
    ci: tuple[float, float] | None = None,
) -> MetricRow:
    ok = value >= threshold if direction == "higher_is_better" else value <= threshold
    return MetricRow.model_validate(
        {
            "metric": metric,
            "value": round(value, 4),
            "unit": unit,
            "n": max(n, 1),
            "split": EvalSplit.DEV,
            "label": NumberLabel.C,
            "baseline_name": baseline_name,
            "baseline_value": round(baseline_value, 4),
            "threshold": round(threshold, 4),
            "direction": direction,
            "passed": ok,
            "ci_low": None if ci is None else round(min(ci[0], value), 4),
            "ci_high": None if ci is None else round(max(ci[1], value), 4),
        }
    )


def calibration_rows(cal: CalibrationReport) -> list[MetricRow]:
    rows = []
    for c in cal.stats:
        tag = "in_sample" if c.fitted else "not_fitted"
        n = cal.counties_compared
        if c.name == "county_t90_spearman":
            rows.append(
                _row(
                    f"restoration.helene.{c.name}_{tag}",
                    c.model,
                    c.unit,
                    n,
                    GENERATOR_BASELINE,
                    c.baseline,
                    c.baseline,
                    "higher_is_better",
                )
            )
        elif c.unit == "h":
            ref = ""
            tol = FITTED_REL_TOL if c.fitted else NOT_FITTED_REL_TOL
            rows.append(
                _row(
                    f"restoration.helene.{c.name}_rel_error_{ref}{tag}",
                    _rel(c.model, c.observed),
                    "relative",
                    n,
                    GENERATOR_BASELINE,
                    _rel(c.baseline, c.observed),
                    tol,
                    "lower_is_better",
                )
            )
        else:
            rows.append(
                _row(
                    f"restoration.helene.{c.name}_abs_error_{tag}",
                    abs(c.model - c.observed),
                    c.unit,
                    n,
                    GENERATOR_BASELINE,
                    abs(c.baseline - c.observed),
                    WEEK_SHARE_TOL,
                    "lower_is_better",
                )
            )
    for c in cal.story:
        if c.name in STORY_ROWS:
            rows.append(
                _row(
                    f"restoration.helene.story_seed.{c.name}_rel_error_in_sample_world",
                    _rel(c.model, c.observed),
                    "relative",
                    cal.counties_compared,
                    GENERATOR_BASELINE,
                    _rel(c.baseline, c.observed),
                    NOT_FITTED_REL_TOL,
                    "lower_is_better",
                )
            )
    return rows


def _rel(value: float, ref: float) -> float:
    if math.isinf(value) or math.isinf(ref):
        return 0.0 if value == ref else 1.0
    return abs(value - ref) / ref


def coverage_rows(ev: Evaluation) -> list[MetricRow]:
    prm = default_params()
    target = prm.f("etr", "coverage_target")
    tol = prm.f("etr", "coverage_tolerance")
    rows = []
    for s in ev.scores:
        stem = f"etr90.family_a_test.{s.population}.issue_declared_peak_plus_{int(s.offset_h)}h"
        raw = "Monte Carlo P10-P90 before conformal calibration"
        rows += [
            _row(
                f"{stem}.coverage80",
                s.coverage80,
                "share",
                s.n,
                raw,
                s.coverage80_raw,
                target - tol,
                "higher_is_better",
                s.coverage80_ci,
            ),
            _row(
                f"{stem}.coverage50",
                s.coverage50,
                "share",
                s.n,
                "Monte Carlo P25-P75 before conformal calibration",
                s.coverage50_raw,
                COV50_TARGET - tol,
                "higher_is_better",
                s.coverage50_ci,
            ),
            _row(
                f"{stem}.width80_median_rel",
                s.width80_rel,
                "(P90 - P10) / P50",
                s.n,
                raw,
                s.width80_rel_raw,
                WIDTH80_MAX_REL,
                "lower_is_better",
            ),
            _row(
                f"{stem}.width50_median_rel",
                s.width50_rel,
                "(P75 - P25) / P50",
                s.n,
                "Monte Carlo P25-P75 before conformal calibration",
                s.width50_rel_raw,
                WIDTH50_MAX_REL,
                "lower_is_better",
            ),
            _row(
                f"{stem}.coverage80_abs_error",
                abs(s.coverage80 - target),
                "share",
                s.n,
                raw,
                abs(s.coverage80_raw - target),
                tol,
                "lower_is_better",
            ),
            _row(
                f"{stem}.p50_median_abs_pct_error",
                s.p50_mdape,
                "relative",
                s.n,
                "historical analog: region peak + EAGLE-I Helene county median t90",
                s.analog_mdape,
                s.analog_mdape,
                "lower_is_better",
            ),
        ]
    return rows


def build(ev: Evaluation, cal: CalibrationReport) -> EvalReport:
    return EvalReport.model_validate(
        {
            "name": "etr",
            "created_at": datetime.now(UTC).replace(microsecond=0),
            "code_version": code_version(),
            "llm_mode": "replay",
            "command": COMMAND,
            "metrics": [*calibration_rows(cal), *coverage_rows(ev)],
        }
    )


def write(report: EvalReport, path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path
