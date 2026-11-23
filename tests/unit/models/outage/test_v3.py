from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from sgw.models.hazard.asos import load_asos
from sgw.models.hazard.field import point_features
from sgw.models.hazard.hurdat2 import EXTENDED_STORMS, load_track
from sgw.models.hazard.series import gust_series
from sgw.models.outage import experiment_v3 as v3
from sgw.models.outage.dataset import county_points
from sgw.models.outage.glm import (
    F2_COVARIATES,
    BoostedResidual,
    ProbitCurve,
    WindCalibration,
    dersimonian_laird,
)
from sgw.models.outage.labels_v3 import load_labels_v3


def synthetic(
    storms: int = 20, counties: int = 120, tau: float = 0.5, ante_coef: float = 0.3, seed: int = 7
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(storms):
        u = rng.normal(0.0, tau)
        gust = rng.uniform(10.0, 60.0, counties)
        h20 = rng.uniform(0.0, 12.0, counties)
        ante = rng.uniform(0.0, 150.0, counties)
        dens = rng.uniform(2.0, 200.0, counties)
        z = (ante - 75.0) / 43.0
        eta = -9.0 + 2.0 * np.log(gust) + 0.2 * np.log1p(h20) + ante_coef * z - 0.1 * np.log(dens) + u
        cust = rng.integers(2_000, 200_000, counties).astype(float)
        frac = rng.binomial(cust.astype(int), norm.cdf(eta)) / cust
        rows.append(
            pd.DataFrame(
                {
                    "storm": f"s{s:02d}",
                    "peak_frac": frac,
                    "customers_mcc": cust,
                    "peak_gust_ms": gust,
                    "hours_gust_ge_20": h20,
                    "rain_antecedent_14d_mm": ante,
                    "customer_density": dens,
                    "vmax_ms_closest": rng.uniform(15.0, 60.0, counties),
                    "speed_kmh_closest": rng.uniform(5.0, 40.0, counties),
                    "ep_mobile": rng.uniform(3.0, 50.0, counties),
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def test_gust_series_reduces_to_the_point_features_of_the_shared_hazard_function() -> None:
    points, _ = county_points()
    track = load_track("debby")
    ser = gust_series(track, points)
    feats = point_features(track, points)
    np.testing.assert_allclose(ser.gust.max(axis=0), feats["peak_gust_ms"], atol=1e-3)
    np.testing.assert_allclose(ser.hours_above(20.0), feats["hours_gust_ge_20"], atol=1e-3)
    assert (ser.hours_above(20.0, 1.5) >= ser.hours_above(20.0)).all()


def test_dersimonian_laird_recovers_between_storm_variance() -> None:
    rng = np.random.default_rng(1)
    u = rng.normal(1.0, 0.6, 4000) + rng.normal(0.0, 0.1, 4000)
    mean, tau2 = dersimonian_laird(u, np.full(4000, 0.01))
    assert mean == pytest.approx(1.0, abs=0.05)
    assert tau2 == pytest.approx(0.36, abs=0.04)


def test_probit_curve_recovers_slopes_and_storm_spread() -> None:
    fit = ProbitCurve.fit(synthetic(storms=30), F2_COVARIATES)
    coef = dict(zip(fit.names, fit.coef, strict=True))
    assert coef["ln_gust"] == pytest.approx(2.0, abs=0.1)
    assert coef["z_ante"] == pytest.approx(0.3, abs=0.05)
    assert 0.1 < fit.tau2 < 0.6
    assert set(fit.storm_u) == {f"s{s:02d}" for s in range(30)}


def test_sign_rule_drops_a_wrong_signed_hazard_covariate() -> None:
    fit = ProbitCurve.fit(synthetic(ante_coef=-0.4), F2_COVARIATES)
    assert "z_ante" in fit.dropped
    assert "z_ante" not in fit.names


def test_marginal_total_exceeds_median_storm_total_for_a_low_curve() -> None:
    frame = synthetic()
    fit = ProbitCurve.fit(frame, F2_COVARIATES)
    test = frame[frame["storm"] == "s00"]
    p = fit.predict(test)
    assert p.total > float((p.point * test["customers_mcc"]).sum())
    assert p.total_lo80 is not None and p.total_hi80 is not None
    assert p.total_lo80 < p.total < p.total_hi80


def test_boosted_residual_is_monotone_in_gust() -> None:
    frame = synthetic()
    m1 = BoostedResidual.fit(frame, ProbitCurve.fit(frame, F2_COVARIATES))
    probe = frame.iloc[:50].copy()
    lo = m1.predict(probe).point
    hi = m1.predict(probe.assign(peak_gust_ms=probe["peak_gust_ms"] * 1.3)).point
    assert (hi >= lo - 1e-12).all()


def test_wind_calibration_recovers_a_known_bias() -> None:
    rng = np.random.default_rng(3)
    n = 400
    model = rng.uniform(13.0, 60.0, n)
    coast = rng.uniform(1.0, 400.0, n)
    obs = model * np.exp(-0.2 - 0.1 * np.log1p(coast) + rng.normal(0.0, 0.05, n))
    rows = pd.DataFrame(
        {
            "storm": "x",
            "obs_peak_gust_ms": obs,
            "report_share": 1.0,
            "peak_gust_ms": model,
            "dist_coast_km": coast,
            "vmax_ms_closest": rng.uniform(15.0, 60.0, n),
            "speed_kmh_closest": rng.uniform(5.0, 40.0, n),
        }
    )
    cal = WindCalibration.fit(rows)
    assert cal.coef[2] == pytest.approx(-0.1, abs=0.02)
    expected = np.exp(-0.2 - 0.1 * np.log1p(coast))
    np.testing.assert_allclose(cal.factor(rows), expected, rtol=0.05)
    censored = rows.assign(report_share=0.5)
    assert len(WindCalibration.usable(censored)) == 0


def test_holm_steps_down_and_stays_monotone() -> None:
    out = v3.holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert out["a"]["holm_p"] == pytest.approx(0.03)
    assert out["c"]["holm_p"] == pytest.approx(0.06)
    assert out["b"]["holm_p"] == pytest.approx(0.06)


def test_derived_v3_tables_cover_every_storm_and_county() -> None:
    labels = load_labels_v3()
    assert len(labels) == len(EXTENDED_STORMS) * 123
    assert labels["peak_frac_l2"].between(0.0, 1.0).all()
    asos = load_asos()
    assert set(asos["storm"]) == {s.name for s in EXTENDED_STORMS}
    assert asos["dist_coast_km"].notna().all()


@pytest.fixture(scope="module")
def real() -> dict[str, Any]:
    frame = v3.v3_frame()
    return {"frame": frame, "asos": load_asos(), "series": v3.storm_series(frame)}


def test_held_out_storm_labels_and_asos_never_reach_any_fit(real: dict[str, Any]) -> None:
    held = "ian"
    v3._init(real["frame"], real["asos"], real["series"], v3.METHODS)
    _, base, _ = v3.run_out(frozenset({held}))
    frame = real["frame"].copy()
    mask = frame["storm"] == held
    frame.loc[mask, "peak_frac"] = np.random.default_rng(0).uniform(0.0, 1.0, int(mask.sum()))
    asos = real["asos"].copy()
    asos.loc[asos["storm"] == held, "obs_peak_gust_ms"] = 99.0
    v3._init(frame, asos, real["series"], v3.METHODS)
    _, spoiled, _ = v3.run_out(frozenset({held}))
    for m in v3.METHODS:
        np.testing.assert_array_equal(base[held][m].point, spoiled[held][m].point)
        assert base[held][m].total == spoiled[held][m].total


def test_calibrated_duration_does_not_depend_on_which_rows_the_frame_keeps(real: dict[str, Any]) -> None:
    cal = WindCalibration.fit(real["asos"])
    full = v3.with_calibration(real["frame"], cal, real["series"])
    sub = real["frame"].iloc[::3].reset_index(drop=True)
    part = v3.with_calibration(sub, cal, real["series"])
    merged = full.merge(part, on=["storm", "fips"], suffixes=("", "_sub"))
    assert len(merged) == len(sub)
    np.testing.assert_allclose(merged["hours_gust_cal_ge_20"], merged["hours_gust_cal_ge_20_sub"])


def test_summary_splits_the_pooled_ratio_and_names_band_misses() -> None:
    def cell(total: float, lo: float, hi: float, obs: float, rho: float) -> dict[str, Any]:
        return {
            "county_mae": 1.0,
            "predicted_total": total,
            "ln_p_over_o": float(np.log(total / obs)),
            "abs_ln_p_over_o": abs(float(np.log(total / obs))),
            "rel_total_error": abs(total - obs) / obs,
            "spearman": rho,
            "total_lo80": lo,
            "total_hi80": hi,
            "total_hit_80": int(lo <= obs <= hi),
        }

    rows = [
        {
            "storm": "helene",
            "observed_total": 1000,
            "F2": cell(400, 100, 900, 1000, 0.6),
            "B3": cell(300, 300, 300, 1000, 0.4),
        },
        {
            "storm": "nestor",
            "observed_total": 10,
            "F2": cell(40, 5, 100, 10, 0.5),
            "B3": cell(5, 5, 5, 10, 0.6),
        },
    ]
    s = v3.summarise(rows)
    assert s["F2"]["pooled_p_over_o_large8"] == pytest.approx(0.4)
    assert s["F2"]["pooled_p_over_o_other"] == pytest.approx(4.0)
    assert s["F2"]["total_band_missed"] == ["helene (above)"]
    assert s["F2"]["versus"]["B3"]["spearman_better"] == 1
