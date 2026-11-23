"""Bookmark snapshots as Postgres template databases on the stack's server.

`snapshot` copies a quiet build database to `sgw_demo_bm_<id>` and marks it IS_TEMPLATE with connections
refused. `goto` copies the template to `<target>_new` first, then drops the target WITH (FORCE) and renames
the copy into place, so a failed copy leaves the target untouched. The target keeps its own owner and ACL,
is marked with the bookmark id (a database comment K19 playback matches on) and has its audit anchors
retired so the stack's audit-checkpoint signs the restored chain afresh. A running API notices the new
database epoch and reloads its clock and ledger stream (G1-BE 582c2f4, 015daa2); its pools check each
connection before lending it (4c1e789).

Targets are an explicit allowlist: the demo database and developer scratch databases (`sgw_wp<nn>...`);
never `postgres`, the cluster templates, a bookmark template or the build database."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from sgw.demo.bookmarks import TEMPLATE_PREFIX, Bookmark

MARK_PREFIX = "sgw-demo-bookmark:"
BUILD_DATABASE = "sgw_demo_build"
ALLOWED_TARGETS = frozenset({"sgw"})
SCRATCH_TARGET = re.compile(r"^sgw_wp[0-9]+[a-z]*(_[a-z0-9]+)*$")
REFUSED_TARGETS = frozenset({"postgres", "template0", "template1", BUILD_DATABASE})
STAGING_SUFFIX = "_new"
MAX_NAME = 63
ACL_PRIVILEGES = {"C": "CREATE", "T": "TEMPORARY", "c": "CONNECT"}


class TargetRefused(ValueError):
    pass


@dataclass(frozen=True)
class GotoReport:
    bookmark: str
    database: str
    template: str
    seconds: float
    retired: list[Path]


def check_target(database: str) -> None:
    if database in REFUSED_TARGETS or database.startswith((TEMPLATE_PREFIX, "sgw_demo_")):
        raise TargetRefused(f"refusing to replace {database!r}: a system, template or build database")
    if database not in ALLOWED_TARGETS and not SCRATCH_TARGET.match(database):
        raise TargetRefused(
            f"refusing to replace {database!r}: allowed are {sorted(ALLOWED_TARGETS)} and builder scratch"
            " databases sgw_wp<nn>..."
        )
    if len(database) + len(STAGING_SUFFIX) > MAX_NAME:
        raise TargetRefused(f"refusing to replace {database!r}: the name is too long for a staged copy")


def exists(admin_url: str, database: str) -> bool:
    with psycopg.connect(admin_url, autocommit=True) as conn:
        return (
            conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone() is not None
        )


def _info(conn: psycopg.Connection[Any], database: str) -> tuple[str, list[str]] | None:
    row = conn.execute(
        "SELECT pg_get_userbyid(datdba), datacl::text[] FROM pg_database WHERE datname = %s", (database,)
    ).fetchone()
    return None if row is None else (str(row[0]), list(row[1] or []))


def _drop(conn: psycopg.Connection[Any], database: str) -> None:
    row = conn.execute("SELECT datistemplate FROM pg_database WHERE datname = %s", (database,)).fetchone()
    if row is not None and row[0]:
        conn.execute(sql.SQL("ALTER DATABASE {} WITH IS_TEMPLATE false").format(sql.Identifier(database)))
    conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database)))


def _create(conn: psycopg.Connection[Any], target: str, template: str, owner: str) -> None:
    conn.execute(
        sql.SQL("CREATE DATABASE {} TEMPLATE {} OWNER {} STRATEGY FILE_COPY").format(
            sql.Identifier(target), sql.Identifier(template), sql.Identifier(owner)
        )
    )


def _apply_acl(conn: psycopg.Connection[Any], target: str, acl: list[str]) -> None:
    """Database-level ACLs are not copied with a template: the target gets `acl` (empty = the default)."""
    if not acl:
        return
    target_id = sql.Identifier(target)
    conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(target_id))
    for item in acl:
        grantee, _, rest = str(item).partition("=")
        wanted = [ACL_PRIVILEGES[ch] for ch in rest.split("/")[0] if ch in ACL_PRIVILEGES]
        if not wanted:
            continue
        who = sql.SQL("PUBLIC") if not grantee else sql.Identifier(grantee.strip('"'))
        conn.execute(
            sql.SQL("GRANT {} ON DATABASE {} TO {}").format(
                sql.SQL(", ").join(sql.SQL(p) for p in wanted), target_id, who
            )
        )


def mark(conn: psycopg.Connection[Any], database: str, bookmark_id: str | None) -> None:
    text = sql.Literal(MARK_PREFIX + bookmark_id) if bookmark_id else sql.NULL
    conn.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(sql.Identifier(database), text))


def marked_bookmark(comment: str | None) -> str | None:
    if not comment or not comment.startswith(MARK_PREFIX):
        return None
    return comment[len(MARK_PREFIX) :] or None


def snapshot(admin_url: str, source: str, bm: Bookmark) -> float:
    """Copy `source` (no other session may be connected) to the bookmark's template database."""
    started = time.perf_counter()
    with psycopg.connect(admin_url, autocommit=True) as conn:
        info = _info(conn, source)
        if info is None:
            raise LookupError(f"database {source} does not exist")
        owner, acl = info
        _drop(conn, bm.template)
        _create(conn, bm.template, source, owner)
        _apply_acl(conn, bm.template, acl)
        conn.execute(
            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(bm.template), sql.Literal(f"SGW demo bookmark template {bm.id}: {bm.title}")
            )
        )
        conn.execute(
            sql.SQL("ALTER DATABASE {} WITH IS_TEMPLATE true ALLOW_CONNECTIONS false").format(
                sql.Identifier(bm.template)
            )
        )
    return time.perf_counter() - started


def goto(
    admin_url: str,
    bm: Bookmark,
    database: str,
    retire: Callable[[str], list[Path]] | None = None,
) -> GotoReport:
    check_target(database)
    started = time.perf_counter()
    staging = database + STAGING_SUFFIX
    with psycopg.connect(admin_url, autocommit=True) as conn:
        template = _info(conn, bm.template)
        if template is None:
            raise LookupError(
                f"bookmark {bm.id} is not built (no database {bm.template}); run `uv run sgw demo build`"
            )
        owner, acl = _info(conn, database) or template
        _drop(conn, staging)
        try:
            _create(conn, staging, bm.template, owner)
        except psycopg.Error:
            _drop(conn, staging)
            raise
        _drop(conn, database)
        conn.execute(
            sql.SQL("ALTER DATABASE {} RENAME TO {}").format(
                sql.Identifier(staging), sql.Identifier(database)
            )
        )
        _apply_acl(conn, database, acl)
        mark(conn, database, bm.id)
    retired = retire(database) if retire else []
    return GotoReport(bm.id, database, bm.template, time.perf_counter() - started, retired)
