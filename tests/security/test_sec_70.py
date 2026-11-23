"""SEC-70 (STM 9.1): each kill level K1-K4 removes its capabilities within the prototype target (new writes
blocked in under 1 s). K1: no approvals, tokens or effects; pending approvals and unburned tokens void.
K2: K1 plus agent runs stopped and refused, LLM calls off (M2). K3: K2 plus ingestion and new proposals
refused (M3). K4: everything off (M4). The database enforces each, whatever the API does."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from sgw.approval import testkit as atk
from sgw.approval.errors import ApprovalError, ForbiddenError
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.contracts import golden
from sgw.contracts.vocab import DegradedMode, KillLevel
from sgw.ops import testkit as tk
from sgw.ops.levels import Capability

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
TARGET_S = 1.0
Conn = psycopg.Connection[Any]


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with tk.ops_database() as url:
        yield url


@pytest.fixture
def conn(db_url: str) -> Iterator[Conn]:
    tk.reset_control(db_url)
    with psycopg.connect(db_url, autocommit=True) as c:
        yield c


def _approvals() -> ApprovalService:
    clock = atk.MutableClock(golden.ADVISORY_N.issued + timedelta(minutes=10))
    return ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=clock)


def _agent_run(conn: Conn, status: str = "running") -> str:
    run_id = f"RUN-OSPREY-{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT INTO agent_run (run_id, thread_id, user_id, graph, graph_version, run_mode, status)"
        " VALUES (%s, 'THR-OSPREY', 'ops_dm_01', 'copilot', 'v1', 'replay', %s)",
        (run_id, status),
    )
    return run_id


def _ingest_job(conn: Conn) -> None:
    conn.execute(
        'INSERT INTO job (kind, payload) VALUES (\'ledger.append\', \'{"origin": "ingest:oms", "ord": 0}\')'
    )


def _pull(conn: Conn, level: KillLevel) -> float:
    started = time.perf_counter()
    tk.service().set_kill(conn, user_id="ic_01", level=level, reason=f"drill {level.value}")
    return started


def test_k1_freezes_actions_and_voids_pending_approvals_and_tokens(conn: Conn) -> None:
    approvals = _approvals()
    pending = atk.new_crew_proposal(conn, approvals)
    approvals.decide(conn, user_id="ic_01", proposal_id=pending.proposal_id, request=atk.approve_req(pending))
    ready = atk.new_crew_proposal(conn, approvals, sandhill=10)
    for user in ("ic_01", "log_01"):
        approvals.decide(conn, user_id=user, proposal_id=ready.proposal_id, request=atk.approve_req(ready))
    token = atk.repo_token(conn, ready.proposal_id)
    assert token is not None
    started = _pull(conn, KillLevel.K1)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE execution_token SET burned_at = now() WHERE token_id = %s", (token["token_id"],))
    assert time.perf_counter() - started < TARGET_S
    with pytest.raises(ApprovalError):
        approvals.burn(
            conn,
            token_id=token["token_id"],
            proposal_id=ready.proposal_id,
            proposal_version=ready.proposal_version,
            action_hash=ready.action_hash,
        )
    with pytest.raises(ForbiddenError):
        approvals.decide(
            conn, user_id="log_01", proposal_id=pending.proposal_id, request=atk.approve_req(pending)
        )
    live = conn.execute(
        "SELECT count(*) FROM approval WHERE proposal_id = ANY(%s) AND voided_at IS NULL",
        ([pending.proposal_id, ready.proposal_id],),
    ).fetchone()
    assert live == (0,)
    voided = conn.execute(
        "SELECT 1 FROM ops_voided_token WHERE token_id = %s", (token["token_id"],)
    ).fetchone()
    assert voided is not None
    caps = tk.service().capabilities(conn)
    assert not caps[Capability.APPROVE_AND_EXECUTE]
    assert (
        caps[Capability.VIEW_DASHBOARDS] and caps[Capability.AGENT_RUNS] and caps[Capability.CREATE_PROPOSALS]
    )
    _agent_run(conn)
    atk.new_crew_proposal(conn, approvals, sandhill=9)


def test_voided_token_stays_dead_after_restore(conn: Conn) -> None:
    approvals = _approvals()
    card = atk.new_crew_proposal(conn, approvals, sandhill=7)
    for user in ("ic_01", "log_01"):
        approvals.decide(conn, user_id=user, proposal_id=card.proposal_id, request=atk.approve_req(card))
    token = atk.repo_token(conn, card.proposal_id)
    assert token is not None
    svc = tk.service()
    svc.set_kill(conn, user_id="exec_01", level=KillLevel.K1, reason="approval anomaly")
    svc.set_kill(conn, user_id="ic_01", level=KillLevel.K0, reason="anomaly explained, chain verified")
    svc.set_kill(conn, user_id="wtr_comp_01", level=KillLevel.K0, reason="anomaly explained, chain verified")
    with pytest.raises(ApprovalError):
        approvals.burn(
            conn,
            token_id=token["token_id"],
            proposal_id=card.proposal_id,
            proposal_version=card.proposal_version,
            action_hash=card.action_hash,
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE execution_token SET burned_at = now() WHERE token_id = %s", (token["token_id"],))


def test_k2_stops_agent_runs_and_closes_llm(conn: Conn) -> None:
    running, paused, done = _agent_run(conn), _agent_run(conn, "paused"), _agent_run(conn, "done")
    started = _pull(conn, KillLevel.K2)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _agent_run(conn)
    assert time.perf_counter() - started < TARGET_S
    states = dict(
        conn.execute(
            "SELECT run_id, status FROM agent_run WHERE run_id = ANY(%s)", ([running, paused, done],)
        ).fetchall()
    )
    assert states == {running: "cancelled", paused: "cancelled", done: "done"}
    svc = tk.service()
    assert svc.state(conn).degraded_mode is DegradedMode.M2
    caps = svc.capabilities(conn)
    assert not caps[Capability.LLM_CALLS] and not caps[Capability.AGENT_RUNS]
    assert caps[Capability.VIEW_DASHBOARDS] and caps[Capability.INGEST_EXTERNAL]
    _ingest_job(conn)


def test_k3_isolates_ingestion_and_new_proposals(db_url: str, conn: Conn) -> None:
    approvals = _approvals()
    started = _pull(conn, KillLevel.K3)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _ingest_job(conn)
    assert time.perf_counter() - started < TARGET_S
    with pytest.raises(ForbiddenError):
        atk.new_crew_proposal(conn, approvals, sandhill=5)
    conn.execute(
        'INSERT INTO job (kind, payload) VALUES (\'ledger.append\', \'{"origin": "ops", "ord": 0}\')'
    )
    assert tk.service().state(conn).degraded_mode is DegradedMode.M3
    with tk.client_for(db_url, tk.service()) as client:
        refused = client.post("/api/pipeline/assets/observations/run", headers=tk.h("ml_01"))
        assert refused.status_code == 403 and refused.json()["error"]["code"] == "PIPELINE_RUNS_PAUSED"
        assert client.get("/api/feeds/health", headers=tk.h("ml_01")).status_code == 200


def test_k4_turns_everything_off(conn: Conn) -> None:
    _pull(conn, KillLevel.K4)
    svc = tk.service()
    assert svc.state(conn).degraded_mode is DegradedMode.M4
    assert not any(svc.capabilities(conn).values())
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _agent_run(conn)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _ingest_job(conn)


def test_every_level_change_is_in_the_audit_chain(conn: Conn) -> None:
    seq0 = tk.audit_head(conn)
    svc = tk.service()
    for level in (KillLevel.K1, KillLevel.K2, KillLevel.K3, KillLevel.K4):
        svc.set_kill(conn, user_id="ops_dm_01", level=level, reason=f"escalate to {level.value}")
    rows = conn.execute(
        "SELECT payload->>'from', payload->>'to' FROM audit_event WHERE kind = 'kill_switch_triggered'"
        " AND seq > %s ORDER BY seq",
        (seq0,),
    ).fetchall()
    assert rows == [("K0", "K1"), ("K1", "K2"), ("K2", "K3"), ("K3", "K4")]
