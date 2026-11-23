"""DX phase 2 through the real app: one source of truth for the scenario period, the scenario
menu's key moments and presenter jumps (Q-08 B), and Readiness read on its own pre-season review date."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from sgw.api.app import create_app
from sgw.api.scenario_info import scenario_period
from sgw.api.settings import ApiSettings
from sgw.api.users import seed_users
from sgw.approval import testkit as tk
from sgw.contracts.api_models import ReadinessItem, ScenarioState
from sgw.demo.bookmarks import BY_ID

PASSWORD = "r26dx2-" + secrets.token_hex(12)
NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
REVIEW = datetime(2024, 5, 6, 12, 0, tzinfo=UTC)
JUMPS = ("before-n", "at-n", "at-n1", "morning-after", "etr-published", "notices-lifted", "after-action")


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: scenario period reads need Postgres
    from sgw.approval.seed import run_seed

    with tk.scratch_database("sgw_r26dx2_t") as url:
        run_seed(url, use_default_ledger=False)
        seed_users(url, PASSWORD)
        settings = ApiSettings(
            database_url=url, demo_mode=True, cookie_secure=False, login_ip_burst=1000, login_user_burst=1000
        )
        with TestClient(create_app(settings)) as c:
            yield c


def login(c: TestClient, user_id: str) -> dict[str, str]:
    r = c.post("/api/auth/login", json={"user_id": user_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": c.cookies["sgw_csrf"]}


def test_the_period_is_the_replay_window_in_eastern_time() -> None:
    period = scenario_period("helene")
    assert period.start_utc == datetime(2024, 9, 23, 12, 0, tzinfo=UTC)
    assert period.end_utc == datetime(2024, 10, 6, 12, 0, tzinfo=UTC)
    assert period.time_zone == "America/New_York"
    assert period.label == "23 Sep – 6 Oct 2024"
    assert period.title == "Hurricane Helene"
    assert "23 Sep 2024" in period.statement and "6 Oct 2024" in period.statement
    assert "today" in period.statement


def test_the_scenario_carries_its_period_moments_and_jumps(client: TestClient) -> None:
    login(client, "audit_01")
    state = ScenarioState.model_validate(client.get("/api/scenario").json())
    assert state.period == scenario_period("helene")
    kinds = [m.kind for m in state.moments]
    assert kinds.count("advisory") == 12 and "landfall" in kinds
    assert [m.moment_id for m in state.jumps] == list(JUMPS)
    for jump in state.jumps:
        assert jump.scenario_time == datetime.fromisoformat(BY_ID[jump.moment_id].scenario_time)
        assert "N+1" not in jump.label and not jump.label.startswith("Advisory N")
    assert all(state.window_start <= m.scenario_time <= state.window_end for m in state.moments + state.jumps)


def test_a_presenter_jumps_and_a_reader_may_not(client: TestClient) -> None:
    target = next(j for j in ScenarioState.model_validate(client.get("/api/scenario").json()).jumps)
    csrf = login(client, "admin_01")
    body = {"action": "seek", "scenario_time": target.scenario_time.isoformat()}
    assert client.post("/api/scenario", json=body, headers=csrf).status_code == 403
    csrf = login(client, "ic_01")
    r = client.post("/api/scenario", json=body, headers=csrf)
    assert r.status_code == 200, r.text
    assert ScenarioState.model_validate(r.json()).scenario_time == target.scenario_time


def test_readiness_is_read_on_its_pre_season_review_date(client: TestClient) -> None:
    csrf = login(client, "ic_01")
    at = BY_ID["after-action"].scenario_time
    assert (
        client.post("/api/scenario", json={"action": "seek", "scenario_time": at}, headers=csrf).status_code
        == 200
    )
    items = [ReadinessItem.model_validate(i) for i in client.get("/api/readiness").json()]
    assert items and {i.evaluated_at_utc for i in items} == {REVIEW}
    assert {i.status for i in items} == {"gap"}
