from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from sgw.contracts.eval_report import EvalReport
from sgw.contracts.vocab import EvalSplit
from sgw.models.hazard.hurdat2 import STORMS
from sgw.models.outage import backtest
from sgw.models.outage.baseline import WindThreshold, fragility_prior
from sgw.models.outage.dataset import storm_features, training_frame, with_exposure
from sgw.models.outage.eaglei import MANIFEST_JSON, TARGETS_CSV, load_targets
from sgw.models.outage.model import INTERVALS, OutageModel, load


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return training_frame()


def test_committed_tables_match_their_manifest() -> None:
    manifest = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
    for name, digest in manifest["outputs_sha256"].items():
        assert hashlib.sha256((TARGETS_CSV.parent / name).read_bytes()).hexdigest() == digest
    assert manifest["licence"] == "CC BY 4.0"


def test_targets_reproduce_the_verified_helene_and_debby_figures() -> None:
    t = load_targets()
    assert len(t) == 4 * 123
    helene = t[t["storm"] == "helene"]
    assert int((helene["peak_excess"] >= 1000).sum()) == 116
    assert int((t[t["storm"] == "debby"]["peak_excess"] >= 1000).sum()) == 55
    assert helene["peak_out"].sum() == pytest.approx(2_494_455, rel=0.01)
    assert t["peak_frac"].between(0.0, 1.0).all()


def test_features_join_every_county_and_storm(frame: pd.DataFrame) -> None:
    assert len(frame) == 4 * 123
    assert set(frame["storm"]) == {s.name for s in STORMS}
    assert not frame[list(OutageModel.__dataclass_fields__["features"].default)].isna().any().any()


def test_each_fold_trains_without_the_held_out_storm(
    frame: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[set[str]] = []
    original = WindThreshold.fit.__func__  # type: ignore[attr-defined]

    def spy(cls: type[WindThreshold], data: pd.DataFrame) -> WindThreshold:
        seen.append(set(data["storm"]))
        return original(cls, data)

    monkeypatch.setattr(WindThreshold, "fit", classmethod(spy))
    fold = backtest.run_fold(frame, "ian")
    assert "ian" not in fold.model.trained_on
    assert seen == [{"michael", "debby", "helene"}]
    assert set(fold.frame["storm"]) == {"ian"}


def test_conformal_fans_are_nested_and_hold_the_median(frame: pd.DataFrame) -> None:
    model = OutageModel.fit(frame[frame["storm"] != "debby"])
    fc = model.predict(frame[frame["storm"] == "debby"])
    lo50, hi50 = fc.intervals["50"]
    lo80, hi80 = fc.intervals["80"]
    lo95, hi95 = fc.intervals["95"]
    assert (lo95 <= lo80).all() and (lo80 <= lo50).all() and (lo50 <= fc.p50 + 1e-12).all()
    assert (fc.p50 <= hi50 + 1e-12).all() and (hi50 <= hi80).all() and (hi80 <= hi95).all()
    assert (np.diff(fc.quantiles, axis=1) >= 0).all()
    assert set(INTERVALS) == {"50", "80", "95"}


def test_wind_threshold_baseline_recovers_a_step_rule() -> None:
    gust = np.linspace(10, 50, 81)
    data = pd.DataFrame(
        {
            "peak_gust_ms": gust,
            "customers_mcc": 1000,
            "peak_frac": np.where(gust >= 30, 0.4, 0.05),
            "storm": "x",
        }
    )
    fit = WindThreshold.fit(data)
    assert fit.threshold_ms == 30.0
    assert fit.share_above == pytest.approx(0.4)
    assert fit.share_below == pytest.approx(0.05)
    assert fragility_prior(pd.DataFrame({"peak_gust_ms": [50.0]}))[0] == pytest.approx(0.5)


def test_committed_report_is_k17_valid_with_every_storm_beside_the_baseline() -> None:
    report = EvalReport.model_validate_json(backtest.REPORT_PATH.read_text(encoding="utf-8"))
    names = {m.metric for m in report.metrics}
    for storm in STORMS:
        for metric in (
            "county_mae",
            "spearman",
            "coverage_80",
            "coverage_95",
            "rel_total_error",
            "worst_miss",
        ):
            assert f"{backtest.PREFIX}.{storm.name}.{metric}" in names
    assert report.metrics[0].metric.endswith(".county_mae")
    assert all(m.ci_low is None and m.ci_high is None for m in report.metrics)
    assert all(m.split is EvalSplit.REAL_LOSO and m.n >= 1 and m.baseline_name for m in report.metrics)
    assert report.command == backtest.COMMAND


def test_rerun_reproduces_the_committed_report_and_serving_model(tmp_path: pytest.TempPathFactory) -> None:
    result = backtest.run_backtest(write=True, report_path=tmp_path / "r.json", artefacts=tmp_path)  # type: ignore[operator]
    committed = EvalReport.model_validate_json(backtest.REPORT_PATH.read_text(encoding="utf-8"))
    fresh = {m.metric: m.value for m in result["report"].metrics}
    assert {m.metric: m.value for m in committed.metrics} == fresh
    for name in ("mean.txt", "q0500.txt", "card.json"):
        a = (tmp_path / backtest.SERVING_MODEL / name).read_bytes()  # type: ignore[operator]
        b = (backtest.ARTEFACT_DIR / backtest.SERVING_MODEL / name).read_bytes()
        assert a == b, name


def test_serving_model_was_trained_without_helene_and_reproduces_its_backtest_predictions() -> None:
    model = load(backtest.ARTEFACT_DIR / backtest.SERVING_MODEL)
    assert model.trained_on == ["debby", "ian", "michael"]
    feats = storm_features("helene")
    targets = load_targets()
    helene = targets[targets["storm"] == "helene"].merge(feats, on=["storm", "fips"])
    x = with_exposure(helene, helene["customers_mcc"])
    served = model.predict(x).mean * helene["customers_mcc"].to_numpy()
    preds = pd.read_csv(backtest.ARTEFACT_DIR / "loso_predictions.csv", dtype={"fips": str})
    expected = (
        preds[preds["storm"] == "helene"].set_index("fips").loc[helene["fips"], "model_mean_out"].to_numpy()
    )
    assert np.abs(served - expected).max() <= 0.06


def test_detail_labels_the_hindcast_and_reports_capped_and_uncapped_totals() -> None:
    detail = json.loads((backtest.ARTEFACT_DIR / "loso_detail.json").read_text(encoding="utf-8"))
    assert "hindcast, observed track" in detail["label"]
    assert "uncalibrated across storm types" in detail["intervals"]
    helene = next(s for s in detail["storms"] if s["storm"] == "helene")
    assert helene["observed_total_out_uncapped"] > helene["observed_total_out"]
    assert "lightly tuned" in detail["fragility_baseline"]


def test_ties_are_not_wins() -> None:
    summary = {
        "storm": "x",
        "counties": 3,
        "model": {
            "county_mae_out": 1.0,
            "spearman": 0.5,
            "coverage_80": 0.8,
            "coverage_95": 0.9,
            "rel_total_error": 0.5,
            "worst_miss": {"abs_error": 1},
        },
        "baseline": {
            "county_mae_out": 1.0,
            "spearman": 0.5,
            "rel_total_error": 0.5,
            "worst_miss": {"abs_error": 1},
        },
        "fragility": {"rel_total_error": 0.5},
    }
    rows = backtest.metric_rows([summary], [{"storm": "x", "county_mae_out": 1.0}])
    assert rows[-1].value == 0.0
