"""Runs `sgw migrate` against the shared stack on 127.0.0.1:5434 (skipped when it is not up)."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from sgw.cli.support import CliError, load_credentials


def stack_up() -> bool:
    try:
        load_credentials()
        with socket.create_connection(("127.0.0.1", 5434), timeout=1):
            return True
    except (OSError, CliError, KeyError):
        return False


pytestmark = pytest.mark.skipif(not stack_up(), reason="sgw stack not running on 127.0.0.1:5434")


@pytest.fixture
def scratch_db():
    import psycopg

    name = f"sgw_migtest_{os.getpid()}"
    yield name
    with psycopg.connect(load_credentials().admin_dsn(), autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


def test_migrate_applies_once_records_ledger_and_refuses_edits(tmp_path: Path, scratch_db: str) -> None:
    import psycopg

    from sgw.cli.commands.database import apply_migrations

    (tmp_path / "0001_core_table.sql").write_text(
        "CREATE TABLE reading (observed_at timestamptz NOT NULL, v double precision);\n"
        "SELECT create_hypertable('reading', by_range('observed_at'));\n"
        "CREATE TABLE station (id int PRIMARY KEY, name text);\n"
    )
    (tmp_path / "0002_core_index.sql").write_text(
        "-- sgw:no-transaction\nCREATE INDEX CONCURRENTLY station_name ON station (name);\n"
    )
    assert apply_migrations(scratch_db, tmp_path, create=True) == [
        "0001_core_table.sql",
        "0002_core_index.sql",
    ]
    assert apply_migrations(scratch_db, tmp_path) == []

    with psycopg.connect(load_credentials().owner_dsn(scratch_db)) as conn:
        ledger = conn.execute(
            "SELECT filename, applied_by FROM schema_migrations ORDER BY filename"
        ).fetchall()
        owner = conn.execute("SELECT tableowner FROM pg_tables WHERE tablename = 'reading'").fetchone()
        extensions = {r[0] for r in conn.execute("SELECT extname FROM pg_extension").fetchall()}
    assert ledger == [("0001_core_table.sql", "sgw"), ("0002_core_index.sql", "sgw")]
    assert owner == ("sgw",)
    assert {"timescaledb", "postgis", "vector", "vectorscale", "h3", "pgrouting"} <= extensions

    (tmp_path / "0001_core_table.sql").write_text("SELECT 'edited';\n")
    with pytest.raises(CliError, match="changed after it was applied"):
        apply_migrations(scratch_db, tmp_path)


def test_failed_migration_rolls_back_and_is_not_recorded(tmp_path: Path, scratch_db: str) -> None:
    import psycopg

    from sgw.cli.commands.database import apply_migrations

    (tmp_path / "0001_core_ok.sql").write_text("CREATE TABLE ok_table (id int);\n")
    (tmp_path / "0002_core_broken.sql").write_text(
        "CREATE TABLE half (id int);\nSELECT no_such_function();\n"
    )
    with pytest.raises(psycopg.Error):
        apply_migrations(scratch_db, tmp_path, create=True)
    with psycopg.connect(load_credentials().owner_dsn(scratch_db)) as conn:
        ledger = [r[0] for r in conn.execute("SELECT filename FROM schema_migrations").fetchall()]
        half = conn.execute("SELECT to_regclass('public.half')").fetchone()
    assert ledger == ["0001_core_ok.sql"]
    assert half == (None,)


def test_dry_run_creates_neither_database_objects_nor_ledger(tmp_path: Path, scratch_db: str) -> None:
    import psycopg

    from sgw.cli.commands.database import apply_migrations, ensure_database

    ensure_database(scratch_db)
    (tmp_path / "0001_core_ok.sql").write_text("CREATE TABLE ok_table (id int);\n")
    assert apply_migrations(scratch_db, tmp_path, dry_run=True) == []
    with psycopg.connect(load_credentials().owner_dsn(scratch_db)) as conn:
        found = conn.execute(
            "SELECT to_regclass('public.schema_migrations'), to_regclass('public.ok_table')"
        ).fetchone()
    assert found == (None, None)


def test_roles_runtime_login_is_a_least_privilege_member_of_sgw_app(tmp_path: Path, scratch_db: str) -> None:
    import psycopg

    from sgw.cli.commands.database import apply_migrations

    (tmp_path / "0001_core_table.sql").write_text(
        "CREATE TABLE note (id int PRIMARY KEY, body text);\n"
        "GRANT SELECT, INSERT ON note TO sgw_app;\n"
        "GRANT SELECT ON note TO sgw_readonly;\n"
    )
    apply_migrations(scratch_db, tmp_path, create=True)
    creds = load_credentials()
    with psycopg.connect(creds.admin_dsn()) as admin:
        roles = dict(
            admin.execute(
                "SELECT rolname, rolcanlogin FROM pg_roles"
                " WHERE rolname IN ('sgw_app', 'sgw_readonly', 'sgw_runtime')"
            ).fetchall()
        )
        member = admin.execute("SELECT pg_has_role('sgw_runtime', 'sgw_app', 'MEMBER')").fetchone()
    assert roles == {"sgw_app": False, "sgw_readonly": False, "sgw_runtime": True}
    assert member == (True,)
    with psycopg.connect(creds.runtime_dsn(scratch_db), autocommit=True) as runtime:
        runtime.execute("INSERT INTO note VALUES (1, 'ok')")
        assert runtime.execute("SELECT count(*) FROM note").fetchone() == (1,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute("DELETE FROM note")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute("CREATE TABLE intruder (id int)")


def test_gateway_login_can_only_insert_into_tables_granted_to_the_writer(
    tmp_path: Path, scratch_db: str
) -> None:
    import psycopg

    from sgw.cli.commands.database import apply_migrations, ensure_roles

    (tmp_path / "0001_core_calls.sql").write_text(
        "CREATE TABLE fake_llm_call (id int PRIMARY KEY, usd numeric);\n"
        "CREATE TABLE other_table (id int);\n"
        "GRANT USAGE ON SCHEMA public TO sgw_llm_writer;\n"
        "GRANT INSERT ON fake_llm_call TO sgw_llm_writer;\n"
    )
    apply_migrations(scratch_db, tmp_path, create=True)
    ensure_roles(scratch_db)
    creds = load_credentials()
    with psycopg.connect(creds.admin_dsn()) as admin:
        role = admin.execute(
            "SELECT rolcanlogin, rolconnlimit, pg_has_role('sgw_gateway', 'sgw_llm_writer', 'MEMBER'),"
            " pg_has_role('sgw_gateway', 'sgw_app', 'MEMBER') FROM pg_roles WHERE rolname = 'sgw_gateway'"
        ).fetchone()
    assert role == (True, 5, True, False)
    with psycopg.connect(creds.gateway_dsn(scratch_db), autocommit=True) as gateway:
        gateway.execute("INSERT INTO fake_llm_call VALUES (1, 0.01)")
        for statement in (
            "SELECT * FROM fake_llm_call",
            "UPDATE fake_llm_call SET usd = 0",
            "DELETE FROM fake_llm_call",
            "SELECT * FROM other_table",
            "CREATE TABLE intruder (id int)",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                gateway.execute(statement)
