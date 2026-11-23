"""Over HTTP with the real app lifespan on a seeded scratch database: what each persona may do
(`getMyPermissions`, the same rules the write routes enforce), the notification feed with per-user read marks,
cancelling a stuck agent run, and the audit records of the wired actions."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from tests.unit.api.clock_testkit import pin_clock

from sgw.api.app import create_app
from sgw.api.deps import csrf_protect, current_user, writer
from sgw.api.routers import ops as ops_router
from sgw.api.routers.runs import AgentRuntime, agent_runtime
from sgw.api.sessions import AuthUser
from sgw.api.settings import ApiSettings
from sgw.approval import audit
from sgw.approval import testkit as tk
from sgw.contracts.api_models import NotificationFeed, Permissions, PipelineRunOut
from sgw.contracts.vocab import ApprovalFunction, Domain
from sgw.ops.control import load_actor

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
NOW = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)
CREW_PROPOSAL = "PRP-CREW-AIK-0926A"
PERSONAS: dict[str, tuple[str, ApprovalFunction]] = {
    "ic_01": ("incident_commander", ApprovalFunction.COMMAND),
    "ops_dm_01": ("duty_manager", ApprovalFunction.OPERATIONS),
    "plan_etr_01": ("etr_specialist", ApprovalFunction.PLANNING),
    "log_01": ("logistics_chief", ApprovalFunction.LOGISTICS),
    "wtr_lead_01": ("water_incident_lead", ApprovalFunction.WATER_OPERATIONS),
    "wtr_comp_01": ("water_compliance_officer", ApprovalFunction.COMPLIANCE),
    "exec_01": ("executive", ApprovalFunction.EXECUTIVE),
    "audit_01": ("auditor", ApprovalFunction.AUDIT),
    "admin_01": ("platform_admin", ApprovalFunction.PLATFORM),
    "ml_01": ("ml_data_owner", ApprovalFunction.DATA),
}


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: routes need Postgres
    with tk.seeded_database() as url:
        yield url


class Session:
    user_id = "ic_01"

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
    app.dependency_overrides[csrf_protect] = session.auth
    app.dependency_overrides[writer] = session.auth
    runtime = AgentRuntime(deps_factory=lambda _request: None)  # type: ignore[arg-type,return-value]
    app.dependency_overrides[agent_runtime] = lambda: runtime
    with TestClient(app) as c:
        yield c


def set_clock(client: TestClient, db_url: str, at: datetime) -> None:
    pin_clock(client, at)


@pytest.fixture(autouse=True)
def stopped_clock(client: TestClient, db_url: str) -> None:
    set_clock(client, db_url, NOW)


def as_(client: TestClient, session: Session, user_id: str) -> TestClient:
    session.user_id = user_id
    return client


def record(db_url: str, kind: str, actor: str, subject: str, payload: dict[str, Any]) -> int:
    with psycopg.connect(db_url, autocommit=True) as conn, conn.transaction():
        return audit.append(
            conn,
            kind=kind,
            actor_type="user",
            actor_id=actor,
            subject=subject,
            payload=payload,
            occurred_at=NOW,
        ).seq


def feed(c: TestClient) -> NotificationFeed:
    r = c.get("/api/notifications")
    assert r.status_code == 200, r.text
    return NotificationFeed.model_validate(r.json())


def kinds(f: NotificationFeed) -> list[str]:
    return [i.kind for i in f.items]


EXPECTED: dict[str, set[str]] = {
    "ic_01": {"stop_raise", "stop_restore", "mode_raise", "mode_lower"},
    "ops_dm_01": {"stop_raise", "mode_raise", "crew_dispatch"},
    "plan_etr_01": set(),
    "log_01": {"crew_dispatch"},
    "wtr_lead_01": {"stop_raise", "mode_raise"},
    "wtr_comp_01": {"stop_restore"},
    "exec_01": {"stop_raise", "mode_raise"},
    "audit_01": set(),
    "admin_01": {"mode_raise", "pipeline_run", "agent_run_cancel", "admin"},
    "ml_01": {"pipeline_run", "agent_run_cancel"},
}


@pytest.mark.parametrize("user_id", sorted(PERSONAS))
def test_permissions_per_persona(client: TestClient, session: Session, user_id: str) -> None:
    r = as_(client, session, user_id).get("/api/me/permissions")
    assert r.status_code == 200, r.text
    granted = {k for k, v in Permissions.model_validate(r.json()).model_dump().items() if v is True}
    assert granted == EXPECTED[user_id]


@pytest.mark.parametrize("user_id", sorted(PERSONAS))
def test_stop_permission_matches_the_kill_switch_rule(
    client: TestClient, session: Session, db_url: str, user_id: str
) -> None:
    body = as_(client, session, user_id).get("/api/me/permissions").json()
    with psycopg.connect(db_url) as conn:
        assert body["stop_raise"] is load_actor(conn, user_id).may_trigger


def test_waiting_decisions_reach_the_signing_functions_only(client: TestClient, session: Session) -> None:
    for user_id in ("ic_01", "log_01"):
        f = feed(as_(client, session, user_id))
        waiting = [i for i in f.items if i.kind == "decision_waiting"]
        assert [i.href for i in waiting] == [f"/decisions/{CREW_PROPOSAL}"], user_id
        assert waiting[0].notification_id.startswith(f"waiting:{CREW_PROPOSAL}:v")
        assert not waiting[0].read
    assert "decision_waiting" not in kinds(feed(as_(client, session, "ops_dm_01")))
    assert "decision_waiting" not in kinds(feed(as_(client, session, "wtr_comp_01")))


def test_deadline_within_two_hours(client: TestClient, session: Session, db_url: str) -> None:
    card = as_(client, session, "ic_01").get(f"/api/proposals/{CREW_PROPOSAL}").json()
    due = datetime.fromisoformat(card["effective_decide_by_utc"].replace("Z", "+00:00"))
    set_clock(client, db_url, due - timedelta(hours=3))
    assert "deadline_soon" not in kinds(feed(client))
    set_clock(client, db_url, due - timedelta(minutes=90))
    assert "deadline_soon" in kinds(feed(client))
    assert "deadline_soon" in kinds(feed(as_(client, session, "ops_dm_01")))
    assert "deadline_soon" not in kinds(feed(as_(client, session, "wtr_comp_01")))


def test_signature_crew_and_stop_events(client: TestClient, session: Session, db_url: str) -> None:
    record(
        db_url,
        "approval_recorded",
        "ic_01",
        CREW_PROPOSAL,
        {"decision": "approve", "function": "command", "approval_id": "APR-T1", "proposal_version": 1},
    )
    record(
        db_url,
        "crew_assignment_proposed",
        "ops_dm_01",
        "ASG-T1",
        {"crew_id": "CRW-EGRET-0207", "target_id": "DC-D2-CREWS-AIK", "required_function": "logistics"},
    )
    proposer = feed(as_(client, session, "ops_dm_01"))
    signed = [i for i in proposer.items if i.kind == "signature_recorded"]
    assert len(signed) == 1 and signed[0].title == "Command signed"
    assert "signature_recorded" not in kinds(feed(as_(client, session, "ic_01")))
    waiting = [i for i in feed(as_(client, session, "log_01")).items if i.kind == "crew_signature_waiting"]
    assert len(waiting) == 1 and waiting[0].href == "/crews?crew=CRW-EGRET-0207"

    record(
        db_url,
        "crew_assignment_signed",
        "log_01",
        "ASG-T1",
        {"crew_id": "CRW-EGRET-0207", "decision": "approve"},
    )
    assert "crew_signature_waiting" not in kinds(feed(as_(client, session, "log_01")))
    assert "crew_assignment_signed" in kinds(feed(as_(client, session, "ops_dm_01")))

    record(
        db_url,
        "kill_switch_triggered",
        "exec_01",
        "control:kill:K2",
        {"from": "K0", "to": "K2", "reason": "drill"},
    )
    stop = [i for i in feed(as_(client, session, "ml_01")).items if i.kind == "stop_level_changed"]
    assert len(stop) == 1 and stop[0].title == "Stop level: AI stopped" and stop[0].detail == "drill"
    assert "stop_level_changed" not in kinds(feed(as_(client, session, "exec_01")))


def test_voided_signature_reaches_the_signer(client: TestClient, session: Session, db_url: str) -> None:
    record(
        db_url,
        "approval_recorded",
        "log_01",
        CREW_PROPOSAL,
        {"decision": "approve", "function": "logistics", "approval_id": "APR-T2", "proposal_version": 1},
    )
    with psycopg.connect(db_url, autocommit=True) as conn, conn.transaction():
        audit.append(
            conn,
            kind="proposal_revised",
            actor_type="system",
            actor_id="system:clock-replanner",
            subject=CREW_PROPOSAL,
            payload={"voided_approval_ids": ["APR-T2"], "material": True},
            occurred_at=NOW,
        )
    voided = [i for i in feed(as_(client, session, "log_01")).items if i.kind == "signature_voided"]
    assert len(voided) == 1 and voided[0].title == "Your signature was voided by a re-plan"
    co_signer = feed(as_(client, session, "ic_01")).items
    assert [i.title for i in co_signer if i.kind == "signature_voided"] == [
        "Logistics signature was voided by a re-plan"
    ]
    assert "signature_recorded" not in kinds(feed(as_(client, session, "ic_01")))


def test_surges_reach_operations_not_compliance(client: TestClient, session: Session) -> None:
    surge = [i for i in feed(as_(client, session, "ops_dm_01")).items if i.kind == "surge_detected"]
    assert len(surge) == 1 and surge[0].title == "Outage surge in 5 counties" and surge[0].href == "/map"
    assert "surge_detected" not in kinds(feed(as_(client, session, "wtr_comp_01")))


def test_read_marks_are_per_user_and_survive_a_refresh(client: TestClient, session: Session) -> None:
    c = as_(client, session, "log_01")
    before = feed(c)
    assert before.unread == len(before.items) >= 2
    first = before.items[0].notification_id
    r = c.post("/api/notifications/read", json={"ids": [first, "made-up-id"]})
    assert r.status_code == 200
    after = NotificationFeed.model_validate(r.json())
    assert after.unread == before.unread - 1
    assert next(i for i in after.items if i.notification_id == first).read
    assert feed(as_(client, session, "ic_01")).items[0].read is False
    c = as_(client, session, "log_01")
    assert feed(c).unread == before.unread - 1
    assert (
        NotificationFeed.model_validate(c.post("/api/notifications/read", json={"all": True}).json()).unread
        == 0
    )
    assert feed(c).unread == 0


def test_read_only_auditor_may_clear_their_own_feed(client: TestClient, session: Session) -> None:
    c = as_(client, session, "audit_01")
    assert c.post("/api/notifications/read", json={"all": True}).status_code == 200


def add_run(db_url: str, run_id: str, status: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO agent_thread (thread_id, user_id, module) VALUES (%s, 'wtr_lead_01', 'water')"
            " ON CONFLICT DO NOTHING",
            (f"THR-{run_id}",),
        )
        conn.execute(
            "INSERT INTO agent_run (run_id, thread_id, user_id, graph, graph_version, run_mode, status)"
            " VALUES (%s, %s, 'wtr_lead_01', 'water_continuity', 'water_continuity@1', 'replay', %s)",
            (run_id, f"THR-{run_id}", status),
        )


def test_cancel_a_paused_run_is_audited(client: TestClient, session: Session, db_url: str) -> None:
    add_run(db_url, "RUN-CB2-PAUSED", "paused")
    body = {"reason": "waits for a sign-off nobody will give"}
    r = as_(client, session, "ops_dm_01").post("/api/runs/RUN-CB2-PAUSED/cancel", json=body)
    assert r.status_code == 403 and r.json()["error"]["code"] == "RUN_CANCEL_DENIED"
    r = as_(client, session, "ml_01").post("/api/runs/RUN-CB2-PAUSED/cancel", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled" and r.json()["ended_at"] is not None
    again = client.post("/api/runs/RUN-CB2-PAUSED/cancel", json=body)
    assert again.status_code == 409 and again.json()["error"]["code"] == "RUN_NOT_ACTIVE"
    assert client.post("/api/runs/RUN-NOPE/cancel", json=body).status_code == 404
    assert client.post("/api/runs/RUN-CB2-PAUSED/cancel", json={"reason": "x"}).status_code == 422
    with psycopg.connect(db_url) as conn:
        row = conn.execute(
            "SELECT actor_id, payload FROM audit_event WHERE kind = 'agent_run_cancelled'"
            " ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        assert row is not None and row[0] == "ml_01"
        assert row[1]["run_id"] == "RUN-CB2-PAUSED" and row[1]["from"] == "paused"
        assert audit.verify(conn).first_bad_seq is None


def test_pipeline_run_now_is_gated_and_audited(
    client: TestClient, session: Session, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = datetime(2026, 11, 21, 5, 0, tzinfo=UTC)
    fake = PipelineRunOut(
        run_id="PRUN-CB2",
        asset="ingest.feeds",
        status="success",
        started_at=started,
        finished_at=started,
        rows_in=3,
        rows_out=3,
        rows_quarantined=0,
        error=None,
    )
    monkeypatch.setattr(ops_router.ops_pipeline, "run_asset", lambda *a, **k: fake)
    for denied in ("wtr_comp_01", "ic_01", "ops_dm_01"):
        r = as_(client, session, denied).post("/api/pipeline/assets/ingest.feeds/run")
        assert r.status_code == 403 and r.json()["error"]["code"] == "PIPELINE_RUN_DENIED", denied
    r = as_(client, session, "ml_01").post("/api/pipeline/assets/ingest.feeds/run")
    assert r.status_code == 202, r.text
    with psycopg.connect(db_url) as conn:
        row = conn.execute(
            "SELECT actor_id, subject, payload FROM audit_event WHERE kind = 'pipeline_run_requested'"
            " ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        assert row is not None and row[0] == "ml_01" and row[1] == "pipeline:ingest.feeds"
        assert row[2]["run_id"] == "PRUN-CB2"
