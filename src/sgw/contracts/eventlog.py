"""K19 run-level event log for demo playback (feas-05): per bookmark, the K4 frames of a green replay run,
JSONL with a K9-style header. Used only in `DEMO_MODE` after a request-hash miss, with the replay banner."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import Field

from sgw.contracts.base import Contract, UtcDatetime
from sgw.contracts.wire import SseId, WireFrame


class EventLogHeader(Contract):
    eventlog: str
    schema_version: int = Field(ge=1)
    bookmark: str
    graph: str
    graph_version: str
    captured_at: UtcDatetime
    source_run_id: str
    licence: str
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EventLogLine(Contract):
    id: str
    delay_ms: int = Field(ge=0, description="gap after the previous frame at capture time")
    frame: WireFrame


def write_eventlog(path: Path, header_fields: dict[str, object], lines: list[EventLogLine]) -> EventLogHeader:
    body = "".join(
        json.dumps(line.model_dump(mode="json"), separators=(",", ":"), sort_keys=True) + "\n"
        for line in lines
    )
    header = EventLogHeader.model_validate(
        {**header_fields, "body_sha256": hashlib.sha256(body.encode()).hexdigest()}
    )
    head = json.dumps(header.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
    path.write_text(head + "\n" + body, encoding="utf-8", newline="\n")
    return header


def read_eventlog(path: Path) -> tuple[EventLogHeader, list[EventLogLine]]:
    head, _, body = path.read_text(encoding="utf-8").partition("\n")
    header = EventLogHeader.model_validate_json(head)
    if hashlib.sha256(body.encode()).hexdigest() != header.body_sha256:
        raise ValueError(f"{path}: body_sha256 mismatch")
    lines = [EventLogLine.model_validate_json(raw) for raw in body.splitlines() if raw.strip()]
    for line in lines:
        SseId.parse(line.id)
    return header, lines
