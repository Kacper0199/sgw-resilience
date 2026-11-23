from __future__ import annotations

import json

import pytest

from sgw.contracts.eval_report import EvalReport
from sgw.contracts.vocab import EvalSplit
from sgw.models.restoration import artefact
from sgw.models.restoration.publish import estimates, story_run
from sgw.models.restoration.report import REPORT_PATH

GOLDEN_GLOBAL_P50_H = 79.4


def test_etr_report_is_k17_with_coverage_rows_for_both_populations_and_issue_times() -> None:
    report = EvalReport.model_validate(json.loads(REPORT_PATH.read_text(encoding="utf-8")))
    rows = {m.metric: m for m in report.metrics}
    for pop in ("regional", "global"):
        for off in (0, 24):
            stem = f"etr90.family_a_test.{pop}.issue_declared_peak_plus_{off}h"
            row = rows[f"{stem}.coverage80"]
            assert row.split is EvalSplit.DEV and row.n >= 1 and row.ci_low is not None
            for tail in ("coverage80_abs_error", "coverage50", "width80_median_rel", "width50_median_rel"):
                assert f"{stem}.{tail}" in rows
    for name in ("county_t50_median", "county_t90_median"):
        assert f"restoration.helene.{name}_rel_error_in_sample" in rows
    assert any(k.endswith("_not_fitted") for k in rows)
    assert all(k.endswith("_in_sample_world") for k in rows if ".story_seed." in k)
    assert report.command == "uv run sgw restoration eval"


def test_serving_artefact_matches_the_parameters_it_was_fitted_with() -> None:
    _, cals, doc = artefact.load()
    assert doc["data_hash"] == artefact.data_hash()
    assert {pop for pop, _ in cals} == {"regional", "global"}


def test_story_global_etr_is_stable() -> None:
    model, cals, _ = artefact.load()
    first = estimates(story_run(), 24.0, model, cals, members=40)[0]
    assert first.region_id == "GLOBAL"
    assert first.hours_from_as_of["p50"] == pytest.approx(GOLDEN_GLOBAL_P50_H, abs=0.05)
