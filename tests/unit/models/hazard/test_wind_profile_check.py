from __future__ import annotations

import pytest

from sgw.models.hazard.validation import station_check


@pytest.mark.parametrize("label", ["N", "N+1"])
def test_wind_profile_spread_contains_the_observed_gust_at_all_five_scored_stations(label: str) -> None:
    result = station_check(label)
    assert result["stations_scored"] == 5
    assert result["inside_spread"] == 5
    vld = next(s for s in result["stations"] if s["station"] == "VLD")
    assert vld["censored"] and vld["observed_ms"] < vld["best_track_model_ms"]
