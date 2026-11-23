from __future__ import annotations

import psycopg
import pytest

from sgw.contracts.events import SOURCE_EVENTS
from sgw.ingest.scenario import load_scenario
from sgw.ingest.testing import ScratchDb, scratch_database
from sgw.pipeline import registry
from sgw.pipeline.replay import replay_scenario, reset_replay_state
from sgw.pipeline.runner import load_assets

pytestmark = pytest.mark.slow

MICRO_SOURCE_EVENTS = len(load_scenario("helene_micro").source_events())
FAULTS = {
    "FAULT_FEED_DUPLICATE": "*",
    "FAULT_FEED_OUT_OF_ORDER": "scada-water",
    "FAULT_FEED_DELAY": "oms:240",
    "FAULT_FEED_GAP": "scada-water",
    "FAULT_FEED_SCHEMA_DRIFT": "lims,fsm-crews",
}


def _source_count(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT count(*) FROM event WHERE type = ANY(%s)", (list(SOURCE_EVENTS),)).fetchone()
    return int(row[0]) if row else 0


def test_micro_replay_succeeds_with_zero_error_checks(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        report = replay_scenario(conn, "helene_micro", env={})
        assert report.ok and report.error_failures == 0
        assert {o.status for o in report.outcomes} == {"success"}
        assert report.ledger.gapless
        assert _source_count(conn) == MICRO_SOURCE_EVENTS
        runs = conn.execute("SELECT asset, status, code_version FROM pipeline_run ORDER BY asset").fetchall()
        assert [r[0] for r in runs] == [
            "ingest.feeds",
            "ledger.reconcile",
            "ledger.relay",
            "observations",
            "opendata.helene",
            "risk.snapshot",
            "surge.outages",
        ]
        checks = conn.execute(
            "SELECT count(*) FILTER (WHERE severity = 'error' AND NOT passed),"
            " count(*) FILTER (WHERE freshness_limit_s IS NOT NULL) FROM dq_check"
        ).fetchone()
        assert checks is not None and checks[0] == 0 and checks[1] >= 6
        health = conn.execute("SELECT count(*) FROM feed_health").fetchone()
        assert health is not None and health[0] == len(load_scenario("helene_micro").by_source())
        finished = conn.execute("SELECT count(*) FROM event WHERE type = 'PipelineRunFinished'").fetchone()
        assert finished is not None and finished[0] == 7


def test_replay_is_byte_identical_across_fresh_databases(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        first = replay_scenario(conn, "helene_micro", env={})
        with psycopg.connect(scratch_db.admin_url, autocommit=True) as owner:
            reset_replay_state(owner)
        second = replay_scenario(conn, "helene_micro", env={})
    with scratch_database("b") as other, psycopg.connect(other.runtime_url, autocommit=True) as conn:
        third = replay_scenario(conn, "helene_micro", env={})
    assert first.ledger_sha256 == second.ledger_sha256 == third.ledger_sha256
    assert first.ledger_events == third.ledger_events


def test_second_replay_resumes_and_from_start_is_absorbed(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        replay_scenario(conn, "helene_micro", env={})
        resumed = replay_scenario(conn, "helene_micro", env={})
        assert _source_count(conn) == MICRO_SOURCE_EVENTS
        ingest = next(o for o in resumed.outcomes if o.asset == "ingest.feeds")
        assert ingest.rows_in == 0
        again = replay_scenario(conn, "helene_micro", env={}, from_start=True)
        relay = next(o for o in again.outcomes if o.asset == "ledger.relay")
        assert relay.rows_in >= MICRO_SOURCE_EVENTS and _source_count(conn) == MICRO_SOURCE_EVENTS
        assert again.ok and again.ledger.gapless


def test_faults_are_absorbed_or_flagged(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        report = replay_scenario(conn, "helene_micro", env=FAULTS)
        assert report.ledger.gapless
        ingest = next(o for o in report.outcomes if o.asset == "ingest.feeds")
        failed = {c.name for c in ingest.failed_checks}
        assert {"ingest.duplicates_in_feed", "ingest.out_of_order"} <= failed
        assert ingest.rows_quarantined > 0 and ingest.status in ("partial", "failed")
        assert next(o for o in report.outcomes if o.asset == "ledger.reconcile").status == "success"
        keys = conn.execute("SELECT count(*), count(DISTINCT dedup_key) FROM event").fetchone()
        assert keys is not None and keys[0] == keys[1]
        gaps = conn.execute("SELECT source_id FROM coverage_gap").fetchall()
        assert gaps == [("scada-water",)]
        published = conn.execute(
            "SELECT count(*) FILTER (WHERE type = 'CoverageGap'),"
            " count(*) FILTER (WHERE type = 'DQCheckFailed') FROM event"
        ).fetchone()
        assert published is not None and published[0] == 1 and published[1] >= 2
        quarantined = conn.execute("SELECT count(*) FROM quarantine WHERE run_id IS NOT NULL").fetchone()
        assert quarantined is not None and quarantined[0] == ingest.rows_quarantined


def test_asset_exception_blocks_dependants_and_is_recorded(
    scratch_db: ScratchDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_assets()
    original = registry.REGISTRY["ledger.relay"]

    def boom(ctx: object, conn: object) -> registry.AssetResult:
        raise RuntimeError("relay host unreachable")

    broken = registry.AssetSpec("ledger.relay", boom, original.deps, None, "broken on purpose")
    monkeypatch.setitem(registry.REGISTRY, "ledger.relay", broken)
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        report = replay_scenario(conn, "helene_micro", env={})
        status = {o.asset: (o.status, o.error) for o in report.outcomes}
        assert status["ledger.relay"] == ("failed", "RuntimeError: relay host unreachable")
        assert status["ledger.reconcile"][0] == "failed"
        assert "upstream failed" in str(status["ledger.reconcile"][1])
        assert not report.ok
        row = conn.execute("SELECT error FROM pipeline_run WHERE asset = 'ledger.relay'").fetchone()
        assert row is not None and "unreachable" in row[0]


def test_relay_runs_when_ingest_raises_and_failed_run_keeps_cursors(
    scratch_db: ScratchDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_assets()
    original = registry.REGISTRY["ingest.feeds"]

    def half_then_boom(ctx: object, conn: psycopg.Connection) -> registry.AssetResult:
        from sgw.ingest import outbox
        from sgw.ingest.synthetic import meter_events

        with conn.transaction():
            outbox.enqueue(conn, meter_events("boom", 5), origin="test")
        raise RuntimeError("feed host vanished")

    monkeypatch.setitem(
        registry.REGISTRY,
        "ingest.feeds",
        registry.AssetSpec("ingest.feeds", half_then_boom, (), None, "fails after enqueue"),
    )
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        report = replay_scenario(conn, "helene_micro", env={})
        status = {o.asset: o.status for o in report.outcomes}
        assert status["ingest.feeds"] == "failed"
        assert status["ledger.relay"] == "success"
        assert status["ledger.reconcile"] == "failed"
        row = conn.execute("SELECT count(*) FROM event WHERE source_id = 'load-boom'").fetchone()
        assert row is not None and row[0] == 5
    monkeypatch.setitem(registry.REGISTRY, "ingest.feeds", original)
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        first = replay_scenario(conn, "helene_micro", env={"FAULT_FEED_SCHEMA_DRIFT": "ami-headend"})
        ingest = next(o for o in first.outcomes if o.asset == "ingest.feeds")
        assert ingest.status == "failed" and ingest.rows_quarantined > 0
        again = replay_scenario(conn, "helene_micro", env={"FAULT_FEED_SCHEMA_DRIFT": "ami-headend"})
        assert next(o for o in again.outcomes if o.asset == "ingest.feeds").rows_in == 0
        row = conn.execute("SELECT count(*) FROM quarantine WHERE source_id = 'ami-headend'").fetchone()
        assert row is not None and row[0] == ingest.rows_quarantined


def test_stale_running_rows_are_closed_on_start(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO pipeline_run (run_id, asset, status, started_at, code_version)"
            " VALUES ('replay.helene_micro.ingest.feeds.999999', 'ingest.feeds', 'running',"
            " now() - interval '2 hours', 'x')"
        )
        replay_scenario(conn, "helene_micro", env={})
        row = conn.execute(
            "SELECT status, error FROM pipeline_run WHERE run_id = 'replay.helene_micro.ingest.feeds.999999'"
        ).fetchone()
        assert row is not None and row[0] == "failed" and row[1].startswith("abandoned")


def test_lineage_marks_skipped_and_replay_runs_and_tallies_ingest_at_the_clock(scratch_db: ScratchDb) -> None:
    from datetime import UTC, datetime

    from sgw.ops import health

    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        replay_scenario(conn, "helene_micro", env={})
        assets = {a["name"]: a for a in health.lineage(conn)}
        assert assets["risk.snapshot"]["last_run"]["skipped"] is True
        assert assets["surge.outages"]["last_run"]["skipped"] is True
        assert assets["ingest.feeds"]["last_run"]["skipped"] is False
        assert all(a["last_run"]["replay"] for a in assets.values())
        at = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)
        listed = health.dq_checks(conn, asset=health.INGEST_ASSET, at=at)
        tally = {a["name"]: a for a in health.lineage(conn, at)}[health.INGEST_ASSET]["last_run"]["dq"]
        assert tally == {
            "checks": len(listed),
            "errors": sum(1 for c in listed if not c.passed and c.severity == "error"),
            "warnings": sum(1 for c in listed if not c.passed and c.severity == "warn"),
        }
