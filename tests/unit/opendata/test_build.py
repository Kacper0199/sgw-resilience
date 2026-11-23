"""GD processing rules of `sgw.opendata.build` on small hand-made inputs (raw downloads are not committed)."""

from __future__ import annotations

from datetime import UTC, datetime

from shapely.geometry import box

from sgw.opendata import build as b


def test_running_max_rise_keeps_only_gains_of_a_step() -> None:
    series = [(0, 2.0), (15, 1.9), (30, 2.05), (45, 2.1), (60, 2.4), (75, 2.2), (90, 2.45)]
    assert b.running_max_rise(series, 0.1) == [(0, 2.0), (45, 2.1), (60, 2.4)]
    assert b.running_max_rise([], 0.1) == []


def test_silent_periods_are_gaps_over_an_hour_and_an_open_end() -> None:
    assert b.silent_periods([0, 5, 10, 100, 105], end=300) == [(10, 100), (105, 300)]
    assert b.silent_periods([0, 60, 120], end=150) == []


def test_direction_is_a_circular_mean_and_never_looks_ahead() -> None:
    reports = [(0, 350.0), (10, 10.0), (200, 90.0)]
    assert b.direction_before(reports, 20) == 0
    assert b.direction_before(reports, 100) == 10
    assert b.direction_before(reports, 150) == -1
    assert b.direction_before(reports, 5) == 350


def _gauge(name: str, minor: float | None, moderate: float | None, major: float | None) -> b.GaugeRow:
    return b.GaugeRow("0", "X", name, "GA", "Y", -81.0, 33.0, None, minor, moderate, major)


def test_gauges_whose_stages_do_not_match_the_gage_height_are_refused() -> None:
    assert b.gauge_problem(_gauge("River at Town", 12, 15, 18), 9.0) is None
    assert b.gauge_problem(_gauge("River at Town", 12, 15, 18), None) == "no gage height in the window"
    assert "MHHW" in str(b.gauge_problem(_gauge("Satilla River at Woodbine (in MHHW)", 0.6, 1.6, 2.6), 3.9))
    assert "elevations" in str(b.gauge_problem(_gauge("Alapaha River", 272, None, None), 3.4))
    assert "order" in str(b.gauge_problem(_gauge("River", 12, 10, 18), 5.0))
    assert b._num("-9999.0") is None and b._num("M") is None and b._num("4.5") == 4.5


def test_warning_window_rules() -> None:
    zone = {"GTYPE": "C", "PHENOM": "TR", "ISSUED": "202409251510", "EXPIRED": "202409271816"}
    assert b.warning_window(zone) == (
        datetime(2024, 9, 25, 15, 10, tzinfo=UTC),
        datetime(2024, 9, 27, 18, 16, tzinfo=UTC),
    )
    storm = {
        "GTYPE": "P",
        "PHENOM": "TO",
        "ISSUED": "202409270300",
        "EXPIRED": "202409270345",
        "POLY_BEG": "202409270315",
        "POLY_END": "202409270345",
    }
    assert b.warning_window(storm) == (
        datetime(2024, 9, 27, 3, 15, tzinfo=UTC),
        datetime(2024, 9, 27, 3, 45, tzinfo=UTC),
    )
    river = {**storm, "PHENOM": "FL", "POLY_BEG": "202409270222", "POLY_END": "202409270222"}
    assert b.warning_window(river) == (
        datetime(2024, 9, 27, 3, 0, tzinfo=UTC),
        datetime(2024, 9, 27, 3, 45, tzinfo=UTC),
    )
    cancelled = {"GTYPE": "C", "PHENOM": "FL", "ISSUED": "202409271200", "EXPIRED": "202409261413"}
    assert b.warning_window(cancelled) is None


def test_zone_names_map_to_footprint_counties() -> None:
    by_name = {("GA", "CHARLTON"): "13049", ("SC", "PICKENS"): "45077", ("GA", "DEKALB"): "13089"}
    assert b.zone_county("GA", "NORTHCHARLTON", by_name) == "13049"
    assert b.zone_county("SC", "GREATER PICKENS", by_name) == "45077"
    assert b.zone_county("GA", "DE KALB", by_name) == "13089"
    assert b.zone_county("GA", "COASTAL CHARLTON", by_name) == "13049"
    assert b.zone_county("GA", "WORTH", by_name) is None


def test_storm_event_times_and_damage() -> None:
    assert b._event_time("27-SEP-24 02:00:00", "EST-5") == datetime(2024, 9, 27, 7, 0, tzinfo=UTC)
    assert b._damage("200.00M") == 200_000_000
    assert b._damage("2.00K") == 2_000
    assert b._damage("") == 0 and b._damage(None) == 0


def test_simplified_multipolygon_drops_slivers_and_rounds() -> None:
    geom = b.simplified_multipolygon(box(-81.123456, 33.0, -81.0, 33.2))
    assert geom is not None and geom["type"] == "MultiPolygon"
    assert all(len(str(c).split(".")[-1]) <= 4 for c in geom["coordinates"][0][0][0])
    assert b.simplified_multipolygon(box(0, 0, 1e-4, 1e-4)) is None
