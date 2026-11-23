"""K9 fixture format: `data/fixtures/<scenario>/<feed>.jsonl`, line 1 a header, then one K2 envelope per
line sorted by `event_time`. `body_sha256` covers every byte after the header line."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import Field

from sgw.contracts.base import Contract, UtcDatetime
from sgw.contracts.events import EnvelopeBase, dump_event, parse_event
from sgw.contracts.vocab import FeedMode


class ScenarioWindow(Contract):
    start_utc: UtcDatetime
    end_utc: UtcDatetime


class FixtureHeader(Contract):
    fixture: str
    schema_version: int = Field(ge=1)
    feed: str
    feed_mode: FeedMode
    generator: str
    generator_version: str
    seed: int | None
    calibration_source: str
    scenario_window: ScenarioWindow
    licence: str
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hand_made: bool = False
    data_label: Literal["synthetic", "public", "mixed"] = "synthetic"
    note: str = ""


class FixtureError(ValueError):
    pass


def _line(event: EnvelopeBase) -> str:
    return json.dumps(dump_event(event), separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def render_body(events: Iterable[EnvelopeBase]) -> str:
    return "".join(_line(e) + "\n" for e in events)


def write_fixture(path: Path, header_fields: dict[str, object], events: list[EnvelopeBase]) -> FixtureHeader:
    ordered = sorted(events, key=lambda e: (e.event_time, e.dedup_key))
    body = render_body(ordered)
    header = FixtureHeader.model_validate(
        {**header_fields, "body_sha256": hashlib.sha256(body.encode()).hexdigest()}
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    head = json.dumps(header.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
    path.write_text(head + "\n" + body, encoding="utf-8", newline="\n")
    return header


def read_fixture(path: Path) -> tuple[FixtureHeader, list[EnvelopeBase]]:
    text = path.read_text(encoding="utf-8")
    head, _, body = text.partition("\n")
    header = FixtureHeader.model_validate_json(head)
    if hashlib.sha256(body.encode()).hexdigest() != header.body_sha256:
        raise FixtureError(f"{path}: body_sha256 mismatch")
    events = [parse_event(json.loads(line)) for line in body.splitlines() if line.strip()]
    times = [e.event_time for e in events]
    if times != sorted(times):
        raise FixtureError(f"{path}: events not sorted by event_time")
    keys = [e.dedup_key for e in events]
    if len(keys) != len(set(keys)):
        raise FixtureError(f"{path}: duplicate dedup_key")
    for e in events:
        if not header.scenario_window.start_utc <= e.event_time <= header.scenario_window.end_utc:
            raise FixtureError(f"{path}: event {e.event_id} outside scenario_window")
    return header, events
