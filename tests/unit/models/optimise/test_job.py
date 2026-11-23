from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

from sgw.ingest.testing import ScratchDb, scratch_database, server_available
from sgw.models.optimise.job import JOB_KIND, MAX_ATTEMPTS, SNAPSHOT_KIND, enqueue, status, work_one

SMALL = {"n_in": 10, "n_out": 40, "replications": 2, "n_evpi": 3, "n_cvar": 20}


@pytest.fixture
def scratch_db() -> Iterator[ScratchDb]:
    reason = server_available()
    if reason:
        pytest.skip(reason)  # sgw-allow-skip: database tests need the local Postgres stack (port 5434)
    with scratch_database("wp16") as db:
        yield db


def test_enqueued_job_returns_at_once_and_a_worker_stores_the_crew_plan(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        job_id = enqueue(conn, scenario="helene", advisory="N", requested_by="ops_dm_01", **SMALL)
        queued = {"job_id": job_id, "state": "queued", "attempts": 0, "snapshot_id": None}
        assert status(conn, job_id) == queued
        result = work_one(conn)
        assert result is not None and result.job_id == job_id
        done = status(conn, job_id)
        assert done is not None and done["state"] == "done" and done["snapshot_id"] == result.snapshot_id
        row = conn.execute(
            "SELECT kind, output->'plans', output->>'advisory' FROM snapshot WHERE snapshot_id = %s",
            (result.snapshot_id,),
        ).fetchone()
        assert row is not None and row[0] == SNAPSHOT_KIND and row[2] == "N"
        assert [p["plan_id"] for p in row[1]] == ["P50", "EV", "COA-A", "COA-B", "COA-C"]
        assert work_one(conn) is None


def test_a_failing_job_is_retried_then_dead_and_outbox_rows_are_never_claimed(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        conn.execute("INSERT INTO job (kind, payload, state) VALUES ('ledger.append', '{}'::jsonb, 'queued')")
        job_id = enqueue(conn, scenario="no-such-scenario", advisory="N", requested_by="ops_dm_01")
        for _ in range(3):
            with pytest.raises(Exception):  # noqa: B017
                work_one(conn)
        final = status(conn, job_id)
        assert final is not None and final["state"] == "dead" and final["attempts"] == 3
        assert work_one(conn) is None
        outbox = conn.execute("SELECT state FROM job WHERE kind = 'ledger.append'").fetchone()
        assert outbox == ("queued",)
        kinds = conn.execute("SELECT DISTINCT kind FROM job ORDER BY 1").fetchall()
        assert [k[0] for k in kinds] == ["ledger.append", JOB_KIND]


def test_a_running_job_whose_lease_expired_is_reclaimed_and_counted(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        job_id = enqueue(conn, scenario="helene", advisory="N", requested_by="ops_dm_01", **SMALL)
        conn.execute(
            "UPDATE job SET state = 'running', lease_token = gen_random_uuid(),"
            " locked_until = clock_timestamp() - interval '1 minute' WHERE job_id = %s",
            (job_id,),
        )
        result = work_one(conn)
        assert result is not None and result.job_id == job_id
        done = status(conn, job_id)
        assert done is not None and done["state"] == "done" and done["attempts"] == 1


def test_a_running_job_with_a_live_lease_is_left_alone(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        job_id = enqueue(conn, scenario="helene", advisory="N", requested_by="ops_dm_01", **SMALL)
        conn.execute(
            "UPDATE job SET state = 'running', lease_token = gen_random_uuid(),"
            " locked_until = clock_timestamp() + interval '5 minutes' WHERE job_id = %s",
            (job_id,),
        )
        assert work_one(conn) is None
        assert status(conn, job_id) == {
            "job_id": job_id,
            "state": "running",
            "attempts": 0,
            "snapshot_id": None,
        }


def test_an_expired_lease_on_the_last_attempt_makes_the_job_dead(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        job_id = enqueue(conn, scenario="helene", advisory="N", requested_by="ops_dm_01", **SMALL)
        conn.execute(
            "UPDATE job SET state = 'running', attempts = %s, lease_token = gen_random_uuid(),"
            " locked_until = clock_timestamp() - interval '1 minute' WHERE job_id = %s",
            (MAX_ATTEMPTS - 1, job_id),
        )
        assert work_one(conn) is None
        final = status(conn, job_id)
        assert final is not None and final["state"] == "dead" and final["attempts"] == MAX_ATTEMPTS
