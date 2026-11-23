"""Deterministic ledger export: one canonical K2 envelope per line in `ledger_seq` order. Two replays of a
scenario into fresh databases give byte-identical exports, which `ledger_sha256` pins."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from sgw.contracts.events import dump_event, parse_event

_SELECT = (
    "SELECT event_id, type, schema_version, source_id, feed_mode, run_mode, event_time, issued_at, valid_at,"
    " received_at, known_at, scenario_known_at, ledger_seq, dedup_key, classification, trust, quality,"
    " coverage_ppm, finality, supersedes, region_id, domain, payload FROM event"
    " WHERE ledger_seq > %s ORDER BY ledger_seq"
)


def iter_ledger(
    conn: psycopg.Connection, *, after_seq: int = 0, page: int = 5000
) -> Iterator[dict[str, Any]]:
    last = after_seq
    while True:
        with conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(_SELECT + " LIMIT %s", (last, page)).fetchall()
        if not rows:
            return
        for row in rows:
            yield dump_event(parse_event(row))
        last = int(rows[-1]["ledger_seq"])


def canonical_line(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def export_lines(conn: psycopg.Connection) -> Iterator[str]:
    for envelope in iter_ledger(conn):
        yield canonical_line(envelope) + "\n"


def ledger_sha256(conn: psycopg.Connection) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for line in export_lines(conn):
        digest.update(line.encode())
        count += 1
    return digest.hexdigest(), count


def export_ledger(conn: psycopg.Connection, path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for line in export_lines(conn):
            handle.write(line)
            digest.update(line.encode())
            count += 1
    return digest.hexdigest(), count
