"""Feed fault hooks (K6 `inject_fault`, `FAULT_FEED_*` flags). Every fault is deterministic, so a faulted
replay is as reproducible as a clean one.

Environment grammar, one variable per `FaultKind`:
    FAULT_FEED_DELAY=oms:90,ami-headend      delay delivery (known_at, received_at) by N minutes (default 60)
    FAULT_FEED_DUPLICATE=*                   resend every third event with the same dedup_key
    FAULT_FEED_OUT_OF_ORDER=scada-water      swap adjacent events with different event_time
    FAULT_FEED_GAP=oms:2024-09-26T12:00:00Z/2024-09-26T18:00:00Z   drop a window (default: middle third)
    FAULT_FEED_SCHEMA_DRIFT=lims             rename a payload field on every fifth record (quarantined)
    FAULT_FEED_FLOOD_10X=ami-headend         deliver every event ten times
`*` matches every source.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from sgw.contracts.adapter import FaultKind
from sgw.contracts.events import EnvelopeBase, dump_event, parse_event

ENV_PREFIX = "FAULT_FEED_"
DEFAULT_DELAY_MIN = 60
DUPLICATE_EVERY = 3
DRIFT_EVERY = 5
FLOOD_FACTOR = 10


class FaultConfigError(ValueError):
    pass


@dataclass(frozen=True)
class FaultSpec:
    kind: FaultKind
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Reject:
    record: dict[str, Any]
    reason: str
    position: int = -1


@dataclass(frozen=True)
class GapWindow:
    from_utc: datetime
    to_utc: datetime


@dataclass
class FaultOutcome:
    events: list[EnvelopeBase]
    rejects: list[Reject] = field(default_factory=list)
    gaps: list[GapWindow] = field(default_factory=list)


def env_name(kind: FaultKind) -> str:
    return ENV_PREFIX + kind.value.upper()


def _parse_param(kind: FaultKind, raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    if kind is FaultKind.DELAY:
        try:
            return {"minutes": int(raw)}
        except ValueError:
            raise FaultConfigError(f"{env_name(kind)}: delay must be whole minutes, got {raw!r}") from None
    if kind is FaultKind.GAP:
        start, sep, end = raw.partition("/")
        if not sep:
            raise FaultConfigError(f"{env_name(kind)}: gap must be <from>/<to>, got {raw!r}")
        try:
            return {"from_utc": _utc(start), "to_utc": _utc(end)}
        except ValueError as error:
            raise FaultConfigError(f"{env_name(kind)}: {error}") from None
    raise FaultConfigError(f"{env_name(kind)} takes no parameter, got {raw!r}")


def _utc(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError(f"timestamp {text!r} needs a zone")
    return value


def faults_from_env(env: Mapping[str, str], source_id: str) -> list[FaultSpec]:
    """Faults that apply to `source_id`, read from `FAULT_FEED_*` variables."""
    specs: list[FaultSpec] = []
    for kind in FaultKind:
        value = env.get(env_name(kind), "").strip()
        if not value:
            continue
        for item in value.split(","):
            target, _, param = item.strip().partition(":")
            if target in ("*", source_id):
                specs.append(FaultSpec(kind, _parse_param(kind, param)))
    return specs


def apply_faults(events: list[EnvelopeBase], specs: list[FaultSpec]) -> FaultOutcome:
    """Apply faults in a fixed order: gap, delay, schema drift, out-of-order, duplicate, flood."""
    outcome = FaultOutcome(events=list(events))
    order = [
        FaultKind.GAP,
        FaultKind.DELAY,
        FaultKind.SCHEMA_DRIFT,
        FaultKind.OUT_OF_ORDER,
        FaultKind.DUPLICATE,
        FaultKind.FLOOD_10X,
    ]
    for kind in order:
        for spec in (s for s in specs if s.kind is kind):
            _APPLY[kind](outcome, dict(spec.params))
    return outcome


def _gap(outcome: FaultOutcome, params: dict[str, Any]) -> None:
    if not outcome.events:
        return
    if "from_utc" in params:
        start, end = params["from_utc"], params["to_utc"]
    else:
        first, last = outcome.events[0].event_time, outcome.events[-1].event_time
        third = (last - first) / 3
        start, end = first + third, first + 2 * third
    if end <= start:
        end = start + timedelta(seconds=1)
    outcome.events = [e for e in outcome.events if not start <= e.event_time < end]
    outcome.gaps.append(GapWindow(start, end))


def _delay(outcome: FaultOutcome, params: dict[str, Any]) -> None:
    shift = timedelta(minutes=int(params.get("minutes", DEFAULT_DELAY_MIN)))
    outcome.events = [
        e.model_copy(
            update={
                "known_at": e.known_at + shift,
                "received_at": e.received_at + shift,
                "scenario_known_at": e.scenario_known_at + shift,
            }
        )
        for e in outcome.events
    ]


def _schema_drift(outcome: FaultOutcome, params: dict[str, Any]) -> None:
    kept: list[EnvelopeBase] = []
    for index, event in enumerate(outcome.events):
        if index % DRIFT_EVERY != DRIFT_EVERY - 1:
            kept.append(event)
            continue
        raw = json.loads(json.dumps(dump_event(event)))
        payload = raw["payload"]
        first = sorted(payload)[0]
        payload[f"{first}_v2"] = payload.pop(first)
        try:
            kept.append(parse_event(raw))
        except ValidationError as error:
            outcome.rejects.append(
                Reject(
                    raw,
                    f"schema: {error.error_count()} error(s), first {error.errors()[0]['type']}",
                    position=len(kept),
                )
            )
    outcome.events = kept


def _out_of_order(outcome: FaultOutcome, params: dict[str, Any]) -> None:
    events = outcome.events
    for i in range(0, len(events) - 1, 2):
        if events[i].event_time != events[i + 1].event_time:
            events[i], events[i + 1] = events[i + 1], events[i]


def _duplicate(outcome: FaultOutcome, params: dict[str, Any]) -> None:
    result: list[EnvelopeBase] = []
    for index, event in enumerate(outcome.events):
        result.append(event)
        if index % DUPLICATE_EVERY == 0:
            result.append(event)
    outcome.events = result


def _flood(outcome: FaultOutcome, params: dict[str, Any]) -> None:
    outcome.events = [e for e in outcome.events for _ in range(FLOOD_FACTOR)]


_APPLY = {
    FaultKind.GAP: _gap,
    FaultKind.DELAY: _delay,
    FaultKind.SCHEMA_DRIFT: _schema_drift,
    FaultKind.OUT_OF_ORDER: _out_of_order,
    FaultKind.DUPLICATE: _duplicate,
    FaultKind.FLOOD_10X: _flood,
}
