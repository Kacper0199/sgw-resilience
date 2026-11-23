"""K1 tests against a migrated empty database (PG 18.6 timescaledb-ha). Needs SGW_TEST_DATABASE_URL."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from sgw.common.migrate import MigrationError, apply, discover
from sgw.contracts.db_snapshot import SNAPSHOT_PATH, snapshot
from sgw.contracts.vocab import ALL_VOCABS

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_ENV = "SGW_TEST_DATABASE_URL"


def _with_db(url: str, dbname: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/{dbname}"


NO_DB_REASON = f"{DB_ENV} not set: database contract tests not run"
EXTENSIONS = ("timescaledb", "postgis", "vector", "btree_gist", "pgcrypto")


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[str]:
    """A fresh database migrated the way WP-03 does it: a superuser creates the extensions and app roles, then
    a non-superuser database owner (no CREATEROLE) applies every migration. Yields a superuser URL.
    Needs SGW_TEST_DATABASE_URL (a server admin URL)."""
    admin = os.environ.get(DB_ENV)
    if not admin:
        pytest.skip(NO_DB_REASON)  # sgw-allow-skip: database tests need SGW_TEST_DATABASE_URL
    from sgw.common.migrate import apply

    suffix = uuid.uuid4().hex[:10]
    name, owner = f"sgw_contracts_{suffix}", f"sgw_owner_{suffix}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"CREATE ROLE {owner} LOGIN PASSWORD 'scratch' NOSUPERUSER NOCREATEROLE")
        conn.execute(f'CREATE DATABASE "{name}" OWNER {owner}')
        for role in ("sgw_app", "sgw_readonly"):
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
                conn.execute(f"CREATE ROLE {role} NOLOGIN")
    url = _with_db(admin, name)
    with psycopg.connect(url, autocommit=True) as conn:
        for ext in EXTENSIONS:
            conn.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
    scheme, _, rest = url.partition("://")
    owner_url = f"{scheme}://{owner}:scratch@{rest.split('@', 1)[1]}"
    try:
        apply(owner_url)
        yield url
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            conn.execute(f"DROP ROLE IF EXISTS {owner}")


FACT_TABLES = (
    "event",
    "observation",
    "forecast",
    "risk",
    "anomaly",
    "decision_case",
    "proposal",
    "asset",
    "crew",
)
ZERO = "0" * 64


MIGRATION_RANGES = (
    (1, 99),
    (1000, 1999),
    (2000, 2999),
    (3000, 3499),
    (3500, 3999),
    (4000, 4499),
    (4500, 4999),
    (5000, 5099),
)


def test_migration_files_are_in_an_owned_range() -> None:
    for mig in discover():
        assert any(lo <= mig.number <= hi for lo, hi in MIGRATION_RANGES), mig.name


def test_schema_snapshot_matches(migrated_db: str) -> None:
    assert snapshot(migrated_db) == SNAPSHOT_PATH.read_text(encoding="utf-8")


def test_migrate_is_idempotent_and_detects_edits(migrated_db: str, tmp_path: Path) -> None:
    assert apply(migrated_db) == []
    edited = tmp_path / "migrations"
    edited.mkdir()
    for mig in discover():
        (edited / mig.name).write_text(mig.path.read_text())
    first = sorted(edited.glob("*.sql"))[0]
    first.write_text(first.read_text() + "\n-- edited\n")
    with pytest.raises(MigrationError, match="changed"):
        apply(migrated_db, edited)


def test_domains_equal_vocab_enums(migrated_db: str) -> None:
    with psycopg.connect(migrated_db) as conn:
        rows = dict(
            conn.execute(
                "SELECT t.typname, pg_get_constraintdef(c.oid) FROM pg_type t "
                "JOIN pg_constraint c ON c.contypid = t.oid "
                "WHERE t.typname LIKE 'sgw_%'"
            ).fetchall()
        )
    for name, enum in ALL_VOCABS.items():
        values = re.findall(r"'([^']*)'::text", rows[f"sgw_{name}"])
        assert values == [e.value for e in enum], name


def test_region_domain_columns(migrated_db: str) -> None:
    with psycopg.connect(migrated_db) as conn:
        cols = conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public'"
        ).fetchall()
    present = {(t, c) for t, c in cols}
    for table in FACT_TABLES:
        assert (table, "region_id") in present, table
        assert (table, "domain") in present, table


def test_only_observation_is_a_hypertable(migrated_db: str) -> None:
    with psycopg.connect(migrated_db) as conn:
        rows = conn.execute(
            "SELECT hypertable_name, column_name FROM timescaledb_information.dimensions"
        ).fetchall()
    assert rows == [("observation", "observed_at")]


def _audit_row(conn: psycopg.Connection, seq: int) -> None:
    conn.execute(
        "INSERT INTO audit_event (seq, event_key, occurred_at, actor_type, actor_id, kind, subject,"
        " payload_hash,"
        " payload, prev_hash, hash) VALUES (%s, %s, now(), 'system', 'test', 'k', 's', %s, '{}', %s, %s)",
        (seq, f"k{seq}", ZERO, ZERO, ZERO),
    )


def test_audit_event_is_insert_only(migrated_db: str) -> None:
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        _audit_row(conn, 1)
        for stmt in ("UPDATE audit_event SET kind = 'x'", "DELETE FROM audit_event", "TRUNCATE audit_event"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(stmt)
        conn.execute("SET ROLE sgw_app")
        _audit_row(conn, 2)
        conn.execute("SELECT count(*) FROM audit_event")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE audit_event SET kind = 'x' WHERE seq = 2")
        conn.execute("RESET ROLE")
        assert conn.execute("SELECT count(*) FROM audit_event").fetchone() == (2,)


def _case(
    conn: psycopg.Connection,
    case_id: str,
    *,
    effective: str = "2024-09-27T04:10Z",
    decide_by: str = "2024-09-27T04:10Z",
) -> None:
    basis = json.dumps({"kind": "model_estimate", "basis_id": "m", "basis_version": "1"})
    conn.execute(
        "INSERT INTO decision_case (decision_case_id, step, title, region_id, domain, clock_kind,"
        " consequence_utc,"
        " consequence_p10_utc, consequence_p90_utc, consequence_basis, action_lead_time_min, lead_time_basis,"
        " decide_by_utc, decide_by_p10_utc, decide_by_p90_utc, effective_decide_by_utc, if_late)"
        " VALUES (%s, 'D3', 't', 'SC-45003', 'water', 'model_estimate', '2024-09-27T06:40Z',"
        " '2024-09-27T05:55Z',"
        " '2024-09-27T07:30Z', %s, 150, %s, %s, '2024-09-27T03:25Z', '2024-09-27T05:00Z', %s, 'late')",
        (case_id, basis, basis, decide_by, effective),
    )


def test_clock_checks_in_the_database(migrated_db: str) -> None:
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        _case(conn, "DC-DB-OK")
        with pytest.raises(psycopg.errors.CheckViolation):
            _case(conn, "DC-DB-LATE", effective="2024-09-27T04:11Z")
        with pytest.raises(psycopg.errors.CheckViolation):
            _case(conn, "DC-DB-WATERFALL", decide_by="2024-09-27T04:20Z", effective="2024-09-27T04:00Z")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("INSERT INTO decision_dependency VALUES ('DC-DB-OK', 'DC-DB-OK', 'self')")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "UPDATE decision_case SET no_regret_verdict = 'maybe' WHERE decision_case_id = 'DC-DB-OK'"
            )


def test_observation_rejects_nan_and_vocab_rejects_unknown(migrated_db: str) -> None:
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO observation (source_id, tag, observed_at, known_at, value, unit, value_hash)"
                " VALUES ('s', 't', now(), now(), 'NaN', 'psi', 'h')"
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO llm_call (call_id, ts, mode, billed, purpose, node, model, effort, request_hash)"
                " VALUES ('c', now(), 'replay', false, 'dev', 'n', 'sonnet', 'turbo', %s)",
                (ZERO,),
            )


H1 = "1" * 64
H2 = "2" * 64
SEED_USERS = (
    ("ic_01", "command", True, True),
    ("ops_dm_01", "operations", True, False),
    ("wtr_lead_01", "water_operations", True, False),
    ("log_01", "logistics", True, False),
    ("exec_01", "executive", False, False),
    ("dual_01", "command", True, False),
)


@pytest.fixture(scope="module")
def authority_db(migrated_db: str) -> str:
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        for uid, fn, can, bg in SEED_USERS:
            fns = "{command,water_operations}" if uid == "dual_01" else "{" + fn + "}"
            conn.execute(
                "INSERT INTO app_user (user_id, display_name, persona, function, functions, can_approve,"
                " break_glass_eligible) VALUES (%s, %s, 'P', %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (uid, uid, fn, fns, can, bg),
            )
        _case(conn, "DC-AUTH")
        conn.execute(
            "INSERT INTO proposal (proposal_id, decision_case_id, incident_id, action_type, params, targets,"
            " risk_band, tier, required_functions, proposal_version, action_hash, policy_version,"
            " initiator_kind, proposed_by, region_id, domain) VALUES ('PRP-AUTH', 'DC-AUTH', 'INC-1',"
            " 'cross_domain_priority', '{}', '{PS-17}', 'very_high', 'T3', '{command,water_operations}',"
            " 2, %s,"
            " 'p1', 'person', 'ops_dm_01', 'SC-45003', 'water')",
            (H1,),
        )
    return migrated_db


def _approve(conn: psycopg.Connection, aid: str, user: str, fn: str, version: int = 2, h: str = H1) -> None:
    conn.execute(
        "INSERT INTO approval (approval_id, proposal_id, proposal_version, action_hash, approver_id,"
        " function,"
        " decision) VALUES (%s, 'PRP-AUTH', %s, %s, %s, %s, 'approve')",
        (aid, version, h, user, fn),
    )


@pytest.mark.parametrize(
    ("user", "fn", "version", "h", "error"),
    [
        ("ops_dm_01", "operations", 2, H1, psycopg.errors.InsufficientPrivilege),
        ("log_01", "water_operations", 2, H1, psycopg.errors.InsufficientPrivilege),
        ("log_01", "logistics", 2, H1, psycopg.errors.InsufficientPrivilege),
        ("exec_01", "executive", 2, H1, psycopg.errors.InsufficientPrivilege),
        ("ic_01", "command", 1, H1, psycopg.errors.TriggeredActionException),
        ("ic_01", "command", 2, H2, psycopg.errors.TriggeredActionException),
    ],
    ids=[
        "self-approval",
        "function-not-held",
        "function-not-required",
        "cannot-approve",
        "stale-version",
        "wrong-hash",
    ],
)
def test_approval_authority_is_enforced(
    authority_db: str, user: str, fn: str, version: int, h: str, error: type[Exception]
) -> None:
    with psycopg.connect(authority_db, autocommit=True) as conn, pytest.raises(error):
        _approve(conn, f"APR-NEG-{user}-{fn}-{version}-{h[0]}", user, fn, version, h)


def test_one_person_cannot_sign_both_functions_and_valid_pair_passes(authority_db: str) -> None:
    with psycopg.connect(authority_db, autocommit=True) as conn:
        _approve(conn, "APR-DUAL-1", "dual_01", "command")
        with pytest.raises(psycopg.errors.UniqueViolation):
            _approve(conn, "APR-DUAL-2", "dual_01", "water_operations")
        conn.execute("DELETE FROM approval WHERE approval_id = 'APR-DUAL-1'")
        _approve(conn, "APR-OK-IC", "ic_01", "command")
        _approve(conn, "APR-OK-WL", "wtr_lead_01", "water_operations")
        n = conn.execute("SELECT count(*) FROM approval WHERE proposal_id = 'PRP-AUTH'").fetchone()
        assert n == (2,)


def _break_glass(conn: psycopg.Connection, ic: str, version: int = 2, h: str = H1) -> int:
    row = conn.execute(
        "INSERT INTO break_glass (proposal_id, ic_id, proposal_version, action_hash, reason, used_at,"
        " cosign_due)"
        " VALUES ('PRP-AUTH', %s, %s, %s, 'pressure falling, water lead unreachable', '2024-09-27T03:00Z',"
        " '2024-09-28T03:00Z') RETURNING break_glass_id",
        (ic, version, h),
    ).fetchone()
    assert row is not None
    return int(row[0])


def test_break_glass_authority_is_enforced(authority_db: str) -> None:
    with psycopg.connect(authority_db, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _break_glass(conn, "dual_01")
        with pytest.raises(psycopg.errors.TriggeredActionException):
            _break_glass(conn, "ic_01", version=1)
        with pytest.raises(psycopg.errors.TriggeredActionException):
            _break_glass(conn, "ic_01", h=H2)
        bg = _break_glass(conn, "ic_01")
        upd = (
            "UPDATE break_glass SET cosigned_by = %s, cosigned_at = '2024-09-27T09:00Z'"
            " WHERE break_glass_id = %s"
        )
        for wrong in ("log_01", "exec_01"):
            with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.CheckViolation)):
                conn.execute(upd, (wrong, bg))
        with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.CheckViolation)):
            conn.execute(upd, ("ic_01", bg))
        conn.execute(upd, ("wtr_lead_01", bg))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "UPDATE break_glass SET reason = 'rewritten after the fact' WHERE break_glass_id = %s", (bg,)
            )


def test_t3_proposal_needs_two_distinct_required_functions(authority_db: str) -> None:
    with psycopg.connect(authority_db, autocommit=True) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO proposal (proposal_id, decision_case_id, incident_id, action_type, params, targets,"
            " risk_band, tier, required_functions, action_hash, policy_version, initiator_kind, proposed_by,"
            " region_id, domain) VALUES ('PRP-BAD', 'DC-AUTH', 'INC-1', 'cross_domain_priority', '{}', '{}',"
            " 'high', 'T3', '{command,command}', %s, 'p1', 'person', 'ops_dm_01', 'SC-45003', 'water')",
            (H1,),
        )


def test_verdict_needs_share_and_next_advisory_in_sql(authority_db: str) -> None:
    with psycopg.connect(authority_db, autocommit=True) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "UPDATE decision_case SET no_regret_verdict = 'act_now' WHERE decision_case_id = 'DC-AUTH'"
        )


def test_audit_checkpoint_rejects_truncate(migrated_db: str) -> None:
    with (
        psycopg.connect(migrated_db, autocommit=True) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("TRUNCATE audit_checkpoint")
