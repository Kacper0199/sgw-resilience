"""Ledger adapter for approval events. Events are wrapped in K2 envelopes and queued through WP-07's
transactional outbox (`sgw.ingest.outbox.enqueue`) inside the same transaction as the approval state; after
commit `sgw.ingest.relay.drain` moves them into the ledger, so the sequence stays gapless. Approval code
never writes `event` rows itself."""

from __future__ import annotations

import importlib
import importlib.util
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

import psycopg

from sgw.contracts.base import Contract
from sgw.contracts.events import EVENT_MODELS, EnvelopeBase
from sgw.contracts.vocab import Classification, FeedMode, RunMode, Trust

ORIGIN = "approval"
SOURCE_ID = "sgw-platform"
NAMESPACE = uuid.UUID("0b9f6a1e-4c1d-4f55-9a09-0a5e17c09a0a")


class LedgerSink(Protocol):
    def enqueue(self, conn: psycopg.Connection[Any], events: Sequence[EnvelopeBase]) -> int: ...

    def drain(self, conn: psycopg.Connection[Any]) -> None: ...


def envelope(
    payload: Contract,
    *,
    at: datetime,
    key: str,
    region_id: str | None,
    domain: str | None,
    classification: Classification = Classification.C1,
    run_mode: RunMode = RunMode.REPLAY,
) -> EnvelopeBase:
    """K2 envelope for a platform event; `key` makes the dedup key and event id deterministic."""
    type_name = type(payload).__name__
    dedup = f"{ORIGIN}:{type_name}:{key}"
    return EVENT_MODELS[type_name].model_validate(
        {
            "type": type_name,
            "event_id": uuid.uuid5(NAMESPACE, dedup),
            "source_id": SOURCE_ID,
            "feed_mode": FeedMode.SYNTHETIC,
            "run_mode": run_mode,
            "event_time": at,
            "received_at": at,
            "known_at": at,
            "scenario_known_at": at,
            "dedup_key": dedup,
            "classification": classification,
            "trust": Trust.SYSTEM,
            "region_id": region_id,
            "domain": domain,
            "payload": payload,
        }
    )


class OutboxSink:
    """WP-07 outbox and relay; imported lazily so this package does not depend on `sgw.ingest` at import."""

    def __init__(self) -> None:
        self._outbox = importlib.import_module("sgw.ingest.outbox")
        self._relay = importlib.import_module("sgw.ingest.relay")

    def enqueue(self, conn: psycopg.Connection[Any], events: Sequence[EnvelopeBase]) -> int:
        return int(self._outbox.enqueue(conn, list(events), origin=ORIGIN))

    def drain(self, conn: psycopg.Connection[Any]) -> None:
        self._relay.drain(conn)


class MemorySink:
    """Test double with the same interface: records what was queued and what a drain would publish."""

    def __init__(self) -> None:
        self.queued: list[EnvelopeBase] = []
        self.drained: list[EnvelopeBase] = []
        self.drain_states: list[tuple[bool, str]] = []

    def enqueue(self, conn: psycopg.Connection[Any], events: Sequence[EnvelopeBase]) -> int:
        self.queued.extend(events)
        return len(events)

    def drain(self, conn: psycopg.Connection[Any]) -> None:
        self.drain_states.append((conn.autocommit, conn.info.transaction_status.name))
        self.drained.extend(self.queued[len(self.drained) :])


def default_sink() -> LedgerSink | None:
    try:
        available = importlib.util.find_spec("sgw.ingest.outbox") is not None
    except ModuleNotFoundError:
        available = False
    return OutboxSink() if available else None
