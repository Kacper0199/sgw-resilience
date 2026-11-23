"""Verification of the wind field against its defining equations."""

from __future__ import annotations

import numpy as np
import pytest

from sgw.generator.config import parse_utc
from sgw.generator.wind import (
    KT,
    TS_MS,
    Track,
    calm_after_peak,
    displace,
    distance_km,
    epoch,
    first_crossing,
    offsets_km,
    sustained_wind,
)

KW = {"holland_b": 1.5, "inner_exponent": 0.5, "r34_fallback": 1.5}


def _track(
    vmax_kt: float = 80.0, rmw_nmi: float = 30.0, r34: tuple[float, ...] = (200, 200, 200, 200)
) -> Track:
    rows = [
        ["2024-09-27T00:00:00Z", 31.0, -83.0, vmax_kt, 960, rmw_nmi, *r34],
        ["2024-09-27T12:00:00Z", 31.0, -83.0, vmax_kt, 960, rmw_nmi, *r34],
    ]
    return Track.from_rows(rows, parse_utc)


def _ring(track: Track, radius_km: float, az_deg: float) -> tuple[np.ndarray, np.ndarray]:
    dx = radius_km * np.sin(np.radians(az_deg))
    dy = radius_km * np.cos(np.radians(az_deg))
    lat, lon = displace(np.array([31.0]), np.array([-83.0]), np.array([dx]), np.array([dy]))
    return lat, lon


def _wind_at(track: Track, radius_km: float, az_deg: float = 45.0) -> float:
    t = np.array([epoch(parse_utc("2024-09-27T06:00:00Z"))])
    lat, lon = _ring(track, radius_km, az_deg)
    return float(sustained_wind(track, t, lat, lon, **KW)[0, 0])


def test_wind_equals_vmax_at_the_radius_of_maximum_wind() -> None:
    tr = _track()
    assert _wind_at(tr, 30 * 1.852) == pytest.approx(80 * KT, rel=2e-3)


def test_outer_profile_passes_through_34_kt_at_the_quadrant_radius() -> None:
    tr = _track()
    assert _wind_at(tr, 200 * 1.852) == pytest.approx(TS_MS, rel=2e-3)


def test_profile_decreases_outside_rmw_and_vanishes_beyond_the_taper() -> None:
    tr = _track()
    radii = np.linspace(60, 1000, 40)
    v = [_wind_at(tr, r) for r in radii]
    assert all(a >= b for a, b in zip(v, v[1:], strict=False))
    assert _wind_at(tr, 3.05 * 200 * 1.852) == 0.0


def test_no_wind_outside_the_track_time_span() -> None:
    tr = _track()
    t = np.array([epoch(parse_utc("2024-09-26T00:00:00Z"))])
    lat, lon = _ring(tr, 50.0, 45.0)
    assert sustained_wind(tr, t, lat, lon, **KW)[0, 0] == 0.0


def test_flat_profile_guard_for_storms_just_above_34_kt() -> None:
    tr = _track(vmax_kt=35.0, rmw_nmi=90.0, r34=(0, 110, 0, 0))
    assert _wind_at(tr, 1700.0, az_deg=45.0) < 1.0


def test_displacement_round_trip() -> None:
    lat, lon = displace(np.array([33.5]), np.array([-81.7]), np.array([12.0]), np.array([-7.0]))
    dx, dy = offsets_km(33.5, -81.7, lat, lon)
    assert float(dx[0]) == pytest.approx(12.0, abs=1e-3)
    assert float(dy[0]) == pytest.approx(-7.0, abs=1e-3)
    assert float(distance_km(33.5, -81.7, lat, lon)[0]) == pytest.approx(np.hypot(12.0, 7.0), abs=1e-3)


def test_crossing_helpers() -> None:
    times = np.arange(6.0)
    series = np.array([[1.0], [3.0], [5.0], [4.0], [2.0], [1.0]])
    assert first_crossing(series, times, 3.0)[0] == 1.0
    assert np.isnan(first_crossing(series, times, 9.0)[0])
    assert calm_after_peak(series, times, 3.0)[0] == 4.0


def test_helene_truth_field_peaks_at_augusta_at_the_observed_hour() -> None:
    from sgw.generator.config import load_scenario

    sc = load_scenario("helene")
    tr = Track.from_rows(sc["storm"]["track"], parse_utc)
    times = epoch(parse_utc("2024-09-27T00:00:00Z")) + np.arange(0, 24 * 3600, 900)
    v = sustained_wind(tr, times, np.array([33.37]), np.array([-81.96]), **KW)
    peak_hour = int((times[int(np.argmax(v[:, 0]))] - times[0]) // 3600)
    assert peak_hour in (8, 9, 10)
