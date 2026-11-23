"""Generated Helene scenario: determinism, golden regression, truth table, ids shared with helene_micro."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from sgw.contracts import golden
from sgw.contracts.fixtures import read_fixture
from sgw.generator.config import FIXTURES_DIR, GENERATOR_NAME, parse_utc
from sgw.generator.scenario import FEEDS, GenerationResult, generate

COMMITTED = FIXTURES_DIR / "helene"
BANNED = re.compile(r"company a\b|fictional|anonymous|\bacme\b|riverside|springfield", re.IGNORECASE)


def _events(out: Path) -> dict[str, list]:
    return {feed: read_fixture(out / f"{feed}.jsonl")[1] for feed in FEEDS}


def test_generation_is_byte_identical_across_runs(generated: GenerationResult, tmp_path: Path) -> None:
    again = generate("helene", tmp_path / "again")
    assert again.manifest["scenario_sha256"] == generated.manifest["scenario_sha256"]
    for name, info in generated.manifest["files"].items():
        assert again.manifest["files"][name]["sha256"] == info["sha256"], name


def test_committed_fixture_matches_the_generator_within_tolerance(generated: GenerationResult) -> None:
    """Golden regression with numerical tolerance (byte identity: `make data` twice on one machine)."""
    committed = json.loads((COMMITTED / "truth_table.json").read_text(encoding="utf-8"))
    new = generated.truth_table
    assert new["metrics"]["county_t50_median_h"] == pytest.approx(
        committed["metrics"]["county_t50_median_h"], abs=0.5
    )
    assert new["metrics"]["events"] == pytest.approx(committed["metrics"]["events"], rel=0.01)
    assert new["metrics"]["sections_failed"] == pytest.approx(
        committed["metrics"]["sections_failed"], rel=0.01
    )
    old_h = next(c for c in committed["seeded_cases"] if c["id"] == "HINGE-PS17-N-N1")["outcome"]
    new_h = next(c for c in new["seeded_cases"] if c["id"] == "HINGE-PS17-N-N1")["outcome"]
    for key in ("decide_by_N_utc", "decide_by_N1_utc"):
        delta = abs((parse_utc(new_h[key]) - parse_utc(old_h[key])).total_seconds())
        assert delta <= 300, key
    assert new_h["verdict"] == old_h["verdict"]


def test_committed_manifest_verifies() -> None:
    import hashlib

    manifest = json.loads((COMMITTED / "manifest.json").read_text(encoding="utf-8"))
    for name, info in manifest["files"].items():
        assert hashlib.sha256((COMMITTED / name).read_bytes()).hexdigest() == info["sha256"], name


def test_fixture_headers_follow_k9(generated: GenerationResult) -> None:
    for feed in FEEDS:
        header, events = read_fixture(generated.out_dir / f"{feed}.jsonl")
        assert header.generator == GENERATOR_NAME and header.seed == 61017
        assert header.hand_made is False and header.data_label == "synthetic" and header.feed == feed
        assert events, feed
        assert all(e.feed_mode.value == "synthetic" for e in events)


def test_truth_table_lists_every_seeded_id_with_an_outcome(
    generated: GenerationResult, scenario: dict
) -> None:
    table = {c["id"]: c for c in generated.truth_table["seeded_cases"]}
    assert set(table) == {c["id"] for c in scenario["seeded"]}
    for cid, case in table.items():
        assert case["outcome"], cid
    text = "".join(
        (generated.out_dir / name).read_text(encoding="utf-8")
        for name in [f"{f}.jsonl" for f in FEEDS] + ["network.json", "sections.csv"]
    )
    clock_ids = set(generated.truth_table["critical_path"]["nodes"])
    governance = {"PRP-CREW-AIK-0926A", "APR-CREW-V1-IC"}
    for case in scenario["seeded"]:
        for entity in case["entities"]:
            if entity in clock_ids or entity in governance or entity == "ami-headend":
                continue
            assert entity in text, (case["id"], entity)


def test_ids_and_story_beats_shared_with_helene_micro(generated: GenerationResult) -> None:
    ev = _events(generated.out_dir)
    devices = {e.payload.device_id for e in ev["scada"]}
    assert {
        golden.PRESSURE_SENSOR,
        f"BRK-{golden.FEEDER_PS17}",
        f"BRK-{golden.FEEDER_LARGER}",
        "PMP-PS-17-1",
    } <= devices
    traces = {e.payload.trace_id: e.payload for e in ev["gis"]}
    assert traces["TRC-FDR2207-PS17"].cross_domain_ids == [golden.PS17, golden.HOSPITAL]
    assert golden.ZONE in traces["TRC-FDR2207-PS17"].downstream_ids
    crews = {e.payload.crew_id for e in ev["fsm"]}
    assert set(golden.CREWS) <= crews
    locations = {e.payload.location_id for e in ev["fsm"]}
    assert {golden.YARD_SANDHILL, golden.YARD_MILLPOND} <= locations
    labels = [e.payload.advisory_label for e in ev["weather"] if e.type == "WeatherForecastIssued"]
    assert {"N-1", "N", "N+1"} <= set(labels)
    trip = next(e for e in ev["scada"] if e.payload.device_id == f"BRK-{golden.FEEDER_PS17}")
    assert trip.payload.value == "open"
    pump_off = next(
        e for e in ev["scada"] if e.payload.device_id == "PMP-PS-17-1" and e.payload.value is False
    )
    assert pump_off.event_time == trip.event_time
    cases = set(generated.truth_table["clocks_by_advisory"]["N+1"]["cases"])
    assert {golden.CASE_CREWS, golden.CASE_PS17} <= cases
    wo = [e for e in ev["eam"] if e.payload.work_order_id == "WO-SYN-PS17-GEN-01"]
    assert wo and wo[0].payload.work_type == "portable_generator_hookup"


def test_events_respect_causality_and_the_window(generated: GenerationResult) -> None:
    ev = _events(generated.out_dir)
    for events in ev.values():
        for e in events:
            assert e.known_at >= e.event_time
    opened = {e.payload.outage_id: e.event_time for e in ev["oms"] if e.payload.status == "open"}
    for e in ev["oms"]:
        if e.payload.status == "restored":
            assert e.event_time > opened[e.payload.outage_id]


def test_late_ami_backlog_is_visible_in_known_at(generated: GenerationResult) -> None:
    late = [
        e for e in _events(generated.out_dir)["ami"] if (e.known_at - e.event_time).total_seconds() > 40 * 60
    ]
    assert late
    assert all(
        parse_utc("2024-09-27T06:00:00Z") <= e.event_time < parse_utc("2024-09-27T08:00:00Z") for e in late
    )


def test_no_banned_names_in_any_output(generated: GenerationResult) -> None:
    for path in generated.out_dir.iterdir():
        assert not BANNED.search(path.read_text(encoding="utf-8")), path.name


def test_acceptance_numbers(generated: GenerationResult) -> None:
    m = generated.truth_table["metrics"]
    assert 25.0 <= m["county_t50_median_h"] <= 50.0
    assert m["events_outside_window_dropped"] == 0
    v = generated.truth_table["validation"]
    ags = v["asos_peak_gust"]["AGS"]
    lag = parse_utc(ags["model_peak_utc"]) - parse_utc(ags["observed_peak_utc"])
    assert abs(lag.total_seconds()) <= 1800
