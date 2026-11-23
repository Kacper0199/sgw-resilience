"""K17 report `evals/reports/saa.json` from one plan run (split dev: family-A synthetic Helene replay)."""

from __future__ import annotations

import math
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np

from sgw.contracts.eval_report import EvalReport, MetricRow
from sgw.contracts.vocab import EvalSplit, NumberLabel
from sgw.models.optimise.coa import COA_IDS, PlanRun
from sgw.models.optimise.saa import cvar_of
from sgw.models.optimise.scenarios import param

REPORT_COMMAND = "uv run sgw optimise report"
CH = "customer-hours"


def code_version(root: Path | None = None) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            cwd=root,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _row(
    metric: str,
    value: float,
    unit: str,
    n: int,
    *,
    baseline_name: str,
    baseline_value: float,
    threshold: float,
    lower_is_better: bool,
    ci: tuple[float, float] | None = None,
) -> MetricRow:
    direction: Literal["higher_is_better", "lower_is_better"] = (
        "lower_is_better" if lower_is_better else "higher_is_better"
    )
    passed = value <= threshold if lower_is_better else value >= threshold
    return MetricRow(
        metric=metric,
        value=round(float(value), 6),
        unit=unit,
        n=n,
        split=EvalSplit.DEV,
        label=NumberLabel.C,
        baseline_name=baseline_name,
        baseline_value=round(float(baseline_value), 6),
        threshold=round(float(threshold), 6),
        direction=direction,
        passed=passed,
        ci_low=None if ci is None else round(float(ci[0]), 6),
        ci_high=None if ci is None else round(float(ci[1]), 6),
    )


def _mean_ci(x: np.ndarray) -> tuple[float, float]:
    m, se = float(x.mean()), float(x.std(ddof=1) / math.sqrt(x.size))
    return m - 1.96 * se, m + 1.96 * se


def metrics(pr: PlanRun) -> list[MetricRow]:
    reps = pr.replications
    p50 = pr.outcomes["P50"]
    alpha = float(param("cvar_alpha"))
    limit = float(param("time_limit_s"))
    gap = float(param("mip_rel_gap"))
    size = f"{len(pr.ctx.geo.yards)} yards x {pr.ctx.geo.n_clusters} clusters x {pr.n_in} scenarios"
    b_size = (
        f"{len(pr.ctx.geo.yards)} yards x {pr.ctx.geo.n_clusters} clusters x {pr.cvar_check['scenarios']}"
    )
    rows = [
        _row(
            "saa.coa_a.solve_seconds_max_over_replications",
            max(r["seconds"] for r in reps),
            f"s ({size})",
            len(reps),
            baseline_name="p50_deterministic plan solve",
            baseline_value=p50.solve.seconds,
            threshold=limit,
            lower_is_better=True,
        ),
        _row(
            "saa.coa_a.mip_rel_gap_max_over_replications",
            max(r["mip_gap"] for r in reps),
            "relative MIP gap",
            len(reps),
            baseline_name="p50_deterministic plan gap",
            baseline_value=p50.solve.mip_gap,
            threshold=gap,
            lower_is_better=True,
        ),
        _row(
            "saa.coa_b.cvar_solve_seconds",
            float(pr.cvar_check["cvar_solve_seconds"]),
            f"s ({b_size} scenarios, CVaR)",
            1,
            baseline_name="p50_deterministic plan solve",
            baseline_value=p50.solve.seconds,
            threshold=limit,
            lower_is_better=True,
        ),
    ]
    mmw = pr.mmw
    rows.append(
        _row(
            "saa.coa_a.optimality_gap_rel_upper95_paired_mak_morton_wood",
            mmw["gap_rel_upper95"],
            "relative gap, one-sided 95% upper bound",
            int(mmw["replications"]),
            baseline_name="point estimate of the paired gap",
            baseline_value=mmw["gap_rel"],
            threshold=gap,
            lower_is_better=True,
        )
    )
    for key, name in (("ev", "expected_value plan (Birge EV)"), ("p50", "p50_deterministic plan")):
        v = pr.vss[key]
        rows.append(
            _row(
                f"saa.coa_a.vss_vs_{key}_out_of_sample",
                v["value"],
                CH,
                int(v["n"]),
                baseline_name=f"{name}, same early mutual-aid request",
                baseline_value=float(pr.outcomes["EV" if key == "ev" else "P50"].mean_ch),
                threshold=1.0,
                lower_is_better=False,
                ci=(v["ci_low"], v["ci_high"]),
            )
        )
    rows += [
        _row(
            "saa.coa_a.evpi_in_sample",
            pr.evpi["in_sample"],
            CH,
            int(pr.evpi["in_sample_n"]),
            baseline_name="wait-and-see (perfect information) mean",
            baseline_value=pr.evpi["wait_and_see_in_sample"],
            threshold=0.0,
            lower_is_better=False,
        ),
        _row(
            "saa.coa_a.evpi_out_of_sample",
            pr.evpi["out_of_sample"],
            CH,
            int(pr.evpi["out_of_sample_n"]),
            baseline_name="wait-and-see on fresh scenarios",
            baseline_value=pr.evpi["wait_and_see_out_of_sample"],
            threshold=0.0,
            lower_is_better=False,
        ),
    ]
    cc = pr.cvar_check
    tag = f"cvar{int(alpha * 100)}"
    rows.append(
        _row(
            f"saa.coa_b.{tag}_out_of_sample_cvar_placement",
            float(cc[f"{tag}_out_of_sample_cvar_plan"]),
            CH,
            pr.n_out,
            baseline_name="risk-neutral placement at the same cap",
            baseline_value=float(cc[f"{tag}_out_of_sample_neutral_plan"]),
            threshold=float(cc[f"{tag}_out_of_sample_neutral_plan"]),
            lower_is_better=True,
        )
    )
    for pid in ("EV", *COA_IDS):
        o = pr.outcomes[pid]
        tag_p = pid.lower().replace("-", "_")
        rows += [
            _row(
                f"saa.{tag_p}.expected_customer_hours_out_of_sample",
                o.mean_ch,
                CH,
                int(o.oos_ch.size),
                baseline_name="p50_deterministic plan",
                baseline_value=p50.mean_ch,
                threshold=p50.mean_ch,
                lower_is_better=True,
                ci=_mean_ci(o.oos_ch),
            ),
            _row(
                f"saa.{tag_p}.{tag}_customer_hours_out_of_sample",
                cvar_of(o.oos_ch, alpha),
                CH,
                int(o.oos_ch.size),
                baseline_name="p50_deterministic plan",
                baseline_value=cvar_of(p50.oos_ch, alpha),
                threshold=cvar_of(p50.oos_ch, alpha),
                lower_is_better=True,
            ),
            _row(
                f"saa.{tag_p}.synthetic_truth_customer_hours",
                o.truth_ch,
                f"{CH} (WP-06 realised county peaks, synthetic)",
                1,
                baseline_name="p50_deterministic plan",
                baseline_value=p50.truth_ch,
                threshold=p50.truth_ch,
                lower_is_better=True,
            ),
            _row(
                f"saa.{tag_p}.observed_scale_stress_customer_hours",
                o.stress_ch,
                f"{CH} (40 members at the replayed storm's hindcast scale k={pr.stress_k:.2f})",
                len(pr.ctx.inputs.members),
                baseline_name="p50_deterministic plan",
                baseline_value=p50.stress_ch,
                threshold=p50.stress_ch,
                lower_is_better=True,
            ),
        ]
        if pid in COA_IDS:
            rows += [
                _row(
                    f"saa.{tag_p}.expected_mutual_aid_person_days",
                    o.cost.person_days,
                    "person-days (early + post-landfall, arrival to release at the Helene 90%-restored time)",
                    int(o.oos_ch.size),
                    baseline_name="p50_deterministic plan",
                    baseline_value=p50.cost.person_days,
                    threshold=p50.cost.person_days,
                    lower_is_better=True,
                ),
                _row(
                    f"saa.{tag_p}.expected_mutual_aid_usd",
                    o.cost.usd,
                    "USD (2,240 USD per lineworker-day, handoff s3)",
                    int(o.oos_ch.size),
                    baseline_name="p50_deterministic plan",
                    baseline_value=p50.cost.usd,
                    threshold=p50.cost.usd,
                    lower_is_better=True,
                ),
                _row(
                    f"saa.{tag_p}.expected_idle_early_mutual_aid_persons",
                    float(o.oos_idle.mean()),
                    "persons",
                    int(o.oos_idle.size),
                    baseline_name="p50_deterministic plan",
                    baseline_value=float(p50.oos_idle.mean()),
                    threshold=float(p50.oos_idle.mean()),
                    lower_is_better=True,
                ),
            ]
            avoided = p50.mean_ch - o.mean_ch
            if avoided > 0:
                per_ch = (o.cost.usd - p50.cost.usd) / avoided
                rows.append(
                    _row(
                        f"saa.{tag_p}.usd_per_customer_hour_avoided_vs_p50",
                        per_ch,
                        "USD per customer-hour of delay avoided (expected, out of sample)",
                        int(o.oos_ch.size),
                        baseline_name="p50_deterministic plan",
                        baseline_value=0.0,
                        threshold=max(per_ch, 0.0),
                        lower_is_better=True,
                    )
                )
    return rows


def build(pr: PlanRun, *, root: Path | None = None) -> EvalReport:
    return EvalReport(
        name="saa",
        created_at=datetime.now(UTC).replace(microsecond=0),
        code_version=code_version(root),
        llm_mode="replay",
        command=REPORT_COMMAND,
        metrics=metrics(pr),
    )


def write(report: EvalReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
