from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from sgw.contracts.eval_report import EvalReport
from sgw.models.surge.fit import DETAIL_JSON, PARAMS_JSON, REPORT_JSON, params_from
from sgw.models.surge.read import list_outage_surges

PINNED: dict[str, float] = {
    "outage_surge.test.event_recall": 0.4787,
    "outage_surge.test.recall_diff_vs_fixed_share": 0.2212,
    "outage_surge.test.recall_diff_vs_rolling_z": 0.1641,
    "outage_surge.test.false_alarms_per_county_month": 0.4075,
    "outage_surge.test.delay_h_median": 0.6167,
    "outage_surge.test.precision_lower_bound": 0.3855,
    "outage_surge.test.confidence_brier": 0.2031,
    "outage_surge.helene.tropical_episode_recall": 0.8073,
}


@pytest.fixture(scope="module")
def report() -> EvalReport:
    return EvalReport.model_validate_json(REPORT_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def detail() -> dict:
    return json.loads(DETAIL_JSON.read_text(encoding="utf-8"))


def test_report_is_k17_with_baselines_and_n(report: EvalReport) -> None:
    assert report.name == "outage_surge"
    assert all(r.n >= 1 and r.baseline_name for r in report.metrics)
    assert {r.split for r in report.metrics} == {"heldout"}


def test_pinned_numbers(report: EvalReport) -> None:
    values = {r.metric: r.value for r in report.metrics}
    for metric, value in PINNED.items():
        assert values[metric] == pytest.approx(value, abs=1e-4), metric


def test_no_beats_claim_under_the_registered_rule(detail: dict) -> None:
    assert detail["beats_both_tuned_baselines"] is False
    assert detail["fa_budget_per_county_month"] == 0.25


def test_beats_claim_matches_its_rule(detail: dict) -> None:
    c = detail["contrasts"]
    rule = all(
        c[b]["ci_low"] > 0 and c[b]["fa_model"] <= c[b]["fa_baseline"] for b in ("fixed_share", "rolling_z")
    )
    assert detail["beats_both_tuned_baselines"] is rule


def test_served_params_are_the_chosen_model(detail: dict) -> None:
    served = json.loads(PARAMS_JSON.read_text(encoding="utf-8"))
    assert params_from(served["params"]) == params_from(detail["chosen"]["robust_cusum"])
    assert served["fitted_on"] == detail["split"]["train"]
    assert len(served["counties"]) == detail["counties"] == 123


def test_serving_path_reproduces_the_eval_helene_run(detail: dict) -> None:
    hel = detail["helene"]
    lo, hi = (pd.Timestamp(t) for t in hel["window_utc"])
    served = list_outage_surges(datetime(2024, 10, 1, tzinfo=UTC), onset_in_window=False)
    window = [s for s in served.surges if lo <= pd.Timestamp(s.detected_at) < hi]
    assert len(window) == hel["surges"]
    assert len({s.fips for s in window}) == hel["counties_with_surge"]
    assert min(s.detected_at for s in window).isoformat() == hel["first_detected_at"]
