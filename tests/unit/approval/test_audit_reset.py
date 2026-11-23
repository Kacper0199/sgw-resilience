"""A database dropped and recreated starts a new audit chain at seq 1, while the anchors of the old chain stay
on the host (`var/audit/anchors/<database>/`). G1 found verify failing at seq 1 after a demo-database reset
("hash differs from the signed checkpoint head"); `sgw reset-db` and `sgw reset` now retire those anchors.
This test runs the real sequence on one scratch database name: chain, checkpoint, drop, recreate,
new chain."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from typer.testing import CliRunner

from sgw.approval import audit
from sgw.approval import audit_testkit as at
from sgw.approval import testkit as tk
from sgw.approval.signer import Ed25519Signer, Keyring
from sgw.cli.commands import stack

T0 = datetime(2024, 9, 26, 9, 0, tzinfo=UTC)
STREAM = audit.STREAM
NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"


def _recreate(admin: str, name: str) -> str:
    from sgw.common.migrate import apply

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{name}"')
    url = tk._with_db(admin, name)
    with psycopg.connect(url, autocommit=True) as conn:
        for ext in tk.EXTENSIONS:
            conn.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
    apply(url)
    return url


def _chain(url: str, signer: Ed25519Signer, anchors: audit.AnchorStore, n: int, start: datetime) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        at.fill(conn, STREAM, n, start)
        assert audit.checkpoint(conn, signer, anchors, at=start + timedelta(minutes=5)) is not None


def _verify(url: str, keyring: Keyring, anchors: audit.AnchorStore) -> audit.VerifyReport:
    with psycopg.connect(url, autocommit=True) as conn:
        return audit.verify(conn, keyring=keyring, anchors=anchors)


def test_verify_is_ok_after_a_database_reset_once_the_old_anchors_are_retired(tmp_path: Path) -> None:
    """A database replaced by a process that cannot retire anchors (the API's read-only mount on a
    Load moment) left the old chain's anchors in place and the after-action page said "Do not use". Anchors
    now record the database instance: the verifier ignores those of a replaced instance and the next
    checkpoint run retires them."""
    admin = tk.admin_dsn()
    if admin is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    signer = Ed25519Signer.generate()
    keyring = Keyring().rotate(signer, T0 - timedelta(days=1))
    anchors = audit.AnchorStore(tmp_path / "anchors")
    with tk.scratch_database("sgw_g1reset_t") as url:
        name = str(psycopg.conninfo.conninfo_to_dict(url)["dbname"])
        _chain(url, signer, anchors, 6, T0)
        assert _verify(url, keyring, anchors).ok
        old_instance = anchors.instance(name)
        assert old_instance is not None
        url = _recreate(admin, name)
        with psycopg.connect(url, autocommit=True) as conn:
            at.fill(conn, STREAM, 3, T0 + timedelta(hours=1))
        before = _verify(url, keyring, anchors)
        assert before.ok, before.problems
        assert before.result().notary == "UNSIGNED"
        with psycopg.connect(url, autocommit=True) as conn:
            assert audit.checkpoint(conn, signer, anchors, at=T0 + timedelta(hours=1, minutes=5)) is not None
        retired = sorted((tmp_path / "anchors" / audit.RETIRED).iterdir())
        assert len(retired) == 1 and retired[0].name.startswith(f"{name}-")
        moved = sorted(p.name for p in (retired[0] / STREAM).glob("*.json"))
        assert moved == [f"{6:012d}.json"]
        assert anchors.instance(name) not in (None, old_instance)
        fresh = _verify(url, keyring, anchors)
        assert fresh.ok, fresh.problems
        assert fresh.result().notary == "signed" and fresh.signed_head_seq == 3
        assert anchors.namespaces() == [name]


def test_anchors_written_before_instances_were_recorded_still_count(tmp_path: Path) -> None:
    admin = tk.admin_dsn()
    if admin is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    signer = Ed25519Signer.generate()
    keyring = Keyring().rotate(signer, T0 - timedelta(days=1))
    anchors = audit.AnchorStore(tmp_path / "anchors")
    with tk.scratch_database("sgw_g1reset_t") as url:
        name = str(psycopg.conninfo.conninfo_to_dict(url)["dbname"])
        _chain(url, signer, anchors, 4, T0)
        (tmp_path / "anchors" / name / audit.INSTANCE_FILE).unlink()
        url = _recreate(admin, name)
        with psycopg.connect(url, autocommit=True) as conn:
            at.fill(conn, STREAM, 2, T0 + timedelta(hours=1))
        report = _verify(url, keyring, anchors)
        assert not report.ok and report.first_bad_seq == 1


def test_retire_never_deletes_and_rejects_path_parts(tmp_path: Path) -> None:
    store = audit.AnchorStore(tmp_path)
    assert store.retire("sgw") is None
    store.write("sgw", {"stream": STREAM, "seq": 1})
    first = store.retire("sgw", at=T0)
    store.write("sgw", {"stream": STREAM, "seq": 1})
    second = store.retire("sgw", at=T0 + timedelta(seconds=1))
    assert first and second and first != second
    assert (first / STREAM / f"{1:012d}.json").is_file() and (second / STREAM / f"{1:012d}.json").is_file()
    assert store.namespaces() == []
    for bad in ("../x", ".retired", "a/b"):
        with pytest.raises(audit.AuditError):
            store.retire(bad)


def test_reset_db_drops_retires_then_migrates_in_that_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []

    class Admin:
        def __enter__(self) -> Admin:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def execute(self, query: Any, *_: Any) -> None:
            calls.append(("sql", query.as_string(None) if hasattr(query, "as_string") else str(query)))

    class Creds:
        def admin_dsn(self) -> str:
            return "postgresql://admin@127.0.0.1:1/postgres"

    monkeypatch.setattr(stack, "load_credentials", lambda: Creds())
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: Admin())
    monkeypatch.setattr(stack, "retire_anchors", lambda db: calls.append(("retire", db)) or [])
    import sgw.cli.commands.database as database

    monkeypatch.setattr(database, "apply_migrations", lambda **kw: calls.append(("migrate", kw)) or [])
    result = CliRunner().invoke(stack.app, ["reset-db", "--yes", "-d", "sgw_demo_x"])
    assert result.exit_code == 0, result.output
    assert [c[0] for c in calls] == ["sql", "retire", "migrate"]
    assert 'DROP DATABASE IF EXISTS "sgw_demo_x" WITH (FORCE)' in calls[0][1]
    assert calls[1] == ("retire", "sgw_demo_x") and calls[2][1] == {"database": "sgw_demo_x", "create": True}
