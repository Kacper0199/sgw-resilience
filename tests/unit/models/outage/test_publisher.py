from __future__ import annotations

import time
from datetime import UTC, datetime

from sgw.contracts.events import parse_event
from sgw.ingest.db import connect
from sgw.ingest.testing import ScratchDb
from sgw.models.outage.publisher import publish_tick

TICK_LIMIT_S = 60.0


def test_risk_snapshot_reaches_the_ledger_within_60_s_of_a_tick(scratch_db: ScratchDb) -> None:
    conn = connect(scratch_db.runtime_url)
    started = time.perf_counter()
    result = publish_tick(conn, datetime(2024, 9, 26, 15, 15, tzinfo=UTC))
    row = conn.execute(
        "SELECT ledger_seq, type, payload, event_id, source_id, feed_mode, run_mode, event_time, issued_at,"
        " received_at, known_at, scenario_known_at, dedup_key, classification, trust FROM event"
        " WHERE type = 'RiskSnapshotPublished'"
    ).fetchone()
    elapsed = time.perf_counter() - started
    assert row is not None and elapsed < TICK_LIMIT_S
    assert result.advisory_label == "N+1" and result.created and result.event_seq == row[0]
    payload = row[2]
    assert payload["snapshot_id"] == result.snapshot_id
    assert len(payload["top_entities"]) == 25
    event = parse_event(
        {
            "type": row[1],
            "payload": payload,
            "event_id": str(row[3]),
            "source_id": row[4],
            "feed_mode": row[5],
            "run_mode": row[6],
            "event_time": row[7].isoformat(),
            "issued_at": row[8].isoformat(),
            "received_at": row[9].isoformat(),
            "known_at": row[10].isoformat(),
            "scenario_known_at": row[11].isoformat(),
            "dedup_key": row[12],
            "classification": row[13],
            "trust": row[14],
        }
    )
    assert event.type == "RiskSnapshotPublished"
    counts = dict(conn.execute("SELECT level, count(*) FROM risk GROUP BY level").fetchall())
    assert counts == {"county": 123, "asset": 500}
    kinds = dict(conn.execute("SELECT kind, count(*) FROM snapshot GROUP BY kind").fetchall())
    assert kinds == {"risk": 1, "plan_diff": 1}
    assert conn.execute("SELECT count(*) FROM forecast").fetchone() == (123,)


def test_ticks_under_one_advisory_publish_one_snapshot(scratch_db: ScratchDb) -> None:
    conn = connect(scratch_db.runtime_url)
    first = publish_tick(conn, datetime(2024, 9, 26, 9, 30, tzinfo=UTC))
    second = publish_tick(conn, datetime(2024, 9, 26, 9, 45, tzinfo=UTC))
    again = publish_tick(conn, datetime(2024, 9, 26, 9, 30, tzinfo=UTC))
    assert first.created and not second.created and not again.created
    assert first.snapshot_id == second.snapshot_id and first.event_seq == second.event_seq
    assert conn.execute("SELECT count(*) FROM event").fetchone() == (1,)
    assert conn.execute("SELECT count(*) FROM snapshot WHERE kind = 'risk'").fetchone() == (1,)
    nxt = publish_tick(conn, datetime(2024, 9, 26, 15, 0, tzinfo=UTC))
    assert nxt.created and nxt.advisory_label == "N+1"


def test_a_tick_before_the_first_advisory_publishes_nothing(scratch_db: ScratchDb) -> None:
    conn = connect(scratch_db.runtime_url)
    result = publish_tick(conn, datetime(2024, 9, 23, 12, 0, tzinfo=UTC))
    assert result.snapshot_id is None and result.event_seq is None


def test_pipeline_asset_records_dq_checks_for_the_snapshot(scratch_db: ScratchDb) -> None:
    from sgw.contracts.vocab import FeedMode, RunMode
    from sgw.models.outage import asset as risk_asset
    from sgw.pipeline.context import RunContext
    from sgw.pipeline.registry import REGISTRY

    assert REGISTRY["risk.snapshot"].freshness_limit_s == risk_asset.FRESHNESS_S
    conn = connect(scratch_db.runtime_url)
    at = datetime(2024, 9, 26, 15, 0, tzinfo=UTC)
    skipped = risk_asset.risk_snapshot(
        RunContext("wp11", RunMode.REPLAY, FeedMode.SYNTHETIC, at, [], as_of=at), conn
    )
    assert skipped.checks == [] and "skipped" in skipped.watermarks
    env = {risk_asset.SCENARIO_ENV: "helene"}
    ctx = RunContext("wp11", RunMode.REPLAY, FeedMode.SYNTHETIC, at, [], as_of=at, env=env)
    result = risk_asset.risk_snapshot(ctx, conn)
    assert result.rows_out == 123
    assert all(c.passed for c in result.checks), result.checks
