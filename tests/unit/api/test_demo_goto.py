"""CA #3: a presenter loads a demo moment's full state from the UI (`POST /api/demo/goto`): DEMO_MODE
and a goto connection only, clock-operator roles only, the session survives the copy and the API follows the
new database."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from sgw.api import demo_goto
from sgw.api.app import create_app
from sgw.api.routers import demo as demo_router
from sgw.api.settings import ApiSettings
from sgw.api.users import seed_users
from sgw.approval import testkit as tk
from sgw.approval.seed import run_seed
from sgw.contracts.api_models import DemoGotoResult, ScenarioState
from sgw.demo import snapshots
from sgw.demo.bookmarks import Bookmark

PASSWORD = "sx5-" + secrets.token_hex(12)
NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
MARKER = "SX5-GOTO-MARKER"


def _client(url: str, demo: bool = True) -> TestClient:
    settings = ApiSettings(
        database_url=url, demo_mode=demo, cookie_secure=False, login_ip_burst=1000, login_user_burst=1000
    )
    return TestClient(create_app(settings))


def _login(c: TestClient, user_id: str) -> dict[str, str]:
    r = c.post("/api/auth/login", json={"user_id": user_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": c.cookies["sgw_csrf"]}


@pytest.fixture
def target() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: demo goto needs Postgres
    with tk.scratch_database("sgw_wp29_sx5_t") as url:
        run_seed(url, use_default_ledger=False)
        seed_users(url, PASSWORD)
        yield url


@pytest.fixture
def moment(monkeypatch: pytest.MonkeyPatch) -> Iterator[Bookmark]:
    admin = tk.admin_dsn()
    assert admin is not None
    bm = Bookmark(
        f"zz-sx5-{uuid.uuid4().hex[:8]}", "Test moment", "2024-09-27T12:00:00Z", "test", None, None, ""
    )
    with tk.scratch_database("sgw_wp29_sx5_src") as source:
        run_seed(source, use_default_ledger=False)
        seed_users(source, PASSWORD)
        with psycopg.connect(source, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO region (region_id, state, county_fips, name)"
                " VALUES (%s, 'SC', '45999', 'Marker')",
                (MARKER,),
            )
        snapshots.snapshot(admin, source.rpartition("/")[2], bm)
    monkeypatch.setitem(demo_router.BY_ID, bm.id, bm)
    monkeypatch.setenv(demo_goto.DSN_ENV, admin)
    try:
        yield bm
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            snapshots._drop(conn, bm.template)


def _marker(url: str) -> bool:
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT 1 FROM region WHERE region_id = %s", (MARKER,)).fetchone() is not None


def test_without_a_goto_connection_the_moment_cannot_be_loaded(
    target: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(demo_goto.DSN_ENV, raising=False)
    with _client(target) as c:
        csrf = _login(c, "ic_01")
        assert ScenarioState.model_validate(c.get("/api/scenario").json()).loads_moments is False
        r = c.post("/api/demo/goto", json={"bookmark": "morning-after"}, headers=csrf)
        assert r.status_code == 503 and r.json()["error"]["code"] == "DEMO_GOTO_UNAVAILABLE", r.text


def test_outside_demo_mode_the_moment_cannot_be_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(demo_goto.DSN_ENV, "postgresql://unused/sgw")
    live = ApiSettings(database_url="postgresql://unused/sgw", demo_mode=False, cookie_secure=True)
    demo = ApiSettings(database_url="postgresql://unused/sgw", demo_mode=True, cookie_secure=False)
    assert demo_goto.available(demo) and not demo_goto.available(live)
    monkeypatch.delenv(demo_goto.DSN_ENV)
    assert not demo_goto.available(demo)


def test_a_reader_may_not_load_and_an_unknown_moment_is_404(target: str, moment: Bookmark) -> None:
    with _client(target) as c:
        csrf = _login(c, "admin_01")
        assert c.post("/api/demo/goto", json={"bookmark": moment.id}, headers=csrf).status_code == 403
        csrf = _login(c, "ic_01")
        r = c.post("/api/demo/goto", json={"bookmark": "landfall"}, headers=csrf)
        assert r.status_code == 404 and r.json()["error"]["code"] == "DEMO_MOMENT_NOT_FOUND", r.text
    assert not _marker(target)


def test_a_presenter_loads_the_moment_and_stays_signed_in(target: str, moment: Bookmark) -> None:
    with _client(target) as c:
        csrf = _login(c, "ic_01")
        assert ScenarioState.model_validate(c.get("/api/scenario").json()).loads_moments is True
        paused = c.post("/api/scenario", json={"action": "pause"}, headers=csrf)
        assert ScenarioState.model_validate(paused.json()).loads_moments is True, "a jump keeps Load scenario"
        r = c.post("/api/demo/goto", json={"bookmark": moment.id}, headers=csrf)
        assert r.status_code == 200, r.text
        result = DemoGotoResult.model_validate(r.json())
        assert result.bookmark == moment.id and result.seconds >= 0
        assert _marker(target)
        me = c.get("/api/me")
        assert me.status_code == 200 and me.json()["user_id"] == "ic_01", me.text
        assert c.get("/api/proposals").status_code == 200


def test_a_presenter_stays_signed_in_when_the_audit_anchors_cannot_be_set_aside(
    target: str, moment: Bookmark, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The live stack mounts the anchor store read-only: retiring the old anchors fails after the copy is in
    place, which once turned the load into a 500 and dropped the presenter's session."""
    from sgw.approval.audit import AnchorStore

    def read_only(self: AnchorStore, database: str) -> Path | None:
        raise OSError(30, "Read-only file system")

    monkeypatch.setenv(demo_goto.ANCHORS_ENV, str(tmp_path))
    monkeypatch.setattr(AnchorStore, "retire", read_only)
    with _client(target) as c:
        csrf = _login(c, "ops_dm_01")
        r = c.post("/api/demo/goto", json={"bookmark": moment.id}, headers=csrf)
        assert r.status_code == 200, r.text
        assert _marker(target)
        me = c.get("/api/me")
        assert me.status_code == 200 and me.json()["user_id"] == "ops_dm_01", me.text
