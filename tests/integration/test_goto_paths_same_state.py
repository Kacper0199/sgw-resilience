"""V4-01: `sgw demo goto` (CLI, after every rebuild) and the API's Load moment leave the same decision and
queue state: both run the scenario jobs (advisory queue, zone rules, exercise injects) at the moment's time
before anyone reads it, so Ask's read models match the recordings either way."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from sgw.api import demo_goto, scenario_jobs
from sgw.api.app import create_app
from sgw.api.routers import demo as demo_router
from sgw.api.settings import ApiSettings
from sgw.api.users import seed_users
from sgw.approval import testkit as tk
from sgw.approval.ledger import default_sink
from sgw.approval.policy import ReferencePolicy
from sgw.approval.seed import run_seed
from sgw.approval.service import ApprovalService
from sgw.cli.commands import demo as demo_cli
from sgw.cli.main import build_app
from sgw.demo import bookmarks, snapshots
from sgw.demo.bookmarks import Bookmark
from sgw.models.clocks import zone_cases
from sgw.rules import injects

PASSWORD = "v401-" + secrets.token_hex(12)
AT_N1 = "2024-09-26T15:05:00Z"


@dataclass(frozen=True)
class _Credentials:
    admin: str

    def admin_dsn(self) -> str:
        return self.admin


def _api(url: str) -> tuple[TestClient, Any]:
    app = create_app(
        ApiSettings(
            database_url=url, demo_mode=True, cookie_secure=False, login_ip_burst=1000, login_user_burst=1000
        )
    )
    app.state.approval_service = ApprovalService(
        ReferencePolicy(), scenario_clock=lambda: app.state.sgw.clock.now(), ledger=default_sink()
    )
    return TestClient(app), app


def _login(c: TestClient, user_id: str) -> dict[str, str]:
    r = c.post("/api/auth/login", json={"user_id": user_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": c.cookies["sgw_csrf"]}


def _seeded(url: str) -> None:
    run_seed(url, use_default_ledger=False)
    seed_users(url, PASSWORD)
    with psycopg.connect(url, autocommit=True) as conn:
        for region in sorted({a.region_id for a in injects.load().assets}):
            conn.execute(
                "INSERT INTO region (region_id, state, county_fips, name) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (region_id) DO NOTHING",
                (region, region[:2], region[3:], f"County {region[3:]}"),
            )


def _state(url: str) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    with psycopg.connect(url) as conn:
        cases = conn.execute(
            "SELECT decision_case_id, effective_decide_by_utc, no_regret_verdict::text FROM decision_case"
            " ORDER BY decision_case_id"
        ).fetchall()
        proposals = conn.execute(
            "SELECT proposal_id, decision_case_id, state::text, proposal_version FROM proposal"
            " ORDER BY proposal_id"
        ).fetchall()
    return cases, proposals


@pytest.fixture
def moment(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, Bookmark]]:
    admin = tk.admin_dsn()
    if admin is None:
        pytest.skip("no Postgres: set SGW_TEST_DATABASE_URL")  # sgw-allow-skip: goto needs Postgres
    for flag in (zone_cases.FLAG_ENV, zone_cases.INJECTS_FLAG_ENV):
        monkeypatch.setenv(flag, "1")
    monkeypatch.delenv(scenario_jobs.INTERVAL_ENV, raising=False)
    bm = Bookmark(f"zz-v401-{uuid.uuid4().hex[:8]}", "At N+1 (test)", AT_N1, "test", None, None, "")
    with tk.scratch_database("sgw_wp34_f5_src") as source:
        _seeded(source)
        c, _ = _api(source)
        with c:
            csrf = _login(c, "ops_dm_01")
            for body in ({"action": "seek", "scenario_time": AT_N1}, {"action": "pause"}):
                r = c.post("/api/scenario", json=body, headers=csrf)
                assert r.status_code == 200, r.text
        snapshots.snapshot(admin, source.rpartition("/")[2], bm)
    monkeypatch.setitem(demo_router.BY_ID, bm.id, bm)
    real = bookmarks.bookmark
    monkeypatch.setattr(bookmarks, "bookmark", lambda b: bm if b == bm.id else real(b))
    monkeypatch.setenv(demo_goto.DSN_ENV, admin)
    monkeypatch.setattr(demo_cli, "load_credentials", lambda: _Credentials(admin))
    try:
        yield admin, bm
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            snapshots._drop(conn, bm.template)


def test_cli_goto_and_api_load_leave_the_same_decisions_and_queue(
    moment: tuple[str, Bookmark], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, bm = moment
    with tk.scratch_database("sgw_wp34_f5_cli") as cli_url, tk.scratch_database("sgw_wp34_f5_api") as api_url:
        cli_db = cli_url.rpartition("/")[2]
        snapshots.goto(admin, bm, cli_db)
        as_copied = _state(cli_url)
        result = CliRunner().invoke(build_app(), ["demo", "goto", bm.id, "--yes", "-d", cli_db])
        assert result.exit_code == 0, result.output
        assert "scenario jobs at 2024-09-26T15:05:00Z" in result.output

        _seeded(api_url)
        monkeypatch.setenv(scenario_jobs.INTERVAL_ENV, "3600")
        c, _ = _api(api_url)
        with c:
            r = c.post("/api/demo/goto", json={"bookmark": bm.id}, headers=_login(c, "ic_01"))
            assert r.status_code == 200, r.text

        loaded = _state(cli_url)
        assert loaded != as_copied
        assert any(p[0].startswith("PRP-EX-") for p in loaded[1])
        assert _state(api_url) == loaded
