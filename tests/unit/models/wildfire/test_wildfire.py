from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest

from sgw.generator.scenarios import fireweather as fwm
from sgw.generator.scenarios import tablerock
from sgw.generator.scenarios.bluesky import WINDOW as BLUE_WINDOW
from sgw.models.wildfire import ranking as rk
from sgw.models.wildfire import trigger as tr
from sgw.models.wildfire.indices import ffwi, kbdi_series


def f_to_c(f: float) -> float:
    return (f - 32.0) / 1.8


MPH = 1.0 / 2.236936


@pytest.mark.parametrize(
    ("t_f", "rh", "mph", "expected"),
    [(90.0, 25.0, 20.0, 47.0), (95.0, 15.0, 30.0, 80.0), (85.0, 70.0, 10.0, 13.0)],
)
def test_ffwi_matches_r02_reference_values(t_f: float, rh: float, mph: float, expected: float) -> None:
    assert ffwi(f_to_c(t_f), rh, mph * MPH) == pytest.approx(expected, abs=1.0)


def test_ffwi_rises_with_wind_and_falls_with_humidity() -> None:
    assert ffwi(30.0, 20.0, 2.0) < ffwi(30.0, 20.0, 8.0) < ffwi(30.0, 20.0, 14.0)
    assert ffwi(30.0, 15.0, 8.0) > ffwi(30.0, 40.0, 8.0) > ffwi(30.0, 80.0, 8.0)
    with pytest.raises(ValueError):
        ffwi(30.0, 101.0, 5.0)


def test_kbdi_severe_drought_reference_and_bounds() -> None:
    days = [(date(2023, 7, 1) + timedelta(days=i), f_to_c(95.0), 0.0) for i in range(30)]
    series = kbdi_series(days, 50.0, start=300.0)
    assert series[-1].kbdi == pytest.approx(657.0, abs=5.0)
    long = kbdi_series([(d, 45.0, 0.0) for d, _, _ in days * 20], 50.0, start=790.0)
    assert all(0.0 <= k.kbdi <= 800.0 for k in long)


def test_kbdi_first_fifth_inch_of_a_spell_is_intercepted() -> None:
    d0 = date(2023, 6, 1)
    cool = 0.0
    small = kbdi_series([(d0, cool, 0.1 * 25.4)], 50.0, start=400.0)
    assert small[0].kbdi == pytest.approx(400.0)
    big = kbdi_series([(d0, cool, 1.2 * 25.4)], 50.0, start=400.0)
    assert big[0].kbdi == pytest.approx(300.0)
    spell = kbdi_series([(d0, cool, 0.1 * 25.4), (d0 + timedelta(days=1), cool, 0.5 * 25.4)], 50.0, 400.0)
    assert spell[1].kbdi == pytest.approx(400.0 - 40.0)


@dataclass(frozen=True)
class Hour:
    t: datetime
    t_c: float
    rh_pct: float
    wind_ms: float
    precip_mm: float = 0.0


DRY = (30.0, 12.0, 10.0)
WET = (20.0, 60.0, 2.0)
T0 = datetime(2025, 3, 19, 12, tzinfo=UTC)


def hours(pattern: str, start: datetime = T0) -> list[Hour]:
    out = []
    for i, ch in enumerate(pattern):
        if ch == "_":
            continue
        t, rh, w = DRY if ch == "x" else WET
        out.append(Hour(start + timedelta(hours=i), t, rh, w))
    return out


def test_ffwi_branch_needs_three_consecutive_hours() -> None:
    assert ffwi(*DRY) >= 35.0
    assert not tr.evaluate(hours("..xx..xx.."), {}).fired
    res = tr.evaluate(hours("..xxx...."), {})
    assert res.first_fire_utc() == T0 + timedelta(hours=4)
    assert res.episodes[0].branches == ("ffwi_rh",)


def test_missing_hour_breaks_the_run() -> None:
    assert not tr.evaluate(hours("xx_xx"), {}).fired


def test_kbdi_branch_uses_previous_local_day() -> None:
    obs = hours("." * 30)
    day = obs[0].t.astimezone(tr.EASTERN).date()
    res = tr.evaluate(obs, {day: 520.0})
    active = [h.t for h in res.hours if h.kbdi_branch]
    assert active and all(h.astimezone(tr.EASTERN).date() == day + timedelta(days=1) for h in active)
    assert res.episodes[0].branches == ("kbdi",)


def test_table_rock_fires_inside_its_window_on_the_ffwi_branch_only() -> None:
    fw = fwm.gsp()
    inside = [e for e in fw.trigger.episodes if tablerock.WINDOW[0] <= e.start_utc < tablerock.WINDOW[1]]
    assert inside, "Table Rock must fire inside 2025-03-19..24"
    assert inside[0].start_utc == datetime(2025, 3, 19, 17, tzinfo=UTC)
    assert all(e.branches == ("ffwi_rh",) for e in inside)
    window_kbdi = [k.kbdi for k in fw.kbdi if date(2025, 3, 18) <= k.day <= date(2025, 3, 24)]
    assert max(window_kbdi) < 200.0, "a KBDI-only rule would miss Table Rock (R05 1.3)"


def test_blue_sky_week_stays_off() -> None:
    fw = fwm.gsp()
    assert not [e for e in fw.trigger.episodes if BLUE_WINDOW[0] <= e.start_utc < BLUE_WINDOW[1]]
    assert not any(h.active for h in fw.trigger.hours if BLUE_WINDOW[0] <= h.t < BLUE_WINDOW[1])


def test_gsp_ffwi_p99_is_close_to_the_threshold() -> None:
    fw = fwm.gsp()
    vals = sorted(ffwi(o.t_c, o.rh_pct, o.wind_ms) for o in fw.obs if o.t.year < 2025)
    p99 = vals[int(0.99 * (len(vals) - 1))]
    assert p99 == pytest.approx(34.4, abs=0.5)


@pytest.fixture(scope="module")
def cal() -> tuple[rk.Calibration, tuple[rk.HourDriver, ...]]:
    return fwm.calibration(tablerock.veg_mean())


def test_calibration_reproduces_the_base_ignition_rate(cal: tuple[rk.Calibration, tuple]) -> None:
    c, year = cal
    years = len(year) / rk.HOURS_PER_YEAR
    km = 100.0
    mean = rk.Circuit("MEAN", "00000", 1500, c.veg_mean, km)
    annual = rk.rank([mean], list(year), c, year)[0].expected_ignitions / years
    assert annual == pytest.approx(0.022, rel=1e-6)


def test_in_sample_fit_reproduces_its_own_month_shares(cal: tuple[rk.Calibration, tuple]) -> None:
    c, year = cal
    shares = rk.seasonal_shares(year, c)
    observed = rk.value("validation", "observed_month_share_pct")
    tol = float(rk.value("validation", "tolerance_points"))
    for month, share in observed.items():
        assert abs(shares[int(month)] - share) <= tol, (month, shares[int(month)], share)


def test_r02_transfer_weights_fail_the_seasonality_check(
    cal: tuple[rk.Calibration, tuple], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, year = cal
    params = tr.params()
    for key in ("logit_kbdi_coef", "logit_ffwi_coef"):
        monkeypatch.setitem(params["ignition"][key], "value", params["ignition"][key]["r02_value"])
    c = rk.calibrate(year, tablerock.veg_mean())
    shares = rk.seasonal_shares(year, c)
    assert shares[2] + shares[3] + shares[4] < 15.0


def test_ranking_orders_by_expected_ignitions_and_is_deterministic(cal: tuple[rk.Calibration, tuple]) -> None:
    c, year = cal
    fw = fwm.gsp()
    window = rk.drivers(fw.between(*tablerock.WINDOW), fw.kbdi_by_day)
    circuits = tablerock.circuits()
    a = rk.rank(circuits, window, c, year)
    b = rk.rank(list(reversed(circuits)), window, c, year)
    assert [x.circuit.feeder_id for x in a] == [x.circuit.feeder_id for x in b]
    assert [x.rank for x in a] == list(range(1, len(a) + 1))
    assert all(x.expected_ignitions >= y.expected_ignitions for x, y in zip(a, a[1:], strict=False))
    assert all(x.ratio_to_average_window > 3.0 for x in a), "Table Rock must stand out from an average week"
    assert all(0.0 < x.p_outage < 1.0 and x.peak_p_ign_given_outage <= 0.5 for x in a)


def test_more_line_and_more_vegetation_mean_more_risk(cal: tuple[rk.Calibration, tuple]) -> None:
    c, year = cal
    fw = fwm.gsp()
    window = rk.drivers(fw.between(*tablerock.WINDOW), fw.kbdi_by_day)
    base = rk.Circuit("A", "45077", 1000, 0.5, 60.0)
    longer = rk.Circuit("B", "45077", 1000, 0.5, 120.0)
    greener = rk.Circuit("C", "45077", 1000, 0.9, 60.0)
    e = {r.circuit.feeder_id: r.expected_ignitions for r in rk.rank([base, longer, greener], window, c, year)}
    assert e["B"] == pytest.approx(2.0 * e["A"])
    assert e["C"] > e["A"]
    assert math.isfinite(e["C"])


def test_leave_one_month_out_results_are_reproducible(cal: tuple[rk.Calibration, tuple]) -> None:
    _, year = cal
    veg = tablerock.veg_mean()
    observed = rk.value("validation", "observed_month_share_pct")
    tol = float(rk.value("validation", "tolerance_points"))
    for row in rk.value("validation", "loo"):
        with rk.ignition_weights(row["kbdi_coef"], row["ffwi_coef"]):
            shares = rk.seasonal_shares(year, rk.calibrate(year, veg))
        month = row["held_out"]
        assert shares[month] == pytest.approx(row["predicted_pct"], abs=0.05)
        assert row["observed_pct"] == observed[month]
        assert (abs(shares[month] - observed[month]) <= tol) is row["within_tolerance"]
    assert [r["within_tolerance"] for r in rk.value("validation", "loo")] == [True, True, False]


def test_table_rock_score_depends_on_the_ffwi_weight(cal: tuple[rk.Calibration, tuple]) -> None:
    _, year = cal
    fw = fwm.gsp()
    window = rk.drivers(fw.between(*tablerock.WINDOW), fw.kbdi_by_day)
    quoted = rk.value("validation", "ffwi_sensitivity")
    ratios = {fc: tablerock.ffwi_ratio(fc, window, year) for fc in (0.8, 2.0, 2.8)}
    for fc, r in ratios.items():
        assert r == pytest.approx(quoted[fc], abs=0.05)
    assert ratios[0.8] < ratios[2.0] < ratios[2.8]
    assert float(rk.value("ignition", "logit_ffwi_coef")) == 2.0
