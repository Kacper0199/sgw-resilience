"""SC-5 forecast-vs-actual scorecard for published ETR estimates.

The "actual" is the WP-17 restoration process's own simulated restoration of the story of record (the run the
estimates were issued from): hours from the issue time until customers out first fall to 10 percent of the
peak known at the issue time (`truth_etr`), per operating area and globally. It is labelled
"simulated actual, not the replay curve": the replay fixtures restore with the WP-06 generator process, so
scoring against the replayed outage curve would compare two different processes (WP-17 guard).

Each estimate gets its P50 error and whether the simulated actual fell inside P25-P75 and P10-P90; the
summary rows are K17 metrics with n, split and label. The baseline is WP-17's historical analog (the area's
peak time plus the observed Helene county median t90). One storm is one draw: the rows describe this story,
not the model's calibration (that is `evals/reports/etr.json`). The story seed is one of the five worlds the
restoration process was calibrated on, so the simulated actual is in-sample for the simulator.
The coverage rows are descriptive (threshold 0; the nominal coverage is the baseline value).

    uv run python -m sgw.reports.scorecard --estimates <jsonl>
        --out data/artefacts/evals/etr_story_scorecard.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from sgw.contracts.eval_report import EvalReport, MetricRow
from sgw.contracts.vocab import EvalSplit, NumberLabel
from sgw.models.restoration.publish import EtrEstimate

ACTUAL_LABEL = "simulated actual, not the replay curve"
PREFIX = "etr90.story_scorecard"


class EstimateScore(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    estimate_id: str
    scope: str
    region_id: str
    as_of_utc: datetime
    actual_utc: datetime | None
    actual_label: str = ACTUAL_LABEL
    p50_error_h: float | None
    abs_error_h: float | None
    analog_abs_error_h: float | None
    in_p25_p75: bool | None
    in_p10_p90: bool | None


@lru_cache(maxsize=1)
def _story() -> Any:
    from sgw.models.restoration.params import default_params
    from sgw.models.restoration.publish import story_run

    return story_run(default_params())


def warm() -> None:
    """Run the deterministic story simulation once (about 6 s) so the first after-action read is fast."""
    _story()


def simulated_actuals(estimates: Sequence[EtrEstimate]) -> dict[str, tuple[float, float]]:
    """region id (or GLOBAL) -> (simulated actual hours from the issue time, analog baseline hours) from the
    Story run at the estimates' issue time. The story run is deterministic (scenario seed, default
    parameters), so it and each issue time's result are computed once per process."""
    as_of = {e.as_of_utc for e in estimates}
    if len(as_of) != 1:
        raise ValueError("score one publication (one issue time) at a time")
    return dict(_actuals_at(next(iter(as_of)).timestamp()))


def score_publication(estimates: Sequence[EtrEstimate]) -> list[EstimateScore]:
    """One publication may mix issue times: a revision re-issues the areas still restoring and keeps the
    estimates of areas already restored. Each estimate is scored at its own issue time."""
    by_time: dict[datetime, list[EtrEstimate]] = {}
    for e in estimates:
        by_time.setdefault(e.as_of_utc, []).append(e)
    scores = [s for group in by_time.values() for s in score(group, simulated_actuals(group))]
    return sorted(scores, key=lambda s: (s.scope != "global", s.region_id))


@lru_cache(maxsize=32)
def _actuals_at(t: float) -> dict[str, tuple[float, float]]:
    from sgw.models.restoration.calibrate import load_observed, targets
    from sgw.models.restoration.etr import GLOBAL, observe, truth_etr
    from sgw.models.restoration.evaluate import analog_hours
    from sgw.models.restoration.params import default_params

    prm = default_params()
    run = _story()
    obs = observe(run, t, prm, run.world.seed)
    reg, glob = truth_etr(run, obs, prm)
    analog_t90 = float(targets(load_observed())[1])
    out = {GLOBAL: (glob, analog_hours(obs.peak_time_global, t, analog_t90))}
    for k, region in enumerate(run.world.region_ids):
        out[region] = (float(reg[k]), analog_hours(float(obs.peak_time_region[k]), t, analog_t90))
    return out


def score(estimates: Sequence[EtrEstimate], actuals: dict[str, tuple[float, float]]) -> list[EstimateScore]:
    out = []
    for e in sorted(estimates, key=lambda e: (e.scope != "global", e.region_id)):
        hours, analog = actuals.get(e.region_id, (math.nan, math.nan))
        ok = math.isfinite(hours) and hours > 0
        actual = e.as_of_utc + timedelta(hours=hours) if ok else None
        p50 = e.hours_from_as_of["p50"]
        out.append(
            EstimateScore(
                estimate_id=e.estimate_id,
                scope=e.scope,
                region_id=e.region_id,
                as_of_utc=e.as_of_utc,
                actual_utc=actual.astimezone(UTC) if actual else None,
                p50_error_h=round(p50 - hours, 1) if ok else None,
                abs_error_h=round(abs(p50 - hours), 1) if ok else None,
                analog_abs_error_h=round(abs(analog - hours), 1) if ok else None,
                in_p25_p75=(e.p25_utc <= actual <= e.p75_utc) if actual else None,
                in_p10_p90=(e.p10_utc <= actual <= e.p90_utc) if actual else None,
            )
        )
    return out


def metric_rows(scores: Sequence[EstimateScore]) -> list[MetricRow]:
    rows: list[MetricRow] = []
    for scope in ("global", "region"):
        mine = [s for s in scores if s.scope == scope and s.abs_error_h is not None]
        if not mine:
            continue
        n = len(mine)
        mae = statistics.median(s.abs_error_h for s in mine if s.abs_error_h is not None)
        analog = statistics.median(s.analog_abs_error_h for s in mine if s.analog_abs_error_h is not None)
        in50 = sum(bool(s.in_p25_p75) for s in mine) / n
        in80 = sum(bool(s.in_p10_p90) for s in mine) / n
        common = {
            "n": n,
            "split": EvalSplit.DEV,
            "label": NumberLabel.S,
            "baseline_name": f"historical analog (Helene county median t90 from the peak); {ACTUAL_LABEL}",
        }
        rows += [
            MetricRow(
                metric=f"{PREFIX}.{scope}.p50_abs_error_h_median",
                value=round(mae, 1),
                unit="hours",
                baseline_value=round(analog, 1),
                threshold=round(analog, 1),
                direction="lower_is_better",
                passed=mae <= analog,
                **common,  # type: ignore[arg-type]
            ),
            MetricRow(
                metric=f"{PREFIX}.{scope}.within_p25_p75",
                value=round(in50, 4),
                unit="share",
                baseline_value=0.5,
                threshold=0.0,
                direction="higher_is_better",
                passed=True,
                **common,  # type: ignore[arg-type]
            ),
            MetricRow(
                metric=f"{PREFIX}.{scope}.within_p10_p90",
                value=round(in80, 4),
                unit="share",
                baseline_value=0.8,
                threshold=0.0,
                direction="higher_is_better",
                passed=True,
                **common,  # type: ignore[arg-type]
            ),
        ]
    return rows


def report(estimates: Sequence[EtrEstimate], command: str) -> tuple[EvalReport, list[EstimateScore]]:
    scores = score(estimates, simulated_actuals(estimates))
    from sgw.models.restoration.report import code_version

    doc = EvalReport(
        name="etr_story_scorecard",
        created_at=datetime.now(UTC).replace(microsecond=0),
        code_version=code_version(),
        llm_mode="replay",
        command=command,
        metrics=metric_rows(scores),
    )
    return doc, scores


def main() -> None:
    from sgw.reports.sources import load_estimates

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--estimates", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    command = f"uv run python -m sgw.reports.scorecard --estimates {a.estimates} --out {a.out}"
    doc, scores = report(load_estimates(a.estimates), command)
    body = doc.model_dump(mode="json") | {
        "actual_label": ACTUAL_LABEL,
        "estimates": [s.model_dump(mode="json") for s in scores],
    }
    a.out.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
