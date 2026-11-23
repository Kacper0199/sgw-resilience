"""Load a demo moment from the UI (CA #3): the API's own database is replaced by a bookmark template
copy (`sgw.demo.snapshots.goto`, the same copy as `sgw demo goto`), so signatures, the published ETR and the
after-action state are reached without the CLI. Only with `DEMO_MODE=1` and a goto connection in
`SGW_DEMO_GOTO_DSN` (a server role allowed to create and drop databases; never logged or returned).

The presenter's session row is carried into the copy, so the browser stays signed in; the audit anchors of
the replaced chain are retired when the anchors directory is configured; the API then follows the new database
epoch (clock and ledger stream reload, clients resync)."""

from __future__ import annotations

import logging
import os
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from sgw.api.settings import ApiSettings
from sgw.demo import snapshots
from sgw.demo.bookmarks import Bookmark

DSN_ENV = "SGW_DEMO_GOTO_DSN"
ANCHORS_ENV = "SGW_AUDIT_ANCHORS_DIR"
SESSION_COLUMNS = ("token_hash", "user_id", "created_at", "expires_at", "demo_switch", "step_up_at")


log = logging.getLogger(__name__)


class GotoUnavailable(RuntimeError):
    pass


def goto_dsn() -> str | None:
    raw = os.environ.get(DSN_ENV, "").strip()
    return raw or None


def available(settings: ApiSettings) -> bool:
    return settings.demo_mode and goto_dsn() is not None


def database_of(url: str) -> str:
    name = urllib.parse.urlsplit(url).path.lstrip("/")
    if not name:
        raise GotoUnavailable("the API database URL names no database")
    return name


def _with_database(dsn: str, database: str) -> str:
    parts = urllib.parse.urlsplit(dsn)
    return urllib.parse.urlunsplit(parts._replace(path=f"/{database}"))


def _session(conn: psycopg.Connection[Any], token_hash: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {', '.join(SESSION_COLUMNS)} FROM session WHERE token_hash = %s",  # noqa: S608
        (token_hash,),
    ).fetchone()
    return None if row is None else dict(zip(SESSION_COLUMNS, row, strict=True))


def _restore_session(conn: psycopg.Connection[Any], session: dict[str, Any]) -> None:
    conn.execute(
        f"INSERT INTO session ({', '.join(SESSION_COLUMNS)})"  # noqa: S608
        f" SELECT {', '.join(['%s'] * len(SESSION_COLUMNS))}"
        " WHERE EXISTS (SELECT 1 FROM app_user WHERE user_id = %s) ON CONFLICT (token_hash) DO NOTHING",
        (*[session[c] for c in SESSION_COLUMNS], session["user_id"]),
    )


def _retire(database: str) -> list[Path]:
    """Set the replaced database's audit anchors aside. The copy is already in place when this runs, so a
    store the API cannot write (a read-only mount) is logged and left as it is, never a failed load."""
    root = os.environ.get(ANCHORS_ENV, "").strip()
    if not root:
        return []
    from sgw.approval.audit import AnchorStore

    try:
        retired = AnchorStore(Path(root)).retire(database)
    except OSError as error:
        log.warning("demo goto: audit anchors of %s not set aside: %s", database, error.strerror)
        return []
    return [retired] if retired is not None else []


@dataclass(frozen=True)
class Loaded:
    bookmark: Bookmark
    seconds: float
    scenario_time: datetime


def load(settings: ApiSettings, bm: Bookmark, session_hash: str) -> Loaded:
    """Blocking: copy the bookmark template over the API's database and keep the caller's session."""
    dsn = goto_dsn()
    if not settings.demo_mode or dsn is None:
        raise GotoUnavailable("loading a demo moment needs DEMO_MODE and a goto connection")
    database = database_of(settings.database_url)
    snapshots.check_target(database)
    with psycopg.connect(_with_database(dsn, database), autocommit=True) as conn:
        session = _session(conn, session_hash)
    try:
        report = snapshots.goto(dsn, bm, database, retire=_retire)
    finally:
        if session is not None:
            with psycopg.connect(_with_database(dsn, database), autocommit=True) as conn:
                _restore_session(conn, session)
    return Loaded(bm, report.seconds, datetime.fromisoformat(bm.scenario_time.replace("Z", "+00:00")))
