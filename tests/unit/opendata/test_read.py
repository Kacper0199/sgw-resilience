"""GD time gating over the committed `data/open/*/helene_*.json`: at any view time only what was observed,
in force or declared by then; peaks only grow with time; the dq asset passes on the committed files."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sgw.opendata import read
from sgw.opendata.asset import checks_for
from sgw.opendata.build import OUT_ROOT

T_N = datetime(2024, 9, 26, 9, tzinfo=UTC)
T_N4 = datetime(2024, 9, 27, 9, tzinfo=UTC)
T_AFTER = datetime(2024, 9, 28, 12, tzinfo=UTC)
T_LATE = datetime(2024, 10, 4, tzinfo=UTC)
RANK = {"below": 0, "minor": 1, "moderate": 2, "major": 3}


@pytest.mark.parametrize("t", [T_N, T_N4, T_AFTER, T_LATE])
def test_nothing_after_the_view_time(t: datetime) -> None:
    body = read.observed(t)
    assert all(g.peak_utc is None or g.peak_utc <= t for g in body.gauges)
    assert all(s.gust_utc is None or s.gust_utc <= t for s in body.stations)
    assert all(w.issued_utc <= t < w.expires_utc for w in body.warnings)
    assert all(
        s.silent_since_utc is None or s.silent_since_utc + timedelta(hours=1) <= t for s in body.stations
    )


def test_peaks_and_categories_only_grow() -> None:
    times = [T_N, T_N4, T_AFTER, T_LATE]
    gauges = [{g.gauge_id: g for g in read.gauges_at(t)} for t in times]
    for a, b in zip(gauges, gauges[1:], strict=False):
        for gid, g in a.items():
            later = b[gid]
            assert RANK[later.category] >= RANK[g.category]
            assert g.peak_ft is None or (later.peak_ft is not None and later.peak_ft >= g.peak_ft)
    late = gauges[-1]
    assert sum(g.category != "below" for g in late.values()) > sum(
        g.category != "below" for g in gauges[0].values()
    )


def test_category_against_nws_stages() -> None:
    stages = {"minor": 10.0, "moderate": 14.0, "major": 18.0}
    assert read.category(None, stages) == "below"
    assert read.category(9.9, stages) == "below"
    assert read.category(10.0, stages) == "minor"
    assert read.category(17.9, stages) == "moderate"
    assert read.category(30.0, {"minor": 10.0, "moderate": None, "major": None}) == "minor"


def test_airport_wind_peak_so_far_and_silence() -> None:
    early = {s.station: s for s in read.stations_at(T_N)}
    landfall = {s.station: s for s in read.stations_at(T_N4)}
    after = {s.station: s for s in read.stations_at(T_AFTER)}
    assert landfall["AGS"].gust_mph is not None and early["AGS"].gust_mph is not None
    assert landfall["AGS"].gust_mph > early["AGS"].gust_mph
    assert after["AGS"].gust_mph == round(71 * 1.15078)
    assert landfall["VLD"].silent_since_utc == datetime(2024, 9, 27, 3, 45, tzinfo=UTC)
    assert early["VLD"].silent_since_utc is None
    assert all(s.from_deg is None or 0 <= s.from_deg < 360 for s in after.values())


def test_warnings_follow_the_storm() -> None:
    kinds = lambda t: {w.kind for w in read.warnings_at(t)}  # noqa: E731
    assert {"tropical_storm", "hurricane"} <= kinds(T_N)
    assert "flash_flood" in kinds(T_N4)
    assert kinds(T_AFTER) == {"flood"}
    assert kinds(datetime(2024, 9, 24, tzinfo=UTC)) == set()
    ids = [w.warning_id for w in read.warnings_at(T_N4)]
    assert len(ids) == len(set(ids))
    assert all(w.geometry["type"] == "MultiPolygon" for w in read.warnings_at(T_N4))


def test_official_record_is_gated_by_declaration_and_event_time() -> None:
    before = read.official_record(datetime(2024, 9, 25, tzinfo=UTC))
    assert before.declarations == [] and before.events_total == 0 and before.top_events == []
    sc_only = read.official_record(datetime(2024, 9, 29, 12, tzinfo=UTC))
    assert [d.declaration_id for d in sc_only.declarations] == ["DR-4829-SC"]
    full = read.official_record(datetime(2024, 10, 5, tzinfo=UTC))
    assert [d.declaration_id for d in full.declarations] == ["DR-4829-SC", "DR-4830-GA"]
    ga = full.declarations[1]
    assert ga.counties_total >= len(ga.footprint_counties) > 50
    assert sum(c.count for c in full.events_by_type) == full.events_total
    assert full.events_total >= sc_only.events_total > 0
    assert all(e.url.endswith(str(e.event_id)) for e in full.top_events)
    assert full.deaths >= max(e.deaths for e in full.top_events)
    assert any("OpenFEMA" in a and "not endorsed by FEMA" in a for a in full.attribution)


def test_dq_asset_passes_on_the_committed_files() -> None:
    checks = {c.name: c for c in checks_for(OUT_ROOT, T_N4)}
    assert all(c.passed for c in checks.values() if c.severity == "error")
    assert checks["freshness.iem-asos"].passed is False and "VLD" in checks["freshness.iem-asos"].observed
    assert checks["freshness.iem-asos"].freshness_limit_s == 3600
    assert checks_for(OUT_ROOT, T_N)[-2].passed
