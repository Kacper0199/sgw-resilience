from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sgw.models.hazard.hurdat2 import EXTENDED_STORMS, STORMS
from sgw.models.outage import experiment
from sgw.models.outage.dataset import extended_frame, training_frame
from sgw.models.outage.eaglei import load_extended_targets, load_targets
from sgw.models.outage.model import OutageModel, load


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return extended_frame()


def test_extended_table_keeps_the_wp11_rows_and_adds_every_registered_storm() -> None:
    ext = load_extended_targets()
    assert len(ext) == len(EXTENDED_STORMS) * 123
    assert list(dict.fromkeys(ext["storm"])) == [s.name for s in EXTENDED_STORMS]
    old = load_targets()
    names = [s.name for s in STORMS]
    kept = ext[ext["storm"].isin(names)].sort_values(["storm", "fips"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(kept, old.sort_values(["storm", "fips"]).reset_index(drop=True))
    assert ext["peak_frac"].between(0.0, 1.0).all()


def test_extended_frame_features_match_the_wp11_frame_on_the_four_storms(frame: pd.DataFrame) -> None:
    old = training_frame()
    cols = list(old.columns)
    sub = frame[frame["storm"].isin(old["storm"])][cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(sub, old)
    assert not frame["hours_centre_within_200km"].isna().any()


def test_prior_offset_and_log_intervals_survive_save_and_load(frame: pd.DataFrame, tmp_path) -> None:  # type: ignore[no-untyped-def]
    storms = ["michael", "ian", "debby", "irma"]
    train = frame[frame["storm"].isin(storms)]
    test = frame[frame["storm"] == "helene"]
    model = OutageModel.fit(train, prior_offset=True, interval_space="log")
    model.save(tmp_path / "m")
    again = load(tmp_path / "m")
    assert again.raw.prior_offset and again.interval_space == "log"
    a, b = model.predict(test), again.predict(test)
    np.testing.assert_allclose(a.mean, b.mean, atol=1e-12)
    for name in a.intervals:
        np.testing.assert_allclose(a.intervals[name][1], b.intervals[name][1], atol=1e-12)
    lo80, hi80 = a.intervals["80"]
    lo95, hi95 = a.intervals["95"]
    assert (lo95 <= lo80).all() and (hi80 <= hi95).all()


def test_nested_selection_never_fits_on_the_held_out_storm(frame: pd.DataFrame) -> None:
    storms = ["michael", "ian", "debby", "helene"]
    sub = frame[frame["storm"].isin(storms)].reset_index(drop=True)
    used: list[tuple[str, frozenset[str]]] = []
    original = experiment.FitCache.get

    def spy(self: experiment.FitCache, variant: str, out: frozenset[str]):  # type: ignore[no-untyped-def]
        used.append((variant, out))
        return original(self, variant, out)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(experiment.FitCache, "get", spy)
        mp.setattr(experiment, "WORKERS", 2)
        result = experiment.run(sub)
    rows = {r["storm"]: r for r in result["storms"]}
    assert set(rows) == set(storms)
    per_outer = len(experiment.VARIANTS) * len(storms)
    assert len(used) == per_outer * len(storms)
    for i, held in enumerate(sorted(storms)):
        chunk = used[i * per_outer : (i + 1) * per_outer]
        assert all(held in out and len(out) in (1, 2) for _, out in chunk)
    for r in rows.values():
        assert r["S"]["variant"] in experiment.VARIANTS
        assert r["S"]["interval_space"] in experiment.SPACES
        assert r["V5"]["weight_model"] in experiment.BLEND_WEIGHTS


def test_fitted_fragility_recovers_its_generating_curve() -> None:
    gust = np.linspace(15, 70, 200)
    truth = experiment.FittedFragility(45.0, 0.3)
    data = pd.DataFrame({"peak_gust_ms": gust, "customers_mcc": 1000.0})
    data["peak_frac"] = truth.predict(data)
    fit = experiment.FittedFragility.fit(data)
    assert fit.median_ms == pytest.approx(45.0) and fit.beta == pytest.approx(0.3)


def test_committed_v2_report_is_k17_valid_with_every_storm_beside_both_baselines() -> None:
    from sgw.contracts.eval_report import EvalReport
    from sgw.contracts.vocab import EvalSplit

    report = EvalReport.model_validate_json(experiment.REPORT_V2.read_text(encoding="utf-8"))
    names = {m.metric for m in report.metrics}
    for storm in EXTENDED_STORMS:
        for metric in ("county_mae", "county_mae_vs_fragility_fitted", "coverage_80", "rel_total_error"):
            assert f"{experiment.PREFIX_V2}.{storm.name}.{metric}" in names
    for metric in (
        "pre_registered_s.storms_beats_wind_threshold_county_mae",
        "storms_s2_same_as_fragility_fitted_county_mae",
        "s2_vs_fragility_fitted_wilcoxon_p",
        "storms_s2_under_predicted_total",
        "s2_share_of_observed_outages_forecast",
        "storms_s2_spearman_better_than_wind_threshold",
        "large_storms.storms_s2_beats_wind_threshold_county_mae",
        "sensitivity_2018_on_refit.fragility_fitted.median_county_mae_ratio_vs_wind_threshold",
    ):
        assert f"{experiment.PREFIX_V2}.{metric}" in names
    for storm in EXTENDED_STORMS:
        assert f"{experiment.PREFIX_V2}.pre_registered_s.{storm.name}.county_mae" in names
    assert report.metrics[0].metric.endswith(".county_mae")
    assert all(m.split is EvalSplit.REAL_LOSO and m.baseline_name for m in report.metrics)
    assert report.command == experiment.COMMAND_V2


def test_serving_candidate_knows_only_storms_before_helene_and_reproduces_its_reported_helene_row(
    frame: pd.DataFrame,
) -> None:
    import json

    model = load(experiment.ARTEFACT_DIR / experiment.SERVING_CANDIDATE)
    assert "helene" not in model.trained_on and "chantal" not in model.trained_on
    assert set(model.trained_on) == set(experiment.serving_storms(frame))
    detail = json.loads(experiment.DETAIL_PATH.read_text(encoding="utf-8"))
    helene = frame[frame["storm"] == "helene"].reset_index(drop=True)
    fc = model.predict(helene)
    total = float((fc.mean * helene["customers_mcc"]).sum())
    assert total == pytest.approx(detail["serving_candidate"]["helene"]["predicted_total"], abs=1.0)


def test_versus_counts_ties_as_ties_and_tests_only_the_untied_storms() -> None:
    rows = [
        {"a": {"county_mae": a}, "b": {"county_mae": b}} for a, b in [(5, 5), (4, 5), (6, 5), (3, 5), (5, 5)]
    ]
    vs = experiment.versus(rows, "a", "b")
    assert (vs["same"], vs["better"], vs["worse"]) == (2, 2, 1)
    assert 0.0 <= vs["wilcoxon_p_untied"] <= 1.0
