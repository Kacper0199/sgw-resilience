"""Transactional outbox. Producers write K2 envelopes as `job` rows of kind `ledger.append` in the same
transaction as their own state; only the relay (`sgw.ingest.relay`) moves them into the ledger and gives
them a `ledger_seq`. Every ledger writer goes through here, so the sequence stays gapless.

Rule for producers: `enqueue` inside your own transaction, commit, then call `relay.drain(conn)` on the
idle connection (the relay refuses to run inside a transaction). Generic job workers must claim with
`GENERIC_JOB_FILTER`, so they never take outbox rows. `purge_done` deletes relayed rows after a grace period;
dead rows stay for inspection."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

import psycopg
from psycopg.types.json import Jsonb

from sgw.contracts.events import EnvelopeBase, dump_event

OUTBOX_KIND = "ledger.append"
GENERIC_JOB_FILTER = "kind <> 'ledger.append'"
DEFAULT_PURGE_AFTER = timedelta(hours=1)


def enqueue(conn: psycopg.Connection, events: Sequence[EnvelopeBase], *, origin: str) -> int:
    """Queue events in the given order; call inside the producer's transaction."""
    if not events:
        return 0
    rows = [
        (OUTBOX_KIND, Jsonb({"origin": origin, "ord": index, "event": dump_event(event)}))
        for index, event in enumerate(events)
    ]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO job (kind, payload, state, created_at) VALUES (%s, %s, 'queued', clock_timestamp())",
            rows,
        )
    return len(rows)


def pending(conn: psycopg.Connection) -> int:
    row = conn.execute(
        "SELECT count(*) FROM job WHERE kind = %s AND state = 'queued'", (OUTBOX_KIND,)
    ).fetchone()
    return int(row[0]) if row else 0


def purge_done(conn: psycopg.Connection, *, older_than: timedelta = DEFAULT_PURGE_AFTER) -> int:
    return conn.execute(
        "DELETE FROM job WHERE kind = %s AND state = 'done' AND created_at < clock_timestamp() - %s",
        (OUTBOX_KIND, older_than),
    ).rowcount


def pending_before(conn: psycopg.Connection, cutoff: object) -> int:
    row = conn.execute(
        "SELECT count(*) FROM job WHERE kind = %s AND state = 'queued' AND created_at <= %s",
        (OUTBOX_KIND, cutoff),
    ).fetchone()
    return int(row[0]) if row else 0
