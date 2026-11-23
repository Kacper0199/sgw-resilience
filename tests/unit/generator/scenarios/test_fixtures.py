from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from sgw.contracts.fixtures import read_fixture
from sgw.generator.scenarios import readiness as rd
from sgw.generator.scenarios.cli import NAMES, generate_all
from sgw.generator.scenarios.weather import FIXTURES

FEEDS = {"bluesky": ("eam", "weather"), "tablerock": ("weather",), "heat": ("weather",)}


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, str], dict[str, str], Path]:
    a = tmp_path_factory.mktemp("scen_a")
    b = tmp_path_factory.mktemp("scen_b")
    return generate_all(a), generate_all(b), a


def test_same_hash_twice_and_equal_to_committed(two_runs) -> None:
    first, second, _ = two_runs
    for name in NAMES:
        committed = json.loads((FIXTURES / name / "manifest.json").read_text(encoding="utf-8"))
        assert first[name] == second[name] == committed["combined_sha256"], name


def test_generated_files_match_committed_bytes(two_runs) -> None:
    _, _, root = two_runs
    for name in NAMES:
        manifest = json.loads((FIXTURES / name / "manifest.json").read_text(encoding="utf-8"))
        for fname in manifest["files"]:
            assert (root / name / fname).read_bytes() == (FIXTURES / name / fname).read_bytes(), (name, fname)


@pytest.mark.parametrize("name", NAMES)
def test_k9_headers_and_bodies_validate(name: str) -> None:
    for feed in FEEDS[name]:
        header, events = read_fixture(FIXTURES / name / f"{feed}.jsonl")
        assert header.fixture == name and header.feed == feed
        assert header.generator == "sgw.generator.scenarios" and not header.hand_made
        assert header.data_label in ("synthetic", "mixed")
        assert all(e.feed_mode.value == "synthetic" for e in events)


def test_table_rock_alert_is_inside_the_window_and_blue_sky_has_none() -> None:
    h, events = read_fixture(FIXTURES / "tablerock" / "weather.jsonl")
    assert events and all(e.type == "WeatherAlert" for e in events)
    assert all(h.scenario_window.start_utc <= e.event_time <= h.scenario_window.end_utc for e in events)
    assert events[0].payload.event_name == "Red Flag Warning"
    _, blue = read_fixture(FIXTURES / "bluesky" / "weather.jsonl")
    assert blue == []
    trig = json.loads((FIXTURES / "tablerock" / "trigger.json").read_text(encoding="utf-8"))
    assert trig["fired_in_window"] and not trig["kbdi_branch_would_fire"]
    base = json.loads((FIXTURES / "bluesky" / "baseline.json").read_text(encoding="utf-8"))
    assert not base["wildfire"]["fired_in_window"] and not base["heat"]["fired_in_window"]


def test_heat_fixture_carries_the_h2_insight() -> None:
    insight = json.loads((FIXTURES / "heat" / "insight.json").read_text(encoding="utf-8"))
    assert insight["insight"]["id"] == "H2-STILL-AIR-LINE-BINDS"
    assert insight["insight"]["seeded_insight_holds"] is True
    assert insight["trigger"]["fired_in_window"] is True
    with (FIXTURES / "heat" / "hot_spot.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 5
    peaks = [float(r["theta_h_peak_c"]) for r in rows]
    assert peaks == sorted(peaks, reverse=True)


def test_ranking_table_is_complete_and_ordered() -> None:
    with (FIXTURES / "tablerock" / "circuit_ranking.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert [int(r["rank"]) for r in rows] == list(range(1, len(rows) + 1))
    e = [float(r["expected_ignitions_window"]) for r in rows]
    assert e == sorted(e, reverse=True)
    assert {r["fips"] for r in rows} == {"45045", "45073", "45077"}


def test_readiness_fixture_cases_are_rule_deadlines_with_work_orders() -> None:
    data = json.loads((FIXTURES / "bluesky" / "readiness_cases.json").read_text(encoding="utf-8"))
    cases = data["cases"]
    assert {c["case"]["decision_case_id"] for c in cases} == {s.case_id for s in rd.SEEDS}
    assert all(c["case"]["clock"]["clock_kind"] == "rule_deadline" for c in cases)
    _, wos = read_fixture(FIXTURES / "bluesky" / "eam.jsonl")
    assert {w.payload.asset_id for w in wos} == {s.asset_id for s in rd.SEEDS}
    assert all(w.payload.status == "open" for w in wos)


def test_no_secret_shaped_strings_in_fixtures() -> None:
    for name in NAMES:
        for p in (FIXTURES / name).iterdir():
            if p.suffix in (".json", ".jsonl", ".csv"):
                assert "sk-ant-" not in p.read_text(encoding="utf-8"), p
