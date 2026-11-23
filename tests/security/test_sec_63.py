"""SEC-63 (STM 8.3): when OPA is down, writes and restricted egress are denied. Three layers, each on its
own: the approval service fails closed when its OPA cannot answer, the gateway's egress gate fails closed for
any class, and the ops signal `opa_down` (probe or `FAULT_OPA_DOWN=1`) makes the database refuse approvals,
execution tokens and effects until OPA has answered healthy three times."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx
import psycopg
import pytest
from services.llm_gateway.egress import EgressInput, EgressUnavailableError, OpaEgress

from sgw.approval import testkit as atk
from sgw.approval.errors import ApprovalError, ForbiddenError
from sgw.approval.policy import OpaPolicy, ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.contracts import golden
from sgw.contracts.vocab import DegradedMode
from sgw.ops import testkit as tk
from sgw.ops.levels import Capability
from sgw.ops.probes import OpaProbe

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
DEAD_OPA = "http://127.0.0.1:9"
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


def _approvals(policy: Any = None) -> ApprovalService:
    clock = atk.MutableClock(golden.ADVISORY_N.issued + timedelta(minutes=10))
    return ApprovalService(policy or ReferencePolicy(), scenario_clock=clock, token_clock=clock)


def test_approval_service_fails_closed_when_opa_is_unreachable(conn: Conn) -> None:
    card = atk.new_crew_proposal(conn, _approvals())
    dead = _approvals(OpaPolicy(DEAD_OPA, timeout_s=0.5))
    with pytest.raises(ApprovalError):
        dead.decide(conn, user_id="ic_01", proposal_id=card.proposal_id, request=atk.approve_req(card))
    count = conn.execute(
        "SELECT count(*) FROM approval WHERE proposal_id = %s", (card.proposal_id,)
    ).fetchone()
    assert count == (0,)


@pytest.mark.parametrize("classes", [(), ("C0",), ("C1",), ("C3",)])
def test_gateway_egress_fails_closed_when_opa_is_unreachable(classes: tuple[str, ...]) -> None:
    async def decide() -> None:
        pdp = OpaEgress(DEAD_OPA, timeout_s=0.5)
        try:
            await pdp.decide(
                EgressInput(route="R1", node="sitrep.draft", model="m", classes=classes, node_rule=None)
            )
        finally:
            await pdp.aclose()

    with pytest.raises(EgressUnavailableError):
        asyncio.run(decide())


def test_opa_down_signal_makes_the_database_refuse_writes(conn: Conn) -> None:
    approvals = _approvals()
    card = atk.new_crew_proposal(conn, approvals)
    approvals.decide(conn, user_id="ic_01", proposal_id=card.proposal_id, request=atk.approve_req(card))
    svc = tk.service({"FAULT_OPA_DOWN": "1"})
    report = svc.reconcile(conn)
    assert report.active == ("opa_down",) and report.after is DegradedMode.M1
    assert not svc.capabilities(conn)[Capability.APPROVE_AND_EXECUTE]
    with pytest.raises(ForbiddenError):
        approvals.decide(conn, user_id="log_01", proposal_id=card.proposal_id, request=atk.approve_req(card))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "INSERT INTO effect (effect_id, proposal_id, channel)"
            " VALUES ('EFF-FORGED', %s, 'work_management')",
            (card.proposal_id,),
        )
    svc.env = {}
    assert svc.reconcile(conn).after is DegradedMode.M0
    done = approvals.decide(
        conn, user_id="log_01", proposal_id=card.proposal_id, request=atk.approve_req(card)
    )
    assert done.value.proposal_state.value == "approved"


def test_opa_probe_raises_and_clears_the_signal_with_hysteresis(conn: Conn) -> None:
    healthy = {"up": False}

    def opa(request: httpx.Request) -> httpx.Response:
        if not healthy["up"]:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={})

    probe = OpaProbe("http://opa.test", httpx.Client(transport=httpx.MockTransport(opa)))
    svc = tk.service()
    states = [svc.reconcile(conn, probe.read()).active for _ in range(2)]
    assert states == [(), ("opa_down",)]
    healthy["up"] = True
    states = [svc.reconcile(conn, probe.read()).active for _ in range(3)]
    assert states == [("opa_down",), ("opa_down",), ()]
