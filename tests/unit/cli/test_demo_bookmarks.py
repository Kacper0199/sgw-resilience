from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from typer.testing import CliRunner

from sgw.approval import audit
from sgw.approval import audit_testkit as at
from sgw.approval.signer import Ed25519Signer, Keyring
from sgw.cli.main import build_app
from sgw.demo import snapshots
from sgw.demo.bookmarks import BOOKMARKS, TEMPLATE_PREFIX, Bookmark, bookmark
from sgw.ingest.testing import ScratchDb, scratch_database, server_available

GOTO_BUDGET_S = 10.0
T0 = datetime(2024, 9, 26, 9, 0, tzinfo=UTC)


def test_bookmarks_follow_the_ps17_story_in_order() -> None:
    assert [b.id for b in BOOKMARKS] == [
        "before-n",
        "at-n",
        "at-n1",
        "signed",
        "morning-after",
        "etr-published",
        "notices-lifted",
        "after-action",
    ]
    assert [b.id for b in BOOKMARKS if not b.has_key_run] == ["morning-after", "notices-lifted"]
    assert [b.scenario_time for b in BOOKMARKS] == sorted(b.scenario_time for b in BOOKMARKS)
    assert all(b.run_at >= b.scenario_time for b in BOOKMARKS)
    assert all(b.template.startswith(TEMPLATE_PREFIX) and "-" not in b.template for b in BOOKMARKS)
    with pytest.raises(KeyError, match="unknown bookmark"):
        bookmark("landfall")


@pytest.mark.parametrize(
    "target",
    [
        "postgres",
        "template0",
        "template1",
        "sgw_demo_build",
        "sgw_demo_bm_at_n1",
        "sgw_golden",
        "sgw_template",
        "mlflow",
        "sgw_wp33a_" + "x" * 60,
    ],
)
def test_goto_refuses_dangerous_or_unlisted_targets(target: str) -> None:
    with pytest.raises(snapshots.TargetRefused):
        snapshots.check_target(target)
    result = CliRunner().invoke(build_app(), ["demo", "goto", "at-n", "--yes", "-d", target])
    assert result.exit_code != 0 and "refusing" in result.output


@pytest.mark.parametrize("target", ["sgw", "sgw_wp33a", "sgw_wp07_t_bm_dst_1a2b3c4d"])
def test_goto_allows_the_demo_and_scratch_databases(target: str) -> None:
    snapshots.check_target(target)


def test_goto_refuses_an_unknown_bookmark_before_touching_a_database() -> None:
    result = CliRunner().invoke(build_app(), ["demo", "goto", "nope", "--yes", "-d", "sgw_wp33a"])
    assert result.exit_code != 0 and "unknown bookmark" in result.output


def test_build_refuses_the_demo_database() -> None:
    from sgw.demo.runner import build

    with pytest.raises(ValueError, match="separate database"):
        build("sgw", lambda _u: "x" * 12, lambda _dsn: None)


@pytest.fixture
def admin_url() -> str:
    reason = server_available()
    if reason:
        pytest.skip(reason)  # sgw-allow-skip: needs Postgres (SGW_TEST_DATABASE_URL or the stack)
    from sgw.ingest.testing import _admin_url

    return _admin_url()


@pytest.fixture
def bm(admin_url: str) -> Bookmark:
    return Bookmark(f"t{uuid.uuid4().hex[:8]}", "test", "2024-09-26T08:00:00Z", "", "copilot", "ask", "")


@contextmanager
def _pair(admin_url: str, bm: Bookmark) -> Iterator[tuple[ScratchDb, ScratchDb]]:
    """Two scratch databases; the bookmark template goes first, since its copied ACL names their roles."""
    with scratch_database("bm_src") as src, scratch_database("bm_dst") as dst:
        try:
            yield src, dst
        finally:
            with psycopg.connect(admin_url, autocommit=True) as conn:
                snapshots._drop(conn, bm.template)
                snapshots._drop(conn, dst.name + snapshots.STAGING_SUFFIX)


def _db(admin_url: str, name: str) -> tuple[str, list[str], bool, bool, str | None]:
    with psycopg.connect(admin_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT pg_get_userbyid(datdba), datacl::text[], datistemplate, datallowconn,"
            " shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s",
            (name,),
        ).fetchone()
    assert row is not None, name
    return str(row[0]), list(row[1] or []), bool(row[2]), bool(row[3]), row[4]


def test_snapshot_and_goto_swap_rows_keep_the_targets_owner_and_acl_and_mark_it(
    admin_url: str, bm: Bookmark, tmp_path: Path
) -> None:
    retired: list[str] = []

    def retire(database: str) -> list[Path]:
        retired.append(database)
        return [tmp_path / database]

    base = admin_url.rpartition("/")[0]
    with _pair(admin_url, bm) as (src, dst):
        with psycopg.connect(src.admin_url, autocommit=True) as conn:
            conn.execute("CREATE TABLE demo_probe (n int)")
            conn.execute("INSERT INTO demo_probe VALUES (17)")
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(src.name)))
            conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO sgw_readonly").format(sql.Identifier(dst.name))
            )
        dst_owner, dst_acl, *_ = _db(admin_url, dst.name)
        assert snapshots.snapshot(admin_url, src.name, bm) < GOTO_BUDGET_S
        _, _, is_template, allow_conn, _ = _db(admin_url, bm.template)
        assert is_template and not allow_conn
        assert snapshots.snapshot(admin_url, src.name, bm) < GOTO_BUDGET_S
        started = time.perf_counter()
        report = snapshots.goto(admin_url, bm, dst.name, retire=retire)
        assert time.perf_counter() - started < GOTO_BUDGET_S and report.seconds < GOTO_BUDGET_S
        assert retired == [dst.name] and report.retired == [tmp_path / dst.name]
        with psycopg.connect(f"{base}/{dst.name}") as conn:
            assert conn.execute("SELECT n FROM demo_probe").fetchone() == (17,)
        owner, acl, is_template, allow_conn, comment = _db(admin_url, dst.name)
        assert (owner, sorted(acl)) == (dst_owner, sorted(dst_acl)) and not is_template and allow_conn
        assert snapshots.marked_bookmark(comment) == bm.id
        assert not snapshots.exists(admin_url, dst.name + snapshots.STAGING_SUFFIX)


def test_a_failed_copy_leaves_the_target_untouched(admin_url: str, bm: Bookmark) -> None:
    base = admin_url.rpartition("/")[0]
    with _pair(admin_url, bm) as (src, dst):
        with psycopg.connect(dst.admin_url, autocommit=True) as conn:
            conn.execute("CREATE TABLE kept (n int)")
            conn.execute("INSERT INTO kept VALUES (3)")
        snapshots.snapshot(admin_url, src.name, bm)
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("ALTER DATABASE {} WITH ALLOW_CONNECTIONS true").format(sql.Identifier(bm.template))
            )
        with psycopg.connect(f"{base}/{bm.template}"), pytest.raises(psycopg.errors.ObjectInUse):
            snapshots.goto(admin_url, bm, dst.name)
        with psycopg.connect(f"{base}/{dst.name}") as conn:
            assert conn.execute("SELECT n FROM kept").fetchone() == (3,)
        assert not snapshots.exists(admin_url, dst.name + snapshots.STAGING_SUFFIX)


def test_audit_verify_is_ok_after_goto_once_the_targets_old_anchors_are_retired(
    admin_url: str, bm: Bookmark, tmp_path: Path
) -> None:
    signer = Ed25519Signer.generate()
    keyring = Keyring().rotate(signer, T0 - timedelta(days=1))
    anchors = audit.AnchorStore(tmp_path / "anchors")
    base = admin_url.rpartition("/")[0]
    with _pair(admin_url, bm) as (src, dst):
        with psycopg.connect(dst.admin_url, autocommit=True) as conn:
            at.fill(conn, audit.STREAM, 4, T0)
            assert audit.checkpoint(conn, signer, anchors, at=T0 + timedelta(minutes=5)) is not None
        with psycopg.connect(src.admin_url, autocommit=True) as conn:
            at.fill(conn, audit.STREAM, 6, T0 + timedelta(hours=1))
        snapshots.snapshot(admin_url, src.name, bm)

        def retire(database: str) -> list[Path]:
            moved = anchors.retire(database, at=T0)
            return [moved] if moved else []

        report = snapshots.goto(admin_url, bm, dst.name, retire=retire)
        assert report.retired and report.retired[0].parent.name == audit.RETIRED
        with psycopg.connect(f"{base}/{dst.name}", autocommit=True) as conn:
            fresh = audit.verify(conn, keyring=keyring, anchors=anchors)
            assert fresh.ok and fresh.checked_to_seq == 6, fresh.problems
            assert audit.checkpoint(conn, signer, anchors, at=T0 + timedelta(hours=2)) is not None
            signed = audit.verify(conn, keyring=keyring, anchors=anchors)
        assert signed.ok and signed.result().notary == "signed" and signed.signed_head_seq == 6


def test_goto_names_the_build_command_when_a_bookmark_is_missing(admin_url: str) -> None:
    missing = Bookmark(f"missing{uuid.uuid4().hex[:6]}", "x", "", "", "", "", "")
    with pytest.raises(LookupError, match="sgw demo build"):
        snapshots.goto(admin_url, missing, "sgw_wp33a_never_created")
