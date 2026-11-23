from __future__ import annotations

import json

import numpy as np
import pytest

from sgw.generator.config import load_scenario
from sgw.generator.wind import Track
from sgw.models.hazard.ensemble import FIXTURES, advisory_members, forecast_window_peak_gust, scenario_hazard
from sgw.models.hazard.field import Points, point_features, splice
from sgw.models.hazard.hurdat2 import TRACKS_CSV, climatology_rmw_nmi, load_track, track_rows


def test_helene_track_from_hurdat2_equals_the_generator_scenario_track() -> None:
    ours = track_rows("helene")
    theirs = load_scenario("helene")["storm"]["track"]
    assert len(ours) == len(theirs)
    for a, b in zip(ours, theirs, strict=True):
        assert a[0] == b[0]
        assert a[1:4] == pytest.approx([float(v) for v in b[1:4]])
        assert a[5:10] == pytest.approx([float(v) for v in b[5:10]])


def test_pre_2021_fixes_get_the_climatology_rmw_and_are_flagged() -> None:
    text = TRACKS_CSV.read_text(encoding="utf-8")
    michael = [line for line in text.splitlines() if line.startswith("michael,")]
    filled = [line for line in michael if line.endswith("willoughby_rahn_2004")]
    assert len(filled) == len(michael) - 1
    assert next(line for line in michael if "2018-10-10T17:30:00Z" in line).endswith(
        ",10.0,90.0,140.0,100.0,80.0,hurdat2"
    )
    assert 15.0 < climatology_rmw_nmi(100.0, 30.0) < 30.0


def _points() -> Points:
    return Points(("near", "far"), np.array([31.0, 34.5]), np.array([-83.5, -79.0]))


def test_features_grow_with_intensity_and_fall_with_distance() -> None:
    track = load_track("michael")
    strong = Track(track.t, track.lat, track.lon, track.vmax * 1.2, track.rmw, track.r34)
    base = point_features(track, _points())
    more = point_features(strong, _points())
    assert (more["peak_gust_ms"] >= base["peak_gust_ms"] - 1e-9).all()
    assert base.loc[0, "min_dist_km"] < base.loc[1, "min_dist_km"]
    assert (base["hours_gust_ge_20"] >= base["hours_ts"] * 0).all()


def test_splice_keeps_analysis_before_the_forecast_start() -> None:
    analysis = load_track("helene")
    forecast = Track(
        analysis.t[10:] + 0.0,
        analysis.lat[10:] + 1.0,
        analysis.lon[10:],
        analysis.vmax[10:],
        analysis.rmw[10:],
        analysis.r34[10:],
    )
    s = splice(analysis, forecast)
    assert np.array_equal(s.t[:10], analysis.t[:10])
    assert np.array_equal(s.lat[10:], forecast.lat)


def test_decision_points_follow_wp06_ensemble_order() -> None:
    data = json.loads((FIXTURES / "helene" / "ensemble.json").read_text(encoding="utf-8"))
    assert list(scenario_hazard("helene").decision_points.points.ids) == data["points"]["ids"]


@pytest.mark.parametrize("label", ["N", "N+1"])
def test_member_peak_gusts_reproduce_wp06_ensemble_json(label: str) -> None:
    data = json.loads((FIXTURES / "helene" / "ensemble.json").read_text(encoding="utf-8"))
    ref = next(a for a in data["advisories"] if a["advisory_label"] == label)
    expected = np.array([m["peak_gust_ms"] for m in ref["members"]])
    ours = forecast_window_peak_gust("helene", label)
    assert ours.shape == expected.shape
    assert np.abs(ours - expected).max() <= 0.051


def test_members_are_deterministic_and_member_zero_is_the_official_forecast() -> None:
    a = advisory_members("helene", "N")
    assert len(a) == 1 + int(scenario_hazard("helene").family["forecast.members"])
    advisory_members.cache_clear()
    b = advisory_members("helene", "N")
    assert a[0].features.equals(b[0].features)
    assert a[5].features.equals(b[5].features)
