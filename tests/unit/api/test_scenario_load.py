"""A presenter loads the Hurricane Ian exercise and returns to Helene (`POST /api/demo/scenario`):
the same DEMO_MODE, goto connection and clock-operator rule as Load moment; Ian switches the stored clock and
every page read to the pack; Helene comes back from its own template."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator

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
from sgw.contracts.api_models import ScenarioLoadResult, ScenarioState
from sgw.demo import snapshots
from sgw.demo.bookmarks import Bookmark

PASSWORD = "b2-" + secrets.token_hex(12)
NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"


def _client(url: str) -> TestClient:
    settings = ApiSettings(
        database_url=url, demo_mode=True, cookie_secure=False, login_ip_burst=1000, login_user_burst=1000
    )
    return TestClient(create_app(settings))


def _login(c: TestClient, user_id: str) -> dict[str, str]:
    r = c.post("/api/auth/login", json={"user_id": user_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": c.cookies["sgw_csrf"]}


@pytest.fixture
def target(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    admin = tk.admin_dsn()
    if admin is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: scenario load needs Postgres
    bm = Bookmark(
        f"zz-b2-{uuid.uuid4().hex[:8]}", "Test moment", "2024-09-26T15:05:00Z", "test", None, None, ""
    )
    with tk.scratch_database("sgw_wp34_b2_src") as source:
        run_seed(source, use_default_ledger=False)
        seed_users(source, PASSWORD)
        snapshots.snapshot(admin, source.rpartition("/")[2], bm)
    monkeypatch.setitem(demo_router.BY_ID, bm.id, bm)
    monkeypatch.setattr(demo_router, "PACK_BASE_MOMENT", bm.id)
    monkeypatch.setattr(demo_router, "HELENE_RETURN_MOMENT", bm.id)
    monkeypatch.setenv(demo_goto.DSN_ENV, admin)
    try:
        with tk.scratch_database("sgw_wp34_b2_t") as url:
            run_seed(url, use_default_ledger=False)
            seed_users(url, PASSWORD)
            yield url
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            snapshots._drop(conn, bm.template)


def test_a_reader_may_not_load_a_scenario(target: str) -> None:
    with _client(target) as c:
        csrf = _login(c, "exec_01")
        assert c.post("/api/demo/scenario", json={"scenario": "ian"}, headers=csrf).status_code == 403
        csrf = _login(c, "ic_01")
        assert c.post("/api/demo/scenario", json={"scenario": "debby"}, headers=csrf).status_code == 422


def test_a_presenter_loads_ian_and_returns_to_helene(target: str) -> None:
    with _client(target) as c:
        csrf = _login(c, "ic_01")
        r = c.post("/api/demo/scenario", json={"scenario": "ian"}, headers=csrf)
        assert r.status_code == 200, r.text
        result = ScenarioLoadResult.model_validate(r.json())
        assert result.scenario == "ian" and result.title == "Hurricane Ian"
        state = ScenarioState.model_validate(c.get("/api/scenario").json())
        assert state.scenario == "ian" and state.scenario_time == result.scenario_time
        assert state.period is not None and state.period.data_note == "Scripted exercise data (synthetic)"
        assert [j.label for j in state.jumps][0] == "Day before landfall"
        assert c.get("/api/me").json()["user_id"] == "ic_01"
        assert all(p["proposal_id"].startswith("PRP-IAN-") for p in c.get("/api/proposals").json())
        brief = c.get("/api/brief").json()
        assert brief["caveat"].startswith("Scripted exercise data (synthetic)")
        assert c.get("/api/outages/counties").json()["customers_out_now"] == 0
        assert c.get("/api/hazard/advisories").json()[-1]["advisory_label"].startswith("IAN-")
        assert c.get("/api/hazard/observed").json()["gauges"] == []
        assert c.get("/api/outages/surges").json()["surges"] == []
        assert c.get("/api/water/advisories").json()["advisories"] == []
        crews = c.get("/api/crews").json()
        assert len(crews) == 38 and {k["status"] for k in crews} == {"available"}
        review = c.get("/api/after-action").json()
        assert review["clocks"] == [] and review["sc_report"] is None
        assert review["scorecard"]["name"] == "Not modelled for this scenario"
        csrf = {"X-CSRF-Token": c.cookies["sgw_csrf"]}
        back = c.post("/api/demo/scenario", json={"scenario": "helene"}, headers=csrf)
        assert back.status_code == 200, back.text
        assert ScenarioState.model_validate(c.get("/api/scenario").json()).scenario == "helene"
