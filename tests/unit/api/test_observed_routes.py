"""GD routes over HTTP with the real app lifespan on a migrated scratch database: `/api/hazard/observed` and
`/api/after-action/official-record` need a session, never answer past the scenario clock (an `as_of` ahead
of it is capped), refuse a naive `as_of`, and revalidate with ETag/304."""

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
from sgw.contracts.api_models import ObservedHazard, OfficialRecord
from sgw.contracts.vocab import ApprovalFunction, Domain

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
        pytest.skip(NO_DB)  # sgw-allow-skip: routes need Postgres
    with tk.scratch_database("sgw_gd_t") as url:
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


def test_reads_need_a_session(db_url: str) -> None:
    with _client(db_url, signed_in=False) as anon:
        for path in ("/api/hazard/observed", "/api/after-action/official-record"):
            r = anon.get(path)
            assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_observed_defaults_to_the_clock_and_caps_a_later_as_of(client: TestClient) -> None:
    now = ObservedHazard.model_validate(client.get("/api/hazard/observed").json())
    assert now.as_of == T_CLOCK
    ahead = ObservedHazard.model_validate(
        client.get("/api/hazard/observed", params={"as_of": "2024-10-02T00:00:00Z"}).json()
    )
    assert ahead.as_of == T_CLOCK and ahead == now
    assert all(g.peak_utc is None or g.peak_utc <= T_CLOCK for g in now.gauges)
    assert {s.station for s in now.stations} == {"AGS", "CAE", "CHS", "GSP", "SAV", "VLD"}
    assert {w.kind for w in now.warnings} >= {"hurricane", "flash_flood"}


def test_observed_looks_back(client: TestClient) -> None:
    early = ObservedHazard.model_validate(
        client.get("/api/hazard/observed", params={"as_of": "2024-09-26T09:00:00Z"}).json()
    )
    assert early.as_of == datetime(2024, 9, 26, 9, tzinfo=UTC)
    gusts = {s.station: s.gust_mph or 0 for s in early.stations}
    later = {
        s.station: s.gust_mph or 0
        for s in ObservedHazard.model_validate(client.get("/api/hazard/observed").json()).stations
    }
    assert all(later[k] >= v for k, v in gusts.items()) and later["AGS"] > gusts["AGS"]


def test_naive_as_of_is_refused(client: TestClient) -> None:
    r = client.get("/api/hazard/observed", params={"as_of": "2024-09-26T09:00:00"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_AS_OF"


def test_etag_revalidates(client: TestClient) -> None:
    first = client.get("/api/hazard/observed")
    again = client.get("/api/hazard/observed", headers={"If-None-Match": first.headers["ETag"]})
    assert again.status_code == 304
    assert first.headers["Cache-Control"] == "private, no-cache"


def test_official_record_follows_the_clock(client: TestClient) -> None:
    body = OfficialRecord.model_validate(client.get("/api/after-action/official-record").json())
    assert body.as_of == T_CLOCK and body.declarations == []
    assert body.events_total > 0 and all(e.begin_utc <= T_CLOCK for e in body.top_events)
    _stop_clock(client, datetime(2024, 10, 1, tzinfo=UTC))
    try:
        later = OfficialRecord.model_validate(client.get("/api/after-action/official-record").json())
        assert [d.declaration_id for d in later.declarations] == ["DR-4829-SC", "DR-4830-GA"]
        assert later.events_total >= body.events_total
    finally:
        _stop_clock(client, T_CLOCK)
