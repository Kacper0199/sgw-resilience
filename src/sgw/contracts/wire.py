"""K4 SSE wire format.

`id: <stream>.<epoch>.<seq>`; stream is `ops` or `run:<run_id>`. Ledger frames use `ledger_seq` as seq.
LangGraph types never reach the browser: every frame is a `WireFrame`.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from sgw.contracts.base import Contract, UtcDatetime
from sgw.contracts.vocab import ApprovalFunction, Classification, DegradedMode, KillLevel, RunMode, Tier

WIRE_VERSION: Literal[1] = 1
HEARTBEAT_INTERVAL_S = 10
MISSED_HEARTBEATS_STALE = 3


class WireEvent(StrEnum):
    LEDGER = "ledger"
    STATE = "state"
    HEARTBEAT = "heartbeat"
    RESYNC = "resync"
    RUN_START = "run_start"
    TEXT_DELTA = "text_delta"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    STEP = "step"
    ARTIFACT = "artifact"
    APPROVAL_REQUIRED = "approval_required"
    RUN_PAUSED = "run_paused"
    RUN_END = "run_end"
    RUN_ERROR = "run_error"


OPS_EVENTS = frozenset({WireEvent.LEDGER, WireEvent.STATE, WireEvent.HEARTBEAT, WireEvent.RESYNC})
RUN_EVENTS = frozenset(set(WireEvent) - {WireEvent.LEDGER, WireEvent.STATE}) | {WireEvent.HEARTBEAT}

_STREAM_RE = re.compile(r"^(ops|run:[A-Za-z0-9_\-]+)$")
_ID_RE = re.compile(r"^(?P<stream>ops|run:[A-Za-z0-9_\-]+)\.(?P<epoch>\d+)\.(?P<seq>\d+)$")


class WireFrame(Contract):
    v: Literal[1] = WIRE_VERSION
    type: WireEvent
    seq: int = Field(ge=0)
    ledger_seq: int | None = Field(default=None, ge=1)
    run_id: str | None = None
    ns: list[str] = Field(default_factory=list, description="subgraph namespace path")
    ts: UtcDatetime
    scenario_time: UtcDatetime | None = None
    run_mode: RunMode
    classification: Classification
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _ledger_frames_carry_seq(self) -> WireFrame:
        if self.type is WireEvent.LEDGER and self.ledger_seq is None:
            raise ValueError("ledger frames carry ledger_seq")
        return self


class HeartbeatPayload(Contract):
    head_ledger_seq: int = Field(ge=0)
    server_time: UtcDatetime
    kill_level: KillLevel
    degraded_mode: DegradedMode


class ResyncPayload(Contract):
    reason: Literal["epoch_mismatch", "ring_overflow", "server_restart"]
    epoch: int = Field(ge=0)
    snapshot_url: str


class StatePayload(Contract):
    tile: Literal["risk", "asset_status", "crew_position", "decision_clock"]
    entity_id: str
    version: int = Field(ge=1)
    value: dict[str, Any]


class ApprovalRequiredPayload(Contract):
    proposal_id: str
    proposal_version: int = Field(ge=1)
    action_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    tier: Tier
    functions_required: list[ApprovalFunction] = Field(min_length=1)
    tainted: bool = Field(default=False, description="the run read untrusted input (notes quarantined)")


class SseId(Contract):
    stream: str = Field(pattern=_STREAM_RE.pattern)
    epoch: int = Field(ge=0)
    seq: int = Field(ge=0)

    def render(self) -> str:
        return f"{self.stream}.{self.epoch}.{self.seq}"

    @classmethod
    def parse(cls, raw: str) -> SseId:
        m = _ID_RE.match(raw)
        if not m:
            raise ValueError(f"malformed SSE id: {raw!r}")
        return cls(stream=m["stream"], epoch=int(m["epoch"]), seq=int(m["seq"]))


def encode_frame(frame: WireFrame, sse_id: SseId) -> str:
    data = json.dumps(
        frame.model_dump(mode="json"), separators=(",", ":"), ensure_ascii=False, sort_keys=True
    )
    return f"id: {sse_id.render()}\nevent: {frame.type.value}\ndata: {data}\n\n"


def decode_stream(text: str) -> list[tuple[SseId, WireFrame]]:
    out: list[tuple[SseId, WireFrame]] = []
    for block in text.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        fields: dict[str, str] = {}
        for line in block.splitlines():
            key, _, value = line.partition(": ")
            fields[key] = value
        frame = WireFrame.model_validate_json(fields["data"])
        if frame.type.value != fields["event"]:
            raise ValueError(f"event line {fields['event']!r} disagrees with frame type {frame.type.value!r}")
        out.append((SseId.parse(fields["id"]), frame))
    return out
