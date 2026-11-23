"""Append-only, hash-chained audit records (K1 `audit_event`, stream `global`).

`hash = sha256(RFC 8785 of the record header incl. prev_hash and payload_hash)`. Writers serialise on a
transaction-scoped advisory lock so `seq` is gapless and the chain is linear. WP-09b owns the verifier and the
signed checkpoints; this module is the single writer the API uses until then.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from psycopg import AsyncConnection

from sgw.contracts.approval import canonical_json, sha256_hex
from sgw.contracts.base import utc_iso

AUDIT_LOCK_KEY = 0x5347_5741  # "SGWA"
GENESIS_HASH = "0" * 64
ActorType = Literal["user", "system", "agent"]


def record_hash(header: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(header))


async def append(
    conn: AsyncConnection[Any],
    *,
    kind: str,
    actor_type: ActorType,
    actor_id: str,
    subject: str,
    payload: dict[str, Any],
    occurred_at: datetime,
    stream: str = "global",
) -> int:
    await conn.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_LOCK_KEY,))
    cur = await conn.execute(
        "SELECT seq, hash FROM audit_event WHERE stream = %s ORDER BY seq DESC LIMIT 1", (stream,)
    )
    last = await cur.fetchone()
    seq, prev_hash = (int(last[0]) + 1, str(last[1])) if last else (1, GENESIS_HASH)
    payload_hash = sha256_hex(canonical_json(payload))
    event_key = f"{kind}:{uuid.uuid4()}"
    header = {
        "stream": stream,
        "seq": seq,
        "event_key": event_key,
        "occurred_at": utc_iso(occurred_at),
        "actor_type": actor_type,
        "actor_id": actor_id,
        "kind": kind,
        "subject": subject,
        "payload_hash": payload_hash,
        "prev_hash": prev_hash,
    }
    await conn.execute(
        "INSERT INTO audit_event (stream, seq, event_key, occurred_at, actor_type, actor_id, kind, subject,"
        " payload_hash, payload, prev_hash, hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            stream,
            seq,
            event_key,
            occurred_at,
            actor_type,
            actor_id,
            kind,
            subject,
            payload_hash,
            _jsonb(payload),
            prev_hash,
            record_hash(header),
        ),
    )
    return seq


def _jsonb(value: dict[str, Any]) -> Any:
    from psycopg.types.json import Jsonb

    return Jsonb(value)
