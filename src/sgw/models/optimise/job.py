"""Async SAA job on the K1 `job` table: enqueue returns at once; a worker claims one row (SKIP LOCKED, lease),
solves outside any transaction, stores the plan document as a `crew_plan` snapshot and marks the row done.
A failure, or a lease that expired while 'running' (a dead worker), counts an attempt; the row is dead after
`MAX_ATTEMPTS`. Outbox rows are never claimed."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from sgw.common.telemetry import sgw_span
from sgw.contracts.vocab import Classification, RunMode
from sgw.models.optimise.coa import ENGINE_VERSION, run
from sgw.models.optimise.plan import document
from sgw.models.optimise.scenarios import build_context

JOB_KIND = "optimise.saa"
SNAPSHOT_KIND = "crew_plan"
MAX_ATTEMPTS = 3
LEASE_MINUTES = 10


@dataclass(frozen=True)
class JobResult:
    job_id: str
    snapshot_id: str
    seconds: float


def enqueue(conn: psycopg.Connection, *, scenario: str, advisory: str, requested_by: str, **opts: Any) -> str:
    payload = {"scenario": scenario, "advisory": advisory, "requested_by": requested_by, "opts": opts}
    row = conn.execute(
        "INSERT INTO job (kind, payload, state, created_at) VALUES (%s, %s, 'queued', clock_timestamp())"
        " RETURNING job_id",
        (JOB_KIND, Jsonb(payload)),
    ).fetchone()
    assert row is not None
    return str(row[0])


def snapshot_id(scenario: str, advisory: str, digest: str) -> str:
    return f"CRP-{scenario.upper()}-{advisory.replace('+', 'P')}-{digest[:12]}"


def digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def reclaim_expired(conn: psycopg.Connection) -> int:
    """A worker that died mid-run leaves its row 'running' past the lease: count the attempt and requeue it
    (dead after `MAX_ATTEMPTS`)."""
    return conn.execute(
        "UPDATE job SET attempts = attempts + 1, lease_token = NULL, locked_until = NULL,"
        " state = CASE WHEN attempts + 1 >= %s THEN 'dead' ELSE 'queued' END"
        " WHERE kind = %s AND state = 'running' AND locked_until < clock_timestamp()",
        (MAX_ATTEMPTS, JOB_KIND),
    ).rowcount


def _claim(conn: psycopg.Connection) -> tuple[str, dict[str, Any], str] | None:
    lease = str(uuid.uuid4())
    with conn.transaction():
        reclaim_expired(conn)
        row = conn.execute(
            "SELECT job_id, payload FROM job WHERE kind = %s AND state = 'queued'"
            " AND (locked_until IS NULL OR locked_until < clock_timestamp())"
            " ORDER BY created_at, job_id LIMIT 1 FOR UPDATE SKIP LOCKED",
            (JOB_KIND,),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE job SET state = 'running', lease_token = %s,"
            " locked_until = clock_timestamp() + make_interval(mins => %s) WHERE job_id = %s",
            (lease, LEASE_MINUTES, row[0]),
        )
    return str(row[0]), dict(row[1]), lease


def compute(payload: dict[str, Any]) -> dict[str, Any]:
    opts = dict(payload.get("opts") or {})
    ctx = build_context(str(payload["scenario"]), str(payload["advisory"]))
    return document(run(ctx, **opts))


def work_one(conn: psycopg.Connection, *, run_id: str | None = None) -> JobResult | None:
    """Claim and run one job. The connection must be idle (autocommit)."""
    claimed = _claim(conn)
    if claimed is None:
        return None
    job_id, payload, lease = claimed
    started = datetime.now(UTC)
    try:
        with sgw_span(
            "optimise.saa",
            run_id=run_id or f"job:{job_id}",
            classification=Classification.C1,
            user_role="system",
            run_mode=RunMode.REPLAY,
            node="optimise",
        ):
            doc = compute(payload)
    except Exception:
        with conn.transaction():
            conn.execute(
                "UPDATE job SET attempts = attempts + 1, locked_until = NULL, lease_token = NULL,"
                " state = CASE WHEN attempts + 1 >= %s THEN 'dead' ELSE 'queued' END"
                " WHERE job_id = %s AND lease_token = %s",
                (MAX_ATTEMPTS, job_id, lease),
            )
        raise
    dig = digest(doc)
    sid = snapshot_id(str(payload["scenario"]), str(payload["advisory"]), dig)
    doc["job_id"] = job_id
    doc["requested_by"] = payload.get("requested_by")
    with conn.transaction():
        conn.execute(
            "INSERT INTO snapshot (snapshot_id, kind, as_of, engine_version, hash, output)"
            " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (snapshot_id) DO NOTHING",
            (sid, SNAPSHOT_KIND, doc["issued_utc"], ENGINE_VERSION, digest(doc), Jsonb(doc)),
        )
        updated = conn.execute(
            "UPDATE job SET state = 'done', locked_until = NULL, payload = payload || %s"
            " WHERE job_id = %s AND lease_token = %s",
            (Jsonb({"snapshot_id": sid}), job_id, lease),
        ).rowcount
        if updated != 1:
            raise RuntimeError(f"job {job_id} lost its lease before completion")
    return JobResult(job_id, sid, (datetime.now(UTC) - started).total_seconds())


def status(conn: psycopg.Connection, job_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT state, attempts, payload->>'snapshot_id' FROM job WHERE job_id = %s AND kind = %s",
        (job_id, JOB_KIND),
    ).fetchone()
    if row is None:
        return None
    return {"job_id": job_id, "state": row[0], "attempts": row[1], "snapshot_id": row[2]}
