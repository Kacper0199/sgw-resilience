"""`GET /api/outages/surges` over HTTP with the real app lifespan on a migrated scratch database: needs a
session, never answers past the scenario clock (a later `as_of` is capped), looks back, refuses a naive
`as_of`, and equals the read function the copilot tool uses."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from tests.unit.api.clock_testkit import pin_clock

from sgw.api.app import create_app
from sgw.api.deps import current_user
from sgw.api.sessions import AuthUser
from sgw.api.settings import ApiSettings
from sgw.approval import testkit as tk
from sgw.contracts.api_models import SurgeReport
from sgw.contracts.vocab import ApprovalFunction, Domain
from sgw.models.surge.read import list_outage_surges

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
READER = AuthUser(
    user_id="audit_01",
    display_name="Auditor",
    function=ApprovalFunction.AUDIT,
    roles=("auditor",),
    regions=("SC", "GA"),
    domains=(Domain.ELECTRIC, Domain.WATER),
    step_up_at=None,
    session_hash="0" * 64,
    demo_switch=False,
)
T_CLOCK = datetime(2024, 9, 27, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: R27-SU route needs Postgres
    with tk.scratch_database("sgw_su_t") as url:
        yield url


def _client(db_url: str, *, signed_in: bool = True) -> TestClient:
    app = create_app(ApiSettings(database_url=db_url, demo_mode=True, cookie_secure=False))
    if signed_in:
        app.dependency_overrides[current_user] = lambda: READER
    return TestClient(app)


def _stop_clock(client: TestClient, when: datetime) -> None:
    pin_clock(client, when)


@pytest.fixture(scope="module")
def client(db_url: str) -> Iterator[TestClient]:
    with _client(db_url) as c:
        _stop_clock(c, T_CLOCK)
        yield c


def test_surges_need_a_session(db_url: str) -> None:
    with _client(db_url, signed_in=False) as anon:
        r = anon.get("/api/outages/surges")
        assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_surges_default_to_the_clock_and_cap_a_later_as_of(client: TestClient) -> None:
    now = SurgeReport.model_validate(client.get("/api/outages/surges").json())
    assert now.as_of == T_CLOCK and now == list_outage_surges(T_CLOCK)
    ahead = client.get("/api/outages/surges", params={"as_of": "2024-10-02T00:00:00Z"}).json()
    assert SurgeReport.model_validate(ahead) == now
    assert all(s.detected_at <= T_CLOCK for s in now.surges) and now.counties_surging > 90


def test_surges_look_back_and_refuse_a_naive_as_of(client: TestClient) -> None:
    early = SurgeReport.model_validate(
        client.get("/api/outages/surges", params={"as_of": "2024-09-26T12:00:00Z"}).json()
    )
    assert early.surges_total < 5
    naive = client.get("/api/outages/surges", params={"as_of": "2024-09-26T12:00:00"})
    assert naive.status_code == 422 and naive.json()["error"]["code"] == "INVALID_AS_OF"
