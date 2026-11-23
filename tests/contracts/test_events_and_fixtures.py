from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from sgw.contracts import events as ev
from sgw.contracts.fixtures import FixtureError, read_fixture, write_fixture
from sgw.contracts.golden import MICRO_HEADER, build_micro_events

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = sorted((REPO_ROOT / "data" / "fixtures").glob("**/*.jsonl"))
FIXTURES = [p for p in FIXTURES if "eventlog" not in p.parts and "llm" not in p.parts]


def _base(type_name: str = "MeterEvent") -> dict:
    return json.loads(json.dumps(ev.dump_event(next(e for e in build_micro_events() if e.type == type_name))))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_every_fixture_line_round_trips(path: Path) -> None:
    header, events = read_fixture(path)
    body_lines = path.read_text(encoding="utf-8").splitlines()[1:]
    assert len(body_lines) == len(events)
    for raw, event in zip(body_lines, events, strict=True):
        again = json.dumps(ev.dump_event(event), separators=(",", ":"), ensure_ascii=False, sort_keys=True)
        assert again == raw
    assert header.schema_version == ev.CURRENT_SCHEMA_VERSION


def test_fixture_set_is_not_empty() -> None:
    assert any(p.parent.name == "helene_micro" for p in FIXTURES)


def test_helene_micro_is_marked_hand_made_and_tells_the_ps17_story() -> None:
    header, events = read_fixture(REPO_ROOT / "data" / "fixtures" / "helene_micro" / "all.jsonl")
    assert header.hand_made is True and header.data_label == "synthetic"
    assert 180 <= len(events) <= 220
    types = [e.type for e in events]
    labels = [e.payload.advisory_label for e in events if e.type == "WeatherForecastIssued"]
    assert {"N", "N+1"} <= set(labels)
    assert types.count("ProposalCreated") == 2
    crew_props = [
        e
        for e in events
        if e.type == "ProposalCreated" and e.payload.action_type.value == "preposition_crews"
    ]
    assert len(crew_props) == 1
    trips = [e for e in events if e.type == "DeviceState" and e.payload.device_id == "BRK-FDR-AIK-2207"]
    assert trips and trips[0].payload.value == "open"
    voided = [e for e in events if e.type == "ProposalUpdated" and e.payload.voided_approval_ids]
    assert voided and voided[0].payload.material is True
    approved = {e.payload.proposal_id: e for e in events if e.type == "DecisionApproved"}
    assert set(approved) == {"PRP-CREW-AIK-0926A", "PRP-PS17-FDR2207-PRIO"}
    ps17 = approved["PRP-PS17-FDR2207-PRIO"]
    assert set(ps17.payload.approver_ids) == {"ic_01", "wtr_lead_01"}
    assert ps17.event_time < datetime(2024, 9, 27, 4, 10, tzinfo=UTC)
    work_order = next(e for e in events if e.type == "WorkOrder")
    assert work_order.payload.proposal_id in approved
    assert any(e.type == "ApprovalRecorded" and e.payload.approval_id == "APR-CREW-V1-IC" for e in events)
    ps17_updates = [
        e.payload
        for e in events
        if e.type == "DecisionClockUpdated" and e.payload.decision_case_id == "DC-D3-PS17-POWER"
    ]
    assert ps17_updates[-1].decide_by_utc < ps17_updates[0].decide_by_utc


def test_every_event_type_has_schema_version_and_upcast_path() -> None:
    for model in ev.EVENT_MODELS.values():
        assert "schema_version" in model.model_fields
    raw = _base()
    raw["schema_version"] = 99
    with pytest.raises(ValueError, match="newer"):
        ev.parse_event(raw)


def test_upcaster_registry_runs_registered_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(ev.EVENT_SCHEMA_VERSIONS, "MeterEvent", 2)
    monkeypatch.setitem(ev.UPCASTERS, ("MeterEvent", 1), lambda d: {**d, "upcast_marker": True})
    out = ev.upcast(_base())
    assert out["schema_version"] == 2 and out["upcast_marker"] is True
    weather = _base("WeatherAlert")
    assert ev.upcast(weather)["schema_version"] == 1


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_inf_and_nan_rejected(bad: float) -> None:
    raw = _base("DeviceState")
    raw["payload"]["value"] = bad
    with pytest.raises(ValidationError):
        ev.parse_event(raw)


def test_naive_timestamp_and_unknown_type_rejected() -> None:
    raw = _base()
    raw["event_time"] = "2024-09-27T04:20:00"
    with pytest.raises(ValidationError):
        ev.parse_event(raw)
    raw = _base()
    raw["type"] = "NotAnEvent"
    with pytest.raises(ValueError, match="unknown event type"):
        ev.parse_event(raw)


def test_extra_fields_rejected() -> None:
    raw = _base()
    raw["payload"]["surprise"] = 1
    with pytest.raises(ValidationError):
        ev.parse_event(raw)


def test_coverage_is_integer_ppm() -> None:
    raw = _base()
    raw["coverage_ppm"] = 0.5
    with pytest.raises(ValidationError):
        ev.parse_event(raw)


def test_fixture_reader_rejects_tampering(tmp_path: Path) -> None:
    events = build_micro_events()[:5]
    path = tmp_path / "f.jsonl"
    write_fixture(path, MICRO_HEADER, events)
    read_fixture(path)
    text = path.read_text().replace("synthetic", "synthetiC", 2)
    path.write_text(text)
    with pytest.raises((FixtureError, ValidationError)):
        read_fixture(path)


def test_fixture_reader_rejects_unsorted(tmp_path: Path) -> None:
    events = build_micro_events()[:5]
    path = tmp_path / "f.jsonl"
    write_fixture(path, MICRO_HEADER, events)
    head, *lines = path.read_text().splitlines()
    import hashlib

    body = "\n".join(reversed(lines)) + "\n"
    header = json.loads(head)
    header["body_sha256"] = hashlib.sha256(body.encode()).hexdigest()
    path.write_text(json.dumps(header) + "\n" + body)
    with pytest.raises(FixtureError, match="sorted"):
        read_fixture(path)


def test_events_schema_lists_every_type_and_webhook_names() -> None:
    schema = ev.events_json_schema()
    mapping = schema["discriminator"]["mapping"]
    assert set(mapping) == set(ev.EVENT_PAYLOADS)
    assert {
        "ClockBreached",
        "CommitmentCreated",
        "CommitmentDrifted",
        "DecisionApproved",
        "EnvelopeApproved",
        "BreakGlassUsed",
    } <= set(mapping)
    assert len(ev.SOURCE_EVENTS) == 9


def test_event_ids_are_uuids() -> None:
    for e in build_micro_events():
        assert isinstance(e.event_id, uuid.UUID)
        assert isinstance(e.event_time, datetime)
