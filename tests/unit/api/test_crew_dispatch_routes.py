"""Crew dispatch over HTTP with the real app lifespan on a scratch database: a dispatcher
assigns a crew to an open decision or a staging yard, the named function signs, the crew moves through
plain states (each move a K2 CrewStatus event in the ledger, read back by `GET /api/crews`), every change is a
record in the hash-chained audit log, and read-only personas are offered no action and refused on write."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from tests.unit.api.clock_testkit import pin_clock

from sgw.api.app import create_app
from sgw.api.deps import current_user, writer
from sgw.api.sessions import AuthUser
from sgw.api.settings import ApiSettings
from sgw.approval import audit
from sgw.approval import testkit as tk
from sgw.approval.ledger import OutboxSink
from sgw.contracts.api_models import CrewItem, CrewTarget
from sgw.contracts.vocab import ApprovalFunction, CrewStatus, Domain
from sgw.dispatch.policy import ReferenceDispatch
from sgw.dispatch.service import Crew, DispatchService, crew_status_envelope

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
T0 = datetime(2024, 9, 26, 10, 0, tzinfo=UTC)
NOW = T0 + timedelta(hours=5)
CASE = "DC-D2-CREWS-AIK"
SANDHILL = "STG-AIK-SANDHILL-YARD"
MILLPOND = "STG-RCH-MILLPOND-YARD"
CREWS = ("CRW-AUKLET-0301", "CRW-BITTERN-0302", "CRW-COOT-0303", "CRW-DUNLIN-0304")
PERSONAS = {
    "admin_01": ("platform_admin", ApprovalFunction.PLATFORM),
    "ops_dm_01": ("duty_manager", ApprovalFunction.OPERATIONS),
    "log_01": ("logistics_chief", ApprovalFunction.LOGISTICS),
    "exec_01": ("executive", ApprovalFunction.EXECUTIVE),
}


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: CR dispatch routes need Postgres
    with tk.seeded_database() as url:
        sink = OutboxSink()
        with psycopg.connect(url, autocommit=True) as conn:
            with conn.transaction():
                for i, crew_id in enumerate(CREWS):
                    crew = Crew(crew_id, CrewStatus.AVAILABLE, None, 24, "SC-45003", "electric")
                    at = T0 + timedelta(minutes=i)
                    sink.enqueue(
                        conn, [crew_status_envelope(crew, CrewStatus.AVAILABLE, at=at, location_id=None)]
                    )
            sink.drain(conn)
        yield url


class Session:
    user_id = "ops_dm_01"

    def auth(self) -> AuthUser:
        role, function = PERSONAS[self.user_id]
        return AuthUser(
            user_id=self.user_id,
            display_name=self.user_id,
            function=function,
            roles=(role,),
            regions=("SC", "GA"),
            domains=(Domain.ELECTRIC, Domain.WATER),
            step_up_at=None,
            session_hash="0" * 64,
            demo_switch=False,
        )


@pytest.fixture(scope="module")
def session() -> Session:
    return Session()


@pytest.fixture(scope="module")
def client(db_url: str, session: Session) -> Iterator[TestClient]:
    app = create_app(ApiSettings(database_url=db_url, demo_mode=True))
    app.dependency_overrides[current_user] = session.auth
    app.dependency_overrides[writer] = session.auth
    with TestClient(app) as c:
        app.state.dispatch_service = DispatchService(
            ReferenceDispatch(), scenario_clock=app.state.sgw.clock.now, ledger=OutboxSink()
        )
        yield c


@pytest.fixture(autouse=True)
def stopped_clock(client: TestClient, db_url: str) -> None:
    """Stop the scenario clock at NOW before every test, in the control row (the broadcaster re-reads it)
    and in-process, so a late start-up read of the clock never moves it."""
    pin_clock(client, NOW)


def as_(client: TestClient, session: Session, user_id: str) -> TestClient:
    session.user_id = user_id
    return client


def crew(client: TestClient, crew_id: str) -> CrewItem:
    found = [CrewItem.model_validate(c) for c in client.get("/api/crews").json() if c["crew_id"] == crew_id]
    assert len(found) == 1, crew_id
    return found[0]


def post(client: TestClient, path: str, body: dict[str, Any] | None = None) -> Any:
    return client.post(path, json=body or {})


def test_targets_are_open_decisions_and_staging_yards(client: TestClient, session: Session) -> None:
    targets = [
        CrewTarget.model_validate(t) for t in as_(client, session, "exec_01").get("/api/crews/targets").json()
    ]
    decisions = [t for t in targets if t.kind == "decision"]
    assert [t.target_id for t in decisions] == [CASE]
    assert decisions[0].proposal_id is not None
    yards = {t.target_id: t.label for t in targets if t.kind == "yard"}
    assert yards[SANDHILL] == "Sandhill yard" and yards[MILLPOND] == "Millpond yard"


@pytest.mark.parametrize("user_id", ["exec_01", "admin_01"])
def test_non_dispatchers_see_no_action_and_are_refused(
    client: TestClient, session: Session, user_id: str
) -> None:
    c = as_(client, session, user_id)
    assert all(item["actions"] == [] for item in c.get("/api/crews").json())
    r = post(c, f"/api/crews/{CREWS[3]}/assignments", {"target_kind": "yard", "target_id": SANDHILL})
    assert r.status_code == 403 and r.json()["error"]["code"] == "DISPATCH_DENIED"
    r = post(c, f"/api/crews/{CREWS[3]}/status", {"move": "blocked", "block_reason": "road_closed"})
    assert r.status_code == 403


def test_assign_to_a_decision_sign_and_move_to_site(
    client: TestClient, session: Session, db_url: str
) -> None:
    crew_id = CREWS[0]
    c = as_(client, session, "ops_dm_01")
    assert crew(c, crew_id).actions == ["assign", "block"]
    r = post(c, f"/api/crews/{crew_id}/assignments", {"target_kind": "decision", "target_id": CASE})
    assert r.status_code == 201, r.text
    assignment_id = r.json()["assignment_id"]
    pending = crew(c, crew_id)
    assert pending.assignment is not None and pending.assignment.state == "proposed"
    assert pending.assignment.required_function is ApprovalFunction.LOGISTICS
    assert pending.assignment.target_label.startswith("Pre-position crews")
    assert "sign" not in pending.actions and "withdraw" in pending.actions
    r = post(c, f"/api/crews/{crew_id}/assignment/sign", {"decision": "approve"})
    assert r.status_code == 403 and "self_sign" in r.json()["error"]["details"]["deny"]

    c = as_(client, session, "log_01")
    assert crew(c, crew_id).actions[:2] == ["sign", "reject"]
    assert post(c, f"/api/crews/{crew_id}/assignment/sign", {"decision": "approve"}).status_code == 200
    signed = crew(c, crew_id)
    assert signed.assignment is not None and signed.assignment.state == "assigned"
    assert signed.assignment.decided_by == "log_01"
    assert signed.actions == ["enroute", "onsite", "block", "release"]

    c = as_(client, session, "ops_dm_01")
    assert post(c, f"/api/crews/{crew_id}/status", {"move": "enroute"}).status_code == 200
    moving = crew(c, crew_id)
    assert moving.status is CrewStatus.ENROUTE and moving.location_id == SANDHILL
    assert post(c, f"/api/crews/{crew_id}/status", {"move": "staged"}).status_code == 409
    assert post(c, f"/api/crews/{crew_id}/status", {"move": "onsite"}).status_code == 200
    assert crew(c, crew_id).status is CrewStatus.ONSITE
    assert post(c, f"/api/crews/{crew_id}/status", {"move": "release"}).status_code == 200
    released = crew(c, crew_id)
    assert released.status is CrewStatus.AVAILABLE and released.assignment is None

    with psycopg.connect(db_url, autocommit=True) as conn:
        kinds = [
            r[0]
            for r in conn.execute(
                "SELECT kind FROM audit_event WHERE subject = ANY(%s) ORDER BY seq",
                ([assignment_id, crew_id],),
            )
        ]
        assert kinds == [
            "crew_assignment_proposed",
            "crew_assignment_signed",
            "crew_status_changed",
            "crew_status_changed",
            "crew_released",
        ]
        assert audit.verify(conn).first_bad_seq is None
        sources = conn.execute(
            "SELECT DISTINCT source_id FROM event WHERE type = 'CrewStatus' AND payload->>'crew_id' = %s"
            " AND scenario_known_at = %s",
            (crew_id, NOW),
        ).fetchall()
        assert sources == [("sgw-dispatch",)]


def test_logistics_proposes_to_a_yard_and_operations_signs(client: TestClient, session: Session) -> None:
    crew_id = CREWS[1]
    c = as_(client, session, "log_01")
    r = post(c, f"/api/crews/{crew_id}/assignments", {"target_kind": "yard", "target_id": MILLPOND})
    assert r.status_code == 201
    a = crew(c, crew_id).assignment
    assert (
        a is not None
        and a.required_function is ApprovalFunction.OPERATIONS
        and a.target_label == "Millpond yard"
    )
    c = as_(client, session, "ops_dm_01")
    assert post(c, f"/api/crews/{crew_id}/assignment/sign", {"decision": "approve"}).status_code == 200
    assert crew(c, crew_id).actions == ["enroute", "staged", "block", "release"]
    assert post(c, f"/api/crews/{crew_id}/status", {"move": "staged"}).status_code == 200
    staged = crew(c, crew_id)
    assert staged.status is CrewStatus.STAGED and staged.location_id == MILLPOND
    r = post(c, f"/api/crews/{crew_id}/assignments", {"target_kind": "yard", "target_id": SANDHILL})
    assert r.status_code == 409


def test_reject_and_withdraw_close_the_assignment(client: TestClient, session: Session) -> None:
    crew_id = CREWS[2]
    c = as_(client, session, "ops_dm_01")
    body = {"target_kind": "yard", "target_id": SANDHILL}
    assert post(c, f"/api/crews/{crew_id}/assignments", body).status_code == 201
    c = as_(client, session, "log_01")
    assert post(c, f"/api/crews/{crew_id}/assignment/sign", {"decision": "reject"}).status_code == 200
    assert crew(c, crew_id).assignment is None
    c = as_(client, session, "ops_dm_01")
    assert post(c, f"/api/crews/{crew_id}/assignments", body).status_code == 201
    assert post(c, f"/api/crews/{crew_id}/assignment/withdraw").status_code == 200
    assert crew(c, crew_id).assignment is None
    assert post(c, f"/api/crews/{crew_id}/assignment/withdraw").status_code == 409


def test_blocked_needs_a_reason_and_clearing_returns_the_status_before(
    client: TestClient, session: Session
) -> None:
    crew_id = CREWS[3]
    c = as_(client, session, "ops_dm_01")
    r = post(c, f"/api/crews/{crew_id}/status", {"move": "blocked"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "BLOCK_REASON_REQUIRED"
    r = post(c, f"/api/crews/{crew_id}/status", {"move": "blocked", "block_reason": "road_closed"})
    assert r.status_code == 200
    blocked = crew(c, crew_id)
    assert blocked.status is CrewStatus.BLOCKED and blocked.block_reason is not None
    assert blocked.actions == ["unblock"]
    r = post(c, f"/api/crews/{crew_id}/assignments", {"target_kind": "yard", "target_id": SANDHILL})
    assert r.status_code == 409
    assert post(c, f"/api/crews/{crew_id}/status", {"move": "unblock"}).status_code == 200
    cleared = crew(c, crew_id)
    assert cleared.status is CrewStatus.AVAILABLE and cleared.block_reason is None


def test_bad_targets_and_unknown_crews_are_refused(client: TestClient, session: Session) -> None:
    c = as_(client, session, "ops_dm_01")
    for body in (
        {"target_kind": "yard", "target_id": "STG-NOWHERE-YARD"},
        {"target_kind": "decision", "target_id": SANDHILL},
        {"target_kind": "decision", "target_id": "DC-D4-ETR-GLOBAL"},
    ):
        r = post(c, f"/api/crews/{CREWS[3]}/assignments", body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_DISPATCH_TARGET", body
    assert (
        post(
            c, "/api/crews/CRW-NOBODY-0000/status", {"move": "blocked", "block_reason": "road_closed"}
        ).status_code
        == 404
    )
    assert post(c, "/api/crews/..%2F..%2Fetc/status", {"move": "unblock"}).status_code in (404, 422)
    r = post(c, f"/api/crews/{CREWS[3]}/status", {"move": "teleport"})
    assert r.status_code == 422
