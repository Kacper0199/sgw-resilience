from __future__ import annotations

import csv
import re
from datetime import UTC, datetime
from pathlib import Path

from sgw.reports import sc_103_314 as sc

HEADER = (
    "section_id,feeder_id,fips,customers,fault_utc,peak_gust_ms,damage_state,work_ok_utc,repaired_utc,"
    "customers_back_utc"
)


def _csv(tmp_path: Path, rows: list[str]) -> Path:
    p = tmp_path / "outages.csv"
    p.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return p


def test_records_follow_the_rule_time_duration_cause_and_six_hour_threshold(tmp_path: Path) -> None:
    path = _csv(
        tmp_path,
        [
            "S1,F1,45001,100,2024-09-27T00:00:00Z,30.0,slight,,,2024-09-27T05:00:00Z",
            "S2,F2,45003,200,2024-09-27T01:00:00Z,41.5,extensive,,,2024-09-27T07:30:00Z",
            "S3,F3,45003,50,2024-09-27T02:00:00Z,20.0,slight,,,2024-09-27T03:00:00Z",
            "S4,F4,13245,999,2024-09-27T00:00:00Z,60.0,complete,,,2024-10-01T00:00:00Z",
            "S5,F5,45005,10,2024-09-27T00:00:00Z,25.0,slight,,,",
        ],
    )
    report = sc.build(path, county_codes={"45001": "ABBS", "45003": "AIK"})
    by_id = {r.area_id: r for r in report.counties}
    assert set(by_id) == {"SC-45001", "SC-45003"}, "only SC counties with restored sections"
    aik, abb = by_id["SC-45003"], by_id["SC-45001"]
    assert (aik.duration_h, aik.customers_interrupted, aik.sections) == (6.5, 250, 2)
    assert aik.report_required and not abb.report_required and abb.duration_h == 5.0
    assert aik.county_code == "AIK" and "Hurricane Helene" in aik.cause and "42 m/s" in aik.cause
    assert report.system.customers_interrupted == 350 and report.system.duration_h == 7.5
    assert report.reportable == [aik]
    assert report.citation == "S.C. Code Ann. Regs. 103-314 (Interruption of Service)"


def test_story_replay_report_is_labelled_synthetic_and_cites_the_rule() -> None:
    report = sc.build()
    md = sc.render_markdown(report)
    assert md.startswith("# Hurricane Helene: interruption report draft under S.C. Code Ann. Regs. 103-314")
    assert "Synthetic data" in md and "Draft, not filed" in md
    assert "times are not held by the platform" in md and "| Over 6 h |" in md
    assert sc.interruption_summary(report) in md and "Cause: Hurricane Helene" in md
    assert sc.render_markdown(report, "> BANNER").startswith("> BANNER\n")
    with sc.OUTAGES.open(encoding="utf-8") as fh:
        sc_rows = [r for r in csv.DictReader(fh) if r["fips"].startswith("45") and r["customers_back_utc"]]
    assert report.system.sections == len(sc_rows)
    assert report.system.customers_interrupted == sum(int(r["customers"]) for r in sc_rows)
    assert all(r.duration_h > 0 for r in report.counties)
    assert re.search(r"\| SC-SYSTEM \| 2024-09-26 21:30Z \|", md)


def test_a_review_before_restoration_holds_nothing_from_after_its_time() -> None:
    at = datetime(2024, 9, 30, 12, 0, tzinfo=UTC)
    report = sc.build(county_codes={}, as_of=at)
    assert report.system.restored_at is None
    assert report.system.duration_h == round((at - report.system.started_at).total_seconds() / 3600, 1)
    assert all(r.restored_at is None or r.restored_at <= at for r in report.counties)
    assert "not yet restored" in sc.interruption_summary(report)
    whole = sc.build(county_codes={})
    assert sc.build(county_codes={}, as_of=datetime(2024, 10, 6, 2, 0, tzinfo=UTC)) == whole
