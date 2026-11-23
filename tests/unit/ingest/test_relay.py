from __future__ import annotations

import uuid

import psycopg
import pytest

from sgw.ingest import ledger, outbox, relay
from sgw.ingest.synthetic import meter_events
from sgw.ingest.testing import ScratchDb

pytestmark = pytest.mark.slow


def _enqueue(conn: psycopg.Connection, events: list, origin: str = "test") -> None:  # type: ignore[type-arg]
    with conn.transaction():
        outbox.enqueue(conn, events, origin=origin)


def test_relay_assigns_contiguous_sequence_and_skips_duplicates(scratch_db: ScratchDb) -> None:
    events = meter_events("a", 25)
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        _enqueue(conn, events)
        _enqueue(conn, events[:5] + events[:5])
        result = relay.drain(conn, limit=7)
        assert result.appended == 25
        assert result.duplicates == 10
        assert result.seqs == list(range(1, 26))
        assert relay.verify_ledger(conn).gapless
        assert outbox.pending(conn) == 0


def _fail_after_insert(conn: psycopg.Connection, target: int) -> None:
    raise RuntimeError("relay crashed after numbering")


def test_rolled_back_batch_leaves_no_gap_and_counts_an_attempt(
    scratch_db: ScratchDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        _enqueue(conn, meter_events("b", 10))
        with monkeypatch.context() as patch:
            patch.setattr(relay, "_advance_identity", _fail_after_insert)
            with pytest.raises(RuntimeError, match="crashed"):
                relay.relay_batch(conn)
        assert relay.verify_ledger(conn).count == 0
        assert outbox.pending(conn) == 10
        row = conn.execute("SELECT min(attempts), max(attempts) FROM job").fetchone()
        assert row == (1, 1)
        relay.drain(conn)
        report = relay.verify_ledger(conn)
        assert report.gapless and report.max_seq == 10


def test_relay_refuses_to_run_inside_a_caller_transaction(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        _enqueue(conn, meter_events("t", 2))
        with conn.transaction(), pytest.raises(relay.RelayInTransactionError):
            relay.relay_batch(conn)
        assert relay.drain(conn).appended == 2


def test_repeated_failures_dead_letter_the_batch(
    scratch_db: ScratchDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        _enqueue(conn, meter_events("r", 3))
        monkeypatch.setattr(relay, "_advance_identity", _fail_after_insert)
        for _ in range(relay.MAX_ATTEMPTS):
            with pytest.raises(RuntimeError):
                relay.relay_batch(conn)
        assert outbox.pending(conn) == 0
        row = conn.execute("SELECT count(*) FROM job WHERE state = 'dead'").fetchone()
        assert row is not None and row[0] == 3


def test_poison_row_refused_by_the_database_is_dead_lettered_alone(scratch_db: ScratchDb) -> None:
    good = meter_events("p", 4)
    poison = good[1].model_copy(
        update={"region_id": "POISON", "dedup_key": "s11:p:poison", "event_id": uuid.uuid4()}
    )
    with psycopg.connect(scratch_db.admin_url, autocommit=True) as admin:
        admin.execute("ALTER TABLE event ADD CONSTRAINT test_refuse_poison CHECK (region_id <> 'POISON')")
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        _enqueue(conn, [good[0], poison, *good[1:]])
        result = relay.drain(conn)
        assert (result.appended, result.rejected) == (4, 1)
        assert result.seqs == [1, 2, 3, 4]
        assert relay.verify_ledger(conn).gapless
        reason = conn.execute("SELECT reason FROM quarantine WHERE source_id = 'ledger-relay'").fetchone()
        assert reason is not None and reason[0].startswith("relay: insert refused")


def test_non_numeric_ord_does_not_break_the_claim(scratch_db: ScratchDb) -> None:
    from psycopg.types.json import Jsonb

    from sgw.contracts.events import dump_event

    event = meter_events("o", 1)[0]
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO job (kind, payload) VALUES (%s, %s)",
            (outbox.OUTBOX_KIND, Jsonb({"origin": "x", "ord": "first", "event": dump_event(event)})),
        )
        conn.execute("INSERT INTO job (kind, payload) VALUES (%s, %s)", (outbox.OUTBOX_KIND, Jsonb([1, 2])))
        result = relay.drain(conn)
        assert (result.appended, result.rejected) == (1, 1)


def test_purge_keeps_dead_and_recent_rows(scratch_db: ScratchDb) -> None:
    from datetime import timedelta

    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        _enqueue(conn, meter_events("g", 3))
        relay.drain(conn)
        assert outbox.purge_done(conn) == 0
        assert outbox.purge_done(conn, older_than=timedelta(0)) == 3


def test_runtime_role_cannot_rewrite_the_ledger(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        _enqueue(conn, meter_events("l", 1))
        relay.drain(conn)
        for statement in ("UPDATE event SET region_id = 'x'", "DELETE FROM event"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)


def test_identity_sequence_follows_the_relay(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        _enqueue(conn, meter_events("c", 3))
        relay.drain(conn)
        row = conn.execute(
            "SELECT nextval(pg_get_serial_sequence('event', 'ledger_seq')::regclass)"
        ).fetchone()
        assert row is not None and row[0] == 4


def test_gap_is_reported_with_first_bad_seq(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        _enqueue(conn, meter_events("d", 6))
        relay.drain(conn)
    with psycopg.connect(scratch_db.admin_url, autocommit=True) as admin:
        admin.execute("DELETE FROM event WHERE ledger_seq = 4")
        report = relay.verify_ledger(admin)
    assert not report.gapless
    assert report.gaps == [(4, 4)]
    assert report.first_bad_seq == 4


def test_invalid_outbox_row_is_quarantined_not_numbered(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        _enqueue(conn, meter_events("e", 2))
        conn.execute(
            "INSERT INTO job (kind, payload, created_at) VALUES (%s, %s::jsonb, clock_timestamp())",
            (outbox.OUTBOX_KIND, '{"origin": "test", "ord": 0, "event": {"type": "MeterEvent"}}'),
        )
        _enqueue(conn, meter_events("e", 3)[2:])
        result = relay.drain(conn)
        assert (result.appended, result.rejected) == (3, 1)
        assert relay.verify_ledger(conn).gapless
        row = conn.execute("SELECT count(*) FROM quarantine WHERE source_id = 'ledger-relay'").fetchone()
        assert row is not None and row[0] == 1


def test_export_round_trips_and_is_stable(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        _enqueue(conn, meter_events("f", 12))
        relay.drain(conn)
        first = ledger.ledger_sha256(conn)
        second = ledger.ledger_sha256(conn)
        lines = list(ledger.export_lines(conn))
    assert first == second and first[1] == 12
    assert '"ledger_seq":1,' in lines[0]


def test_observation_upsert_is_idempotent(scratch_db: ScratchDb) -> None:
    from sgw.ingest import store
    from sgw.ingest.scenario import load_scenario

    readings = [e for e in load_scenario("helene_micro").source_events() if e.type == "DeviceState"]
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        first = store.upsert_observations(conn, readings)
        second = store.upsert_observations(conn, readings)
        row = conn.execute("SELECT count(*) FROM observation").fetchone()
    assert first == len(store.observation_rows(readings)) > 0
    assert second == 0 and row is not None and row[0] == first
