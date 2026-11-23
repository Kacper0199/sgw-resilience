from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from sgw.generator.scenarios import bluesky
from sgw.generator.scenarios import heat as heat_sc
from sgw.generator.scenarios.weather import AGS_HOURLY, load_hourly
from sgw.models.heat import hotspot as hs
from sgw.models.heat.ampacity import Conductor, ampacity, heat_terms
from sgw.models.heat.thermal import DISTRIBUTION_ONAN, ONAF, faa, simulate, steady_state

DRAKE = Conductor("Drake 795 kcmil ACSR", 0.02814, 7.283e-5, 8.688e-5, 0.8, 0.8, 100.0)


def test_iec_steady_state_reference() -> None:
    for cooling in (DISTRIBUTION_ONAN, ONAF):
        oil, hot = steady_state(cooling, 1.0, 30.0)
        assert oil == pytest.approx(85.0)
        assert hot == pytest.approx(108.0)


def test_ageing_rate_reference_values() -> None:
    assert [round(faa(t), 2) for t in (110.0, 120.0, 140.0)] == [1.0, 2.71, 17.2]


@pytest.mark.parametrize("cooling", [DISTRIBUTION_ONAN, ONAF])
def test_ode_relaxes_to_steady_state_from_a_cold_start(cooling) -> None:
    n = 60 * 24
    trace = simulate(cooling, [1.2] * n, [35.0] * n, 1.0, initial=(35.0, 0.0, 0.0))
    _, hot = steady_state(cooling, 1.2, 35.0)
    assert trace.theta_h[-1] == pytest.approx(hot, abs=0.05)


def test_step_response_converges_when_the_step_is_halved() -> None:
    n = 60 * 12
    k = [0.8] * 60 + [1.3] * (n - 60)
    ta = [30.0] * n
    one = simulate(DISTRIBUTION_ONAN, k, ta, 1.0)
    half = simulate(DISTRIBUTION_ONAN, [x for x in k for _ in (0, 1)], [x for x in ta for _ in (0, 1)], 0.5)
    assert max(abs(a - b) for a, b in zip(one.theta_h, half.theta_h[::2], strict=True)) < 0.3
    with pytest.raises(ValueError):
        simulate(DISTRIBUTION_ONAN, k, ta, 5.0)


def test_ieee738_drake_example() -> None:
    qs_example = 22.44
    solar = qs_example / (DRAKE.absorptivity * DRAKE.diameter_m)
    h = heat_terms(DRAKE, 40.0, 0.61, solar, elevation_m=0.0)
    assert h.q_convection == pytest.approx(81.93, rel=0.01)
    assert h.q_radiation == pytest.approx(39.1, rel=0.01)
    assert h.ampacity_a == pytest.approx(1025.0, rel=0.01)


def test_ampacity_monotone_in_wind_and_ambient() -> None:
    c = hs.conductor()
    assert ampacity(c, 35.0, 0.3, 900.0) < ampacity(c, 35.0, 0.61, 900.0) < ampacity(c, 35.0, 2.0, 900.0)
    assert ampacity(c, 38.0, 0.61, 900.0) < ampacity(c, 30.0, 0.61, 900.0)
    assert ampacity(c, 35.0, 0.61, 1000.0) < ampacity(c, 35.0, 0.61, 0.0)


def test_load_shape_peaks_at_17_local() -> None:
    assert hs.shape(17.0) == pytest.approx(1.0)
    assert hs.shape(5.0) == pytest.approx(0.75 / 1.25)
    assert hs.load_factor(datetime(2024, 7, 15, 21, tzinfo=UTC), 21.0) == pytest.approx(1.0)


def test_heat_trigger_threshold_is_out_of_sample_and_fires_in_the_window() -> None:
    trig = heat_sc.trigger()
    assert trig.calibration_days >= 85
    first, last = heat_sc.window_dates()
    assert trig.fires_in(first, last) == [date(2024, 7, 15)]
    assert all(d.year == 2023 or d.year == 2024 for d in trig.fire_days)


def test_blue_sky_week_has_no_hot_day() -> None:
    trig = heat_sc.trigger()
    first, last = (t.astimezone(hs.EASTERN).date() for t in bluesky.WINDOW)
    assert not [d for d in trig.hot_days if first <= d <= last]


@pytest.fixture(scope="module")
def grid_and_t2() -> tuple[hs.Grid, hs.UnitResult]:
    grid = hs.minute_grid(load_hourly(AGS_HOURLY), heat_sc.SPIN_UP_START, heat_sc.WINDOW[1])
    unit = next(u for u in hs.params()["units"] if u["asset_id"] == hs.params()["line"]["transformer_id"])
    return grid, hs.run_unit(unit, grid)


def test_h2_seeded_insight_still_air_line_binds_first(grid_and_t2) -> None:
    grid, t2 = grid_and_t2
    rating = hs.binding_check(t2, grid, *heat_sc.WINDOW, float(hs.value("wind", "rating_basis_ms")))
    still = hs.binding_check(t2, grid, *heat_sc.WINDOW, float(hs.value("wind", "still_air_ms")))
    assert rating.binding == "transformer" and rating.peak_line_loading_pct < 100.0
    assert still.binding == "line" and still.line_limit_utc is not None
    assert still.transformer_limit_utc is not None and still.line_limit_utc < still.transformer_limit_utc


def test_hot_spot_table_stays_in_the_plausibility_band(grid_and_t2) -> None:
    grid, _ = grid_and_t2
    for unit in hs.params()["units"]:
        s = hs.summarise(hs.run_unit(unit, grid), *heat_sc.WINDOW)
        assert 95.0 <= s["theta_h_peak_c"] <= 140.0, unit["asset_id"]
        assert s["night_min_theta_h_c"] < s["theta_h_peak_c"]
        assert s["alarm"] in ("watch", "warning")
