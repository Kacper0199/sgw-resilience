"""Test helpers for the audit chain: a superuser who bypasses the insert-only triggers (SEC-52..54)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sgw.api.audit_log import record_hash
from sgw.approval import audit
from sgw.contracts.approval import canonical_json, sha256_hex


def new_stream() -> str:
    return f"t{uuid.uuid4().hex[:12]}"


def fill(conn: psycopg.Connection[Any], stream: str, n: int, start: datetime) -> list[audit.AuditRecord]:
    out = []
    with conn.transaction():
        for i in range(n):
            out.append(
                audit.append(
                    conn,
                    kind="test_event",
                    actor_type="system",
                    actor_id="system:test",
                    subject=f"subject-{i}",
                    payload={"i": i, "note": "synthetic"},
                    occurred_at=start + timedelta(seconds=i),
                    stream=stream,
                )
            )
    return out


def _as_superuser(conn: psycopg.Connection[Any]) -> None:
    conn.execute("SET session_replication_role = replica")


def tamper(admin_url: str, stream: str, seq: int, payload: dict[str, Any], *, recompute_chain: bool) -> None:
    """Edit one row's payload. With `recompute_chain` the attacker also recomputes payload_hash, the
    row's hash and every later prev_hash/hash, so the chain alone looks consistent (SEC-52)."""
    with psycopg.connect(admin_url, autocommit=True) as conn, conn.transaction():
        _as_superuser(conn)
        if not recompute_chain:
            conn.execute(
                "UPDATE audit_event SET payload = %s WHERE stream = %s AND seq = %s",
                (Jsonb(payload), stream, seq),
            )
            return
        with conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(
                f"SELECT {audit.ROW_COLUMNS} FROM audit_event WHERE stream = %s AND seq >= %s ORDER BY seq",  # noqa: S608
                (stream, seq),
            ).fetchall()
        prev = rows[0]["prev_hash"]
        for row in rows:
            if row["seq"] == seq:
                row["payload"] = payload
                row["payload_hash"] = sha256_hex(canonical_json(payload))
            row["prev_hash"] = prev
            row["hash"] = record_hash(audit.header_of(row))
            conn.execute(
                "UPDATE audit_event SET payload = %s, payload_hash = %s, prev_hash = %s, hash = %s"
                " WHERE stream = %s AND seq = %s",
                (
                    Jsonb(row["payload"]),
                    row["payload_hash"],
                    row["prev_hash"],
                    row["hash"],
                    stream,
                    row["seq"],
                ),
            )
            prev = row["hash"]


def delete_from(admin_url: str, stream: str, seq: int, *, checkpoints: bool = False) -> None:
    with psycopg.connect(admin_url, autocommit=True) as conn, conn.transaction():
        _as_superuser(conn)
        conn.execute("DELETE FROM audit_event WHERE stream = %s AND seq >= %s", (stream, seq))
        if checkpoints:
            conn.execute("DELETE FROM audit_checkpoint WHERE stream = %s AND seq >= %s", (stream, seq))


def swap(admin_url: str, stream: str, a: int, b: int) -> None:
    """Reorder two rows by exchanging their sequence numbers (SEC-54)."""
    with psycopg.connect(admin_url, autocommit=True) as conn, conn.transaction():
        _as_superuser(conn)
        conn.execute("UPDATE audit_event SET seq = -1 WHERE stream = %s AND seq = %s", (stream, a))
        conn.execute("UPDATE audit_event SET seq = %s WHERE stream = %s AND seq = %s", (a, stream, b))
        conn.execute("UPDATE audit_event SET seq = %s WHERE stream = %s AND seq = -1", (b, stream))
