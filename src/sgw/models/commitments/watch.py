"""Commitment drift: pure evaluation of a milestone schedule against observed ledger signals.

Projection: the first unmet milestone cannot finish before `max(now, due)`, and what remains after it takes
its planned `remaining_min`; a milestone met late pushes the promise by the same amount. The projected
completion is the latest of these, and drift is projected minus promised, in whole minutes (ceiling).
States: `on_track` (drift <= 0), `at_risk` (0 < drift <= tolerance), `drifted` (drift > tolerance), `met`
(every milestone met within tolerance of the promise), `missed` (every milestone met, the last one late).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from sgw.contracts.vocab import CommitmentState
from sgw.models.commitments.plan import Milestone


@dataclass(frozen=True)
class Assessment:
    state: CommitmentState
    projected_utc: datetime
    drift_min: int
    milestone_seq: int | None


def ceil_min(delta: timedelta) -> int:
    return math.ceil(delta.total_seconds() / 60.0)


def assess(
    milestones: Sequence[Milestone], promised_by_utc: datetime, now: datetime, tolerance_min: int
) -> Assessment:
    projected = promised_by_utc
    worst_seq: int | None = None
    for m in milestones:
        if m.met_utc is not None:
            candidate = m.met_utc + timedelta(minutes=m.remaining_min)
        else:
            candidate = max(now, m.due_utc) + timedelta(minutes=m.remaining_min)
        if candidate > projected:
            projected, worst_seq = candidate, m.seq
        if m.met_utc is None:
            break
    drift = ceil_min(projected - promised_by_utc)
    if all(m.met_utc is not None for m in milestones):
        state = CommitmentState.MET if drift <= tolerance_min else CommitmentState.MISSED
    elif drift > tolerance_min:
        state = CommitmentState.DRIFTED
    elif drift > 0:
        state = CommitmentState.AT_RISK
    else:
        state = CommitmentState.ON_TRACK
    return Assessment(state=state, projected_utc=projected, drift_min=max(drift, 0), milestone_seq=worst_seq)


def _payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = event.get("payload", {})
    return payload if isinstance(payload, Mapping) else {}


def event_time(event: Mapping[str, Any]) -> datetime:
    value = event["event_time"]
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def matches(signal: Mapping[str, Any], event: Mapping[str, Any]) -> bool:
    if event.get("type") != signal.get("type"):
        return False
    p = _payload(event)
    if "work_type" in signal and p.get("work_type") != signal["work_type"]:
        return False
    if "status_in" in signal and p.get("status") not in signal["status_in"]:
        return False
    if "asset_id" in signal and p.get("asset_id") != signal["asset_id"]:
        return False
    if "device_kind" in signal and p.get("device_kind") != signal["device_kind"]:
        return False
    if "min_value" in signal:
        value = p.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or value < float(signal["min_value"])
        ):
            return False
    return "location_in" not in signal or p.get("location_id") in set(signal["location_in"])


def observe(
    milestones: Sequence[Milestone], event: Mapping[str, Any], seen: dict[int, set[str]]
) -> list[Milestone]:
    """Mark milestones met by one ledger event, in order. `seen` keeps per-milestone locations for
    `all_locations` signals (every target yard must report)."""
    out = list(milestones)
    at = event_time(event)
    met_seqs = {m.seq: m.met_utc for m in out if m.met_utc is not None}
    for i, m in enumerate(out):
        if m.met_utc is not None or not matches(m.signal, event):
            continue
        after = m.signal.get("after_seq")
        if after is not None:
            prior = met_seqs.get(int(after))
            if prior is None or at < prior:
                continue
        if m.signal.get("all_locations"):
            locations = seen.setdefault(m.seq, set())
            locations.add(str(_payload(event).get("location_id")))
            if not set(m.signal.get("location_in", [])) <= locations:
                continue
        out[i] = replace(
            m, met_utc=at, met_event_id=str(event.get("event_id")) if event.get("event_id") else None
        )
        met_seqs[m.seq] = at
    return out
