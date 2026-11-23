"""Ledger relay: drains the outbox into `event` with a gapless `ledger_seq`.

One transaction per batch, serialised by a transaction-scoped advisory lock. Sequence numbers are taken as
`max(ledger_seq) + 1 ...` and written with `OVERRIDING SYSTEM VALUE`, so a rolled-back batch leaves no hole
(an identity sequence would). Duplicates (same `dedup_key`) are acknowledged without a number. The identity
sequence is advanced to the head afterwards so a stray default insert cannot collide. After each commit the
relay sends `NOTIFY sgw_ledger, '<head>'` for SSE listeners.

The relay refuses to run inside a caller's transaction. A row the database refuses is retried alone in a
savepoint and dead-lettered (quarantine `ledger-relay`); a failed batch counts an attempt on every claimed
row, and a row is dead after `MAX_ATTEMPTS`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from sgw.contracts.events import EnvelopeBase, parse_event
from sgw.ingest.outbox import OUTBOX_KIND

RELAY_LOCK = 0x5347_5707
NOTIFY_CHANNEL = "sgw_ledger"
DEFAULT_BATCH = 1000
QUARANTINE_SOURCE = "ledger-relay"
MAX_ATTEMPTS = 5
ORD_EXPR = "(CASE WHEN payload->>'ord' ~ '^[0-9]{1,9}$' THEN (payload->>'ord')::int END)"
_COLUMNS = (
    "event_id",
    "type",
    "schema_version",
    "source_id",
    "feed_mode",
    "run_mode",
    "event_time",
    "issued_at",
    "valid_at",
    "received_at",
    "known_at",
    "scenario_known_at",
    "ledger_seq",
    "dedup_key",
    "classification",
    "trust",
    "quality",
    "coverage_ppm",
    "finality",
    "supersedes",
    "region_id",
    "domain",
    "payload",
)
_INSERT = (
    f"INSERT INTO event ({', '.join(_COLUMNS)}) OVERRIDING SYSTEM VALUE "  # noqa: S608
    f"VALUES ({', '.join(['%s'] * len(_COLUMNS))})"
)


@dataclass
class RelayResult:
    claimed: int = 0
    appended: int = 0
    duplicates: int = 0
    rejected: int = 0
    dangling_supersedes: int = 0
    first_seq: int | None = None
    head: int = 0
    seqs: list[int] = field(default_factory=list)


def _row(event: EnvelopeBase, seq: int, supersedes: UUID | None) -> tuple[Any, ...]:
    data = event.model_dump(mode="python")
    data["ledger_seq"] = seq
    data["supersedes"] = supersedes
    data["payload"] = Jsonb(event.model_dump(mode="json")["payload"])
    for key in ("feed_mode", "run_mode", "classification", "trust", "quality", "finality", "domain"):
        value = data.get(key)
        data[key] = getattr(value, "value", value)
    return tuple(data[c] for c in _COLUMNS)


def head(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT coalesce(max(ledger_seq), 0) FROM event").fetchone()
    return int(row[0]) if row else 0


class RelayInTransactionError(RuntimeError):
    pass


_CLAIM = (
    "SELECT job_id, payload FROM job WHERE kind = %s AND state = 'queued'"  # noqa: S608
    f" ORDER BY created_at, {ORD_EXPR}, job_id LIMIT %s FOR UPDATE SKIP LOCKED"
)


def relay_batch(conn: psycopg.Connection, *, limit: int = DEFAULT_BATCH) -> RelayResult:
    """Move one batch from the outbox to the ledger. Call on an idle autocommit connection, after the
    producers have committed: the relay owns its transaction, so a caller's rollback can never undo
    numbered events or hold the relay lock."""
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise RelayInTransactionError("relay_batch must run outside any transaction (enqueue, commit, drain)")
    claimed: list[UUID] = []
    try:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (RELAY_LOCK,))
            jobs = conn.execute(_CLAIM, (OUTBOX_KIND, limit)).fetchall()
            claimed = [j for j, _ in jobs]
            return _relay_locked(conn, jobs)
    except Exception:
        if claimed:
            _count_failed_attempt(conn, claimed)
        raise


def _count_failed_attempt(conn: psycopg.Connection, job_ids: list[UUID]) -> None:
    with conn.transaction():
        conn.execute(
            "UPDATE job SET attempts = attempts + 1,"
            " state = CASE WHEN attempts + 1 >= %s THEN 'dead' ELSE state END WHERE job_id = ANY(%s)",
            (MAX_ATTEMPTS, job_ids),
        )


def _parse(payload: object) -> EnvelopeBase | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("event"), dict):
        return None
    try:
        return parse_event(payload["event"])
    except (ValidationError, ValueError, KeyError, TypeError):
        return None


def _relay_locked(conn: psycopg.Connection, jobs: list[tuple[UUID, Any]]) -> RelayResult:
    result = RelayResult(head=head(conn))
    if not jobs:
        return result
    result.claimed = len(jobs)
    parsed = [(job_id, _parse(payload), payload) for job_id, payload in jobs]
    events = [e for _, e, _ in parsed if e is not None]
    known_keys = {
        r[0]
        for r in conn.execute(
            "SELECT dedup_key FROM event WHERE dedup_key = ANY(%s)", ([e.dedup_key for e in events],)
        )
    }
    known_ids = {
        r[0]
        for r in conn.execute(
            "SELECT event_id FROM event WHERE event_id = ANY(%s)", ([e.event_id for e in events],)
        )
    }
    refs = [e.supersedes for e in events if e.supersedes is not None]
    known_refs = {r[0] for r in conn.execute("SELECT event_id FROM event WHERE event_id = ANY(%s)", (refs,))}
    candidates: list[tuple[UUID, EnvelopeBase, UUID | None, Any]] = []
    dead: list[tuple[UUID, Any, str]] = []
    done: list[UUID] = []
    for job_id, event, payload in parsed:
        if event is None:
            dead.append((job_id, payload, "relay: payload is not a valid K2 envelope"))
            continue
        if event.dedup_key in known_keys:
            result.duplicates += 1
            done.append(job_id)
            continue
        if event.event_id in known_ids:
            dead.append((job_id, payload, f"relay: event_id {event.event_id} reused with a new dedup_key"))
            continue
        supersedes = event.supersedes
        if supersedes is not None and supersedes not in known_refs:
            result.dangling_supersedes += 1
            supersedes = None
        candidates.append((job_id, event, supersedes, payload))
        known_keys.add(event.dedup_key)
        known_ids.add(event.event_id)
        known_refs.add(event.event_id)
    seq = _insert(conn, candidates, result.head, result, done, dead)
    with conn.cursor() as cur:
        cur.execute("UPDATE job SET state = 'done', attempts = attempts + 1 WHERE job_id = ANY(%s)", (done,))
        if dead:
            cur.execute(
                "UPDATE job SET state = 'dead', attempts = attempts + 1 WHERE job_id = ANY(%s)",
                ([d[0] for d in dead],),
            )
            cur.executemany(
                "INSERT INTO quarantine (source_id, record, reason, run_id) VALUES (%s, %s, %s, NULL)",
                [(QUARANTINE_SOURCE, Jsonb(p), reason) for _, p, reason in dead],
            )
    result.rejected = len(dead)
    result.appended = len(result.seqs)
    result.first_seq = result.seqs[0] if result.seqs else None
    result.head = seq
    if result.seqs:
        _advance_identity(conn, seq)
        conn.execute("SELECT pg_notify(%s, %s)", (NOTIFY_CHANNEL, str(seq)))
    return result


def _insert(
    conn: psycopg.Connection,
    candidates: list[tuple[UUID, EnvelopeBase, UUID | None, Any]],
    start: int,
    result: RelayResult,
    done: list[UUID],
    dead: list[tuple[UUID, Any, str]],
) -> int:
    """Bulk insert in a savepoint; if the database refuses any row, retry one by one in savepoints so
    only the bad row is dead-lettered and the numbering stays contiguous."""
    if not candidates:
        return start
    rows = [_row(event, start + i + 1, sup) for i, (_, event, sup, _) in enumerate(candidates)]
    try:
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany(_INSERT, rows)
    except psycopg.Error:
        seq = start
        for job_id, event, sup, payload in candidates:
            try:
                with conn.transaction():
                    conn.execute(_INSERT, _row(event, seq + 1, sup))
            except psycopg.Error as error:
                reason = f"relay: insert refused: {type(error).__name__}: {str(error).splitlines()[0][:200]}"
                dead.append((job_id, payload, reason))
                continue
            seq += 1
            result.seqs.append(seq)
            done.append(job_id)
        return seq
    result.seqs.extend(range(start + 1, start + len(rows) + 1))
    done.extend(job_id for job_id, _, _, _ in candidates)
    return start + len(rows)


def _advance_identity(conn: psycopg.Connection, target: int) -> None:
    row = conn.execute("SELECT pg_get_serial_sequence('event', 'ledger_seq')").fetchone()
    if not row or not row[0]:
        return
    name = row[0]
    state = conn.execute(f"SELECT last_value, is_called FROM {name}").fetchone()  # noqa: S608
    current = int(state[0]) if state and state[1] else 0
    if current < target:
        conn.execute(
            "SELECT count(nextval(%s::regclass)) FROM generate_series(1, %s)", (name, target - current)
        )


def drain(conn: psycopg.Connection, *, limit: int = DEFAULT_BATCH, max_batches: int = 100_000) -> RelayResult:
    total = RelayResult()
    for _ in range(max_batches):
        batch = relay_batch(conn, limit=limit)
        total.claimed += batch.claimed
        total.appended += batch.appended
        total.duplicates += batch.duplicates
        total.rejected += batch.rejected
        total.dangling_supersedes += batch.dangling_supersedes
        total.seqs.extend(batch.seqs)
        total.head = batch.head
        if total.first_seq is None:
            total.first_seq = batch.first_seq
        if batch.claimed == 0:
            break
    return total


@dataclass(frozen=True)
class LedgerReport:
    count: int
    min_seq: int | None
    max_seq: int | None
    gaps: list[tuple[int, int]]

    @property
    def gapless(self) -> bool:
        if self.count == 0:
            return True
        return not self.gaps and self.min_seq == 1 and self.max_seq == self.count

    @property
    def first_bad_seq(self) -> int | None:
        if self.min_seq not in (None, 1):
            return 1
        return self.gaps[0][0] if self.gaps else None


def verify_ledger(conn: psycopg.Connection) -> LedgerReport:
    stats = conn.execute("SELECT count(*), min(ledger_seq), max(ledger_seq) FROM event").fetchone()
    assert stats is not None
    gaps = conn.execute(
        "SELECT prev + 1, ledger_seq - 1 FROM ("
        " SELECT ledger_seq, lag(ledger_seq) OVER (ORDER BY ledger_seq) AS prev FROM event) s"
        " WHERE ledger_seq - prev > 1 ORDER BY ledger_seq"
    ).fetchall()
    return LedgerReport(
        count=int(stats[0]),
        min_seq=stats[1],
        max_seq=stats[2],
        gaps=[(int(a), int(b)) for a, b in gaps],
    )
