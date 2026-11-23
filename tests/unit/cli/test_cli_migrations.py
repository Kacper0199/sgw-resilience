from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sgw.cli.commands.database import Migration, count_statements, discover_migrations, plan_migrations
from sgw.cli.support import CliError


def write(directory: Path, name: str, body: str = "SELECT 1;") -> Path:
    path = directory / name
    path.write_text(body)
    return path


def migration(directory: Path, name: str, body: str = "SELECT 1;") -> Migration:
    path = write(directory, name, body)
    return Migration(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_discovery_orders_by_number_and_ignores_other_files(tmp_path: Path) -> None:
    write(tmp_path, "1000_b1_events.sql")
    write(tmp_path, "0002_core_ledger.sql")
    write(tmp_path, "0001_core_schema.sql")
    write(tmp_path, "README.md", "notes")
    assert [m.name for m in discover_migrations(tmp_path)] == [
        "0001_core_schema.sql",
        "0002_core_ledger.sql",
        "1000_b1_events.sql",
    ]


def test_missing_directory_means_no_migrations(tmp_path: Path) -> None:
    assert discover_migrations(tmp_path / "absent") == []


@pytest.mark.parametrize("bad", ["1_core.sql", "0001-core.sql", "0001_Core.sql", "abcd_core.sql"])
def test_bad_names_are_rejected(tmp_path: Path, bad: str) -> None:
    write(tmp_path, bad)
    with pytest.raises(CliError, match="bad migration file name"):
        discover_migrations(tmp_path)


def test_duplicate_numbers_are_rejected(tmp_path: Path) -> None:
    write(tmp_path, "0003_core_a.sql")
    write(tmp_path, "0003_core_b.sql")
    with pytest.raises(CliError, match="duplicate migration numbers: 0003"):
        discover_migrations(tmp_path)


def test_plan_returns_only_pending_in_order(tmp_path: Path) -> None:
    first = migration(tmp_path, "0001_core_a.sql")
    second = migration(tmp_path, "0002_core_b.sql", "SELECT 2;")
    third = migration(tmp_path, "0003_core_c.sql", "SELECT 3;")
    pending = plan_migrations([first, second, third], {first.name: first.sha256})
    assert [m.name for m in pending] == ["0002_core_b.sql", "0003_core_c.sql"]


def test_edited_applied_migration_is_refused(tmp_path: Path) -> None:
    first = migration(tmp_path, "0001_core_a.sql", "SELECT 'edited';")
    with pytest.raises(CliError, match="changed after it was applied"):
        plan_migrations([first], {first.name: "0" * 64})


def test_migration_older_than_an_applied_one_in_its_range_is_refused(tmp_path: Path) -> None:
    early = migration(tmp_path, "0001_core_a.sql")
    late = migration(tmp_path, "0005_core_e.sql", "SELECT 5;")
    with pytest.raises(CliError, match="older than an applied one in the same owned range"):
        plan_migrations([early, late], {late.name: late.sha256})


def test_lower_range_migration_applies_after_a_higher_range_one(tmp_path: Path) -> None:
    clocks = migration(tmp_path, "2300_clocks.sql", "SELECT 23;")
    approvals = migration(tmp_path, "4501_approvals.sql", "SELECT 45;")
    pending = plan_migrations([clocks, approvals], {approvals.name: approvals.sha256})
    assert [m.name for m in pending] == ["2300_clocks.sql"]


def test_no_transaction_marker(tmp_path: Path) -> None:
    plain = migration(tmp_path, "0001_core_a.sql")
    concurrent = migration(
        tmp_path, "0002_core_b.sql", "-- sgw:no-transaction\nCREATE INDEX CONCURRENTLY i ON t (c);"
    )
    assert plain.transactional
    assert not concurrent.transactional


def test_checksum_ignores_crlf_line_endings(tmp_path: Path) -> None:
    lf = tmp_path / "lf"
    lf.mkdir()
    crlf = tmp_path / "crlf"
    crlf.mkdir()
    write(lf, "0001_core_a.sql", "CREATE TABLE a (id int);\nSELECT 1;\n")
    (crlf / "0001_core_a.sql").write_bytes(b"CREATE TABLE a (id int);\r\nSELECT 1;\r\n")
    assert discover_migrations(lf)[0].sha256 == discover_migrations(crlf)[0].sha256


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT 1", 1),
        ("SELECT 1;", 1),
        ("SELECT 1; SELECT 2;", 2),
        ("-- a; comment\nSELECT ';' ;", 1),
        ("/* x; y */ SELECT 'it''s; fine'", 1),
        ('CREATE TABLE "a;b" (id int);', 1),
        ("CREATE FUNCTION f() RETURNS int AS $body$ SELECT 1; SELECT 2; $body$ LANGUAGE sql;", 1),
        ("DO $$ BEGIN PERFORM 1; END $$; SELECT 1;", 2),
        ("-- only a comment\n", 0),
    ],
)
def test_count_statements(sql: str, expected: int) -> None:
    assert count_statements(sql) == expected


def test_no_transaction_migration_must_hold_one_statement(tmp_path: Path) -> None:
    write(
        tmp_path,
        "0001_core_idx.sql",
        "-- sgw:no-transaction\n"
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS a ON t (c);\n"
        "CREATE INDEX CONCURRENTLY b ON t (d);\n",
    )
    with pytest.raises(CliError, match="exactly one statement"):
        discover_migrations(tmp_path)


def test_no_transaction_migration_with_one_statement_is_accepted(tmp_path: Path) -> None:
    write(
        tmp_path,
        "0001_core_idx.sql",
        "-- sgw:no-transaction\nCREATE INDEX CONCURRENTLY IF NOT EXISTS a ON t (c);\n",
    )
    assert not discover_migrations(tmp_path)[0].transactional
