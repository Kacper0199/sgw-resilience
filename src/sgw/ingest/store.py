"""Idempotent writes that travel with the outbox in one transaction: observations (natural key + upsert),
adapter health, quarantine (one row per distinct record and reason) and coverage gaps."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

import psycopg
from psycopg.types.json import Jsonb

from sgw.contracts.adapter import AdapterHealth
from sgw.contracts.events import EnvelopeBase
from sgw.ingest.faults import GapWindow, Reject


def value_hash(value: float, unit: str) -> str:
    return hashlib.sha256(json.dumps([repr(float(value)), unit]).encode()).hexdigest()


def observation_rows(events: Sequence[EnvelopeBase]) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for e in events:
        if e.type != "DeviceState":
            continue
        payload = e.payload  # type: ignore[attr-defined]
        value = payload.value
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        unit = payload.unit or ""
        rows.append(
            (
                e.source_id,
                f"{payload.device_id}/{payload.tag}",
                payload.asset_id,
                e.region_id,
                e.domain.value if e.domain else None,
                e.event_time,
                e.known_at,
                float(value),
                unit,
                e.quality.value,
                e.finality.value,
                value_hash(value, unit),
            )
        )
    return rows


def upsert_observations(conn: psycopg.Connection, events: Sequence[EnvelopeBase]) -> int:
    rows = observation_rows(events)
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO observation (source_id, tag, asset_id, region_id, domain, observed_at, known_at,"
            " value, unit, quality, finality, value_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
            " %s, %s) ON CONFLICT (source_id, tag, observed_at, value_hash) DO NOTHING",
            rows,
        )
        return max(cur.rowcount, 0)


def record_health(conn: psycopg.Connection, health: AdapterHealth, freshness_limit_s: int) -> None:
    conn.execute(
        "INSERT INTO adapter_health (source_id, feed_mode, last_success_at, ingest_lag_s, product_age_s,"
        " error_rate_ppm, freshness_limit_s, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, now())"
        " ON CONFLICT (source_id) DO UPDATE SET feed_mode = EXCLUDED.feed_mode,"
        " last_success_at = coalesce(EXCLUDED.last_success_at, adapter_health.last_success_at),"
        " ingest_lag_s = EXCLUDED.ingest_lag_s, product_age_s = EXCLUDED.product_age_s,"
        " error_rate_ppm = EXCLUDED.error_rate_ppm, freshness_limit_s = EXCLUDED.freshness_limit_s,"
        " updated_at = now()",
        (
            health.source_id,
            health.feed_mode.value,
            health.last_success_at,
            health.ingest_lag_s,
            health.product_age_s,
            health.error_rate_ppm,
            freshness_limit_s,
        ),
    )


def quarantine(
    conn: psycopg.Connection, source_id: str, rejects: Sequence[Reject], run_id: str | None
) -> int:
    if not rejects:
        return 0
    with conn.cursor() as cur:
        added = 0
        for r in rejects:
            cur.execute(
                "INSERT INTO quarantine (source_id, record, reason, run_id) SELECT %s, %s, %s, %s"
                " WHERE NOT EXISTS (SELECT 1 FROM quarantine WHERE source_id = %s AND record = %s"
                " AND reason = %s)",
                (source_id, Jsonb(r.record), r.reason, run_id, source_id, Jsonb(r.record), r.reason),
            )
            added += cur.rowcount
    return added


def record_gaps(conn: psycopg.Connection, source_id: str, gaps: Sequence[GapWindow], reason: str) -> int:
    added = 0
    for gap in gaps:
        exists = conn.execute(
            "SELECT 1 FROM coverage_gap WHERE source_id = %s AND from_ts = %s AND to_ts = %s",
            (source_id, gap.from_utc, gap.to_utc),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO coverage_gap (source_id, from_ts, to_ts, reason) VALUES (%s, %s, %s, %s)",
            (source_id, gap.from_utc, gap.to_utc, reason),
        )
        added += 1
    return added
