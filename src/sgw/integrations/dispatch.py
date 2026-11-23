"""Fan-out from the ledger to webhook deliveries (transactional, idempotent, gapless).

The dispatcher keeps one cursor (`integration_cursor.name = 'webhooks'`). Under a transaction-scoped advisory
lock it reads ledger rows after the cursor (up to `batch`), inserts one `webhook_delivery` per matching
active subscription whose token is still valid and whose `after_seq` is below the row, and advances the
cursor in the same transaction. A crash before commit leaves nothing; a rerun inserts nothing twice
(`UNIQUE (subscription_id, event_id)` and a deterministic delivery id). The ledger is committed in seq order
under the relay lock, so reading up to the current head never skips a row that commits later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection

from sgw.contracts.events import WEBHOOK_EVENT_TYPES
from sgw.integrations.payload import delivery_id

CURSOR = "webhooks"
DISPATCH_LOCK = 0x5347_5737
DEFAULT_BATCH = 500


@dataclass(frozen=True)
class DispatchResult:
    scanned_to: int
    created: int


async def dispatch_once(
    conn: AsyncConnection[Any], now: datetime, batch: int = DEFAULT_BATCH
) -> DispatchResult:
    """One batch in its own transaction; call until `created == 0` and the cursor stops moving."""
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(%s)", (DISPATCH_LOCK,))
        await conn.execute(
            "INSERT INTO integration_cursor (name, last_seq) VALUES (%s, 0) ON CONFLICT (name) DO NOTHING",
            (CURSOR,),
        )
        cur = await conn.execute(
            "SELECT last_seq FROM integration_cursor WHERE name = %s FOR UPDATE", (CURSOR,)
        )
        row = await cur.fetchone()
        after = int(row[0]) if row else 0
        cur = await conn.execute(
            "SELECT max(ledger_seq) FROM (SELECT ledger_seq FROM event WHERE ledger_seq > %s"
            " ORDER BY ledger_seq LIMIT %s) page",
            (after, batch),
        )
        top_row = await cur.fetchone()
        if not top_row or top_row[0] is None:
            return DispatchResult(after, 0)
        upto = int(top_row[0])
        cur = await conn.execute(
            "SELECT s.subscription_id, e.event_id::text FROM event e"
            " JOIN webhook_subscription s ON e.type = ANY(s.event_types) AND e.ledger_seq > s.after_seq"
            " JOIN api_token t ON t.token_id = s.token_id"
            " WHERE e.ledger_seq > %s AND e.ledger_seq <= %s AND e.type = ANY(%s)"
            " AND s.active AND t.revoked_at IS NULL AND t.expires_at > %s"
            " ORDER BY e.ledger_seq, s.subscription_id",
            (after, upto, list(WEBHOOK_EVENT_TYPES), now),
        )
        pairs = [(str(r[0]), str(r[1])) for r in await cur.fetchall()]
        created = 0
        for subscription_id, event_id in pairs:
            ins = await conn.execute(
                "INSERT INTO webhook_delivery (delivery_id, subscription_id, event_id, state, created_at,"
                " next_attempt_at) VALUES (%s, %s, %s, 'pending', %s, %s)"
                " ON CONFLICT (subscription_id, event_id) DO NOTHING",
                (delivery_id(subscription_id, event_id), subscription_id, event_id, now, now),
            )
            created += ins.rowcount
        await conn.execute(
            "UPDATE integration_cursor SET last_seq = %s, updated_at = %s WHERE name = %s",
            (upto, now, CURSOR),
        )
        return DispatchResult(upto, created)


async def dispatch_all(conn: AsyncConnection[Any], now: datetime, batch: int = DEFAULT_BATCH) -> int:
    total = 0
    last = -1
    while True:
        result = await dispatch_once(conn, now, batch)
        total += result.created
        if result.scanned_to == last:
            return total
        last = result.scanned_to
