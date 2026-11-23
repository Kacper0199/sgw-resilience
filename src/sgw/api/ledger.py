"""Ledger access for the API: read pages by `ledger_seq`, read the head, append platform events.

Ledger frames are rendered from rows through `parse_event`, so stored events are upcast to the current K2
payload version before they reach the browser.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sgw.contracts.events import EVENT_MODELS, parse_event
from sgw.contracts.vocab import Classification, DegradedMode, FeedMode, KillLevel, RunMode, ScenarioMode

log = logging.getLogger("sgw.api.ledger")

PLATFORM_SOURCE = "sgw-platform"
RELAY_LOCK_KEY = 0x5347_5707
"""The WP-07 relay's advisory lock (`sgw.ingest.relay.RELAY_LOCK`). Platform events are numbered the way the
relay numbers its batches: under this transaction lock, `max(ledger_seq) + 1`, `OVERRIDING SYSTEM VALUE`, then
the identity is advanced and `NOTIFY sgw_ledger` sent. Both writers serialise on the lock and commit in seq
order, so the ledger stays gapless and a reader never sees seq n+1 before n."""
NOTIFY_CHANNEL = "sgw_ledger"
_ENVELOPE_COLUMNS = (
    "ledger_seq, event_id, type, schema_version, source_id, feed_mode, run_mode, event_time, issued_at,"
    " valid_at, received_at, known_at, scenario_known_at, dedup_key, classification, trust, quality,"
    " coverage_ppm, finality, supersedes, region_id, domain, payload"
)


@dataclass(frozen=True)
class LedgerRow:
    ledger_seq: int
    event_id: str
    event_type: str
    event_time: datetime
    run_mode: RunMode
    classification: Classification
    payload: dict[str, Any]


@dataclass(frozen=True)
class ControlSnapshot:
    kill_level: KillLevel
    degraded_mode: DegradedMode
    run_mode: RunMode
    scenario_mode: ScenarioMode
    scenario_clock: dict[str, Any]


def _row(raw: dict[str, Any]) -> LedgerRow:
    payload = raw["payload"]
    try:
        envelope = {k: v for k, v in raw.items() if v is not None or k in {"payload"}}
        envelope["event_id"] = str(raw["event_id"])
        if raw.get("supersedes") is not None:
            envelope["supersedes"] = str(raw["supersedes"])
        payload = parse_event(envelope).model_dump(mode="json")["payload"]
    except ValueError:
        log.warning("ledger row %s did not parse as K2; sent as stored", raw["ledger_seq"])
    return LedgerRow(
        ledger_seq=int(raw["ledger_seq"]),
        event_id=str(raw["event_id"]),
        event_type=str(raw["type"]),
        event_time=raw["event_time"],
        run_mode=RunMode(raw["run_mode"]),
        classification=Classification(raw["classification"]),
        payload=payload,
    )


async def head(conn: AsyncConnection[Any]) -> int:
    cur = await conn.execute("SELECT coalesce(max(ledger_seq), 0) FROM event")
    row = await cur.fetchone()
    return int(row[0]) if row else 0


async def fetch_after(conn: AsyncConnection[Any], after: int, upto: int, limit: int) -> list[LedgerRow]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT {_ENVELOPE_COLUMNS} FROM event WHERE ledger_seq > %s AND ledger_seq <= %s"  # noqa: S608
            " ORDER BY ledger_seq LIMIT %s",
            (after, upto, limit),
        )
        return [_row(r) for r in await cur.fetchall()]


async def database_epoch(conn: AsyncConnection[Any]) -> int:
    """Changes when the database is recreated, so a client holding ids from an older ledger gets `resync`."""
    cur = await conn.execute("SELECT oid::bigint FROM pg_database WHERE datname = current_database()")
    row = await cur.fetchone()
    return int(row[0]) if row else 0


async def ensure_control_row(conn: AsyncConnection[Any]) -> None:
    await conn.execute("INSERT INTO control_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING")


async def read_control(conn: AsyncConnection[Any]) -> ControlSnapshot | None:
    cur = await conn.execute(
        "SELECT kill_level, degraded_mode, run_mode, scenario_mode, scenario_clock"
        " FROM control_state WHERE id = 1"
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return ControlSnapshot(
        KillLevel(row[0]), DegradedMode(row[1]), RunMode(row[2]), ScenarioMode(row[3]), row[4]
    )


async def append_platform_event(
    conn: AsyncConnection[Any],
    *,
    type_name: str,
    payload: dict[str, Any],
    scenario_time: datetime,
    wall_now: datetime,
    run_mode: RunMode,
    dedup_key: str | None = None,
) -> int:
    event_id = uuid.uuid4()
    envelope = EVENT_MODELS[type_name].model_validate(
        {
            "type": type_name,
            "event_id": str(event_id),
            "source_id": PLATFORM_SOURCE,
            "feed_mode": (FeedMode.LIVE if run_mode is RunMode.LIVE else FeedMode.REPLAY).value,
            "run_mode": run_mode.value,
            "event_time": scenario_time,
            "received_at": wall_now,
            "known_at": wall_now,
            "scenario_known_at": scenario_time,
            "dedup_key": dedup_key or f"{PLATFORM_SOURCE}:{type_name}:{event_id}",
            "classification": Classification.C1.value,
            "trust": "system",
            "payload": payload,
        }
    )
    data = envelope.model_dump(mode="json")
    await conn.execute("SELECT pg_advisory_xact_lock(%s)", (RELAY_LOCK_KEY,))
    seq = await head(conn) + 1
    await conn.execute(
        "INSERT INTO event (event_id, type, schema_version, source_id, feed_mode, run_mode, event_time,"
        " received_at, known_at, scenario_known_at, ledger_seq, dedup_key, classification, trust, payload)"
        " OVERRIDING SYSTEM VALUE"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            event_id,
            type_name,
            data["schema_version"],
            PLATFORM_SOURCE,
            data["feed_mode"],
            data["run_mode"],
            scenario_time,
            wall_now,
            wall_now,
            scenario_time,
            seq,
            data["dedup_key"],
            data["classification"],
            data["trust"],
            Jsonb(data["payload"]),
        ),
    )
    await _advance_identity(conn, seq)
    await conn.execute("SELECT pg_notify(%s, %s)", (NOTIFY_CHANNEL, str(seq)))
    return seq


async def _advance_identity(conn: AsyncConnection[Any], target: int) -> None:
    """Keep the identity at or above the head so a stray default insert cannot reuse a number."""
    cur = await conn.execute("SELECT pg_get_serial_sequence('event', 'ledger_seq')")
    row = await cur.fetchone()
    if not row or not row[0]:
        return
    name = str(row[0])
    cur = await conn.execute(f"SELECT last_value, is_called FROM {name}")  # noqa: S608
    state = await cur.fetchone()
    current = int(state[0]) if state and state[1] else 0
    if current < target:
        await conn.execute(
            "SELECT count(nextval(%s::regclass)) FROM generate_series(1, %s)", (name, target - current)
        )


async def existing(conn: AsyncConnection[Any], seqs: list[int]) -> list[int]:
    cur = await conn.execute("SELECT ledger_seq FROM event WHERE ledger_seq = ANY(%s)", (seqs,))
    return sorted(int(r[0]) for r in await cur.fetchall())
