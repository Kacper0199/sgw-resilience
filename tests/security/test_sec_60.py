"""SEC-60 (STM 8.2/8.3, PLAN SC-7): when the LLM is down the platform enters M2 (deterministic only), and
dashboards and the manual approval workflow keep working. `FAULT_LLM_DOWN=1` is the drill; a gateway whose
circuit breaker is open is the real trigger. Leaving M2 needs the flag cleared and sustained health."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx
import psycopg
import pytest

from sgw.approval import testkit as atk
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.contracts import golden
from sgw.contracts.vocab import DegradedMode, ProposalState
from sgw.ops import testkit as tk
from sgw.ops.levels import Capability
from sgw.ops.probes import GatewayProbe
from sgw.ops.reconciler import reconcile_once

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
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


def test_fault_llm_down_sets_m2_and_removes_only_llm_work(conn: Conn) -> None:
    svc = tk.service({"FAULT_LLM_DOWN": "1"})
    seq0 = tk.audit_head(conn)
    report = svc.reconcile(conn)
    assert report.before is DegradedMode.M0 and report.after is DegradedMode.M2
    assert svc.state(conn).degraded_mode is DegradedMode.M2
    caps = svc.capabilities(conn)
    assert not caps[Capability.LLM_CALLS] and not caps[Capability.FREE_FORM_PLANS]
    for kept in (Capability.VIEW_DASHBOARDS, Capability.MANUAL_WORKFLOW, Capability.APPROVE_AND_EXECUTE):
        assert caps[kept], kept
    assert tk.audit_kinds(conn, seq0) == ["ops_signal_raised", "degraded_mode_changed"]
    svc.env = {}
    assert svc.reconcile(conn).after is DegradedMode.M0


def test_dashboards_and_manual_workflow_work_in_m2(db_url: str, conn: Conn) -> None:
    svc = tk.service({"FAULT_LLM_DOWN": "1"})
    svc.reconcile(conn)
    with tk.client_for(db_url, svc) as client:
        for path in (
            "/api/feeds/health",
            "/api/pipeline/runs",
            "/api/dq/checks",
            "/api/models",
            "/api/pipeline/assets",
            "/api/control/mode",
        ):
            assert client.get(path, headers=tk.h("ops_dm_01")).status_code == 200, path
        assert client.get("/api/control/mode", headers=tk.h("ops_dm_01")).json()["degraded_mode"] == "M2"
    clock = atk.MutableClock(golden.ADVISORY_N.issued + timedelta(minutes=10))
    approvals = ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=clock)
    card = atk.new_crew_proposal(conn, approvals)
    assert "degraded_mode" in card.escalators
    approvals.decide(conn, user_id="ic_01", proposal_id=card.proposal_id, request=atk.approve_req(card))
    done = approvals.decide(
        conn, user_id="log_01", proposal_id=card.proposal_id, request=atk.approve_req(card)
    )
    assert done.value.proposal_state is ProposalState.APPROVED
    token = atk.repo_token(conn, card.proposal_id)
    assert token is not None
    effect = approvals.burn(
        conn,
        token_id=token["token_id"],
        proposal_id=card.proposal_id,
        proposal_version=card.proposal_version,
        action_hash=card.action_hash,
    )
    assert effect == f"EFF-{card.proposal_id}"


def test_open_gateway_breaker_enters_m2_and_recovery_needs_sustained_health(conn: Conn) -> None:
    breaker = {"state": "open"}

    def gateway(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"breaker": breaker, "budget": {"level": "ok"}})

    svc = tk.service({"SGW_OPS_GATEWAY_URL": "http://gateway.test"})
    probe = GatewayProbe("http://gateway.test", httpx.Client(transport=httpx.MockTransport(gateway)))

    def tick() -> DegradedMode:
        return svc.reconcile(conn, probe.read()).after

    assert tick() is DegradedMode.M0
    assert tick() is DegradedMode.M2
    breaker["state"] = "closed"
    assert [tick() for _ in range(3)] == [DegradedMode.M2, DegradedMode.M2, DegradedMode.M0]


def test_unreachable_gateway_counts_as_down(conn: Conn) -> None:
    svc = tk.service({"SGW_OPS_GATEWAY_URL": "http://127.0.0.1:9"})
    reconcile_once(conn, svc)
    assert reconcile_once(conn, svc).after is DegradedMode.M2


def test_api_process_with_fault_llm_down_enters_m2(db_url: str, conn: Conn) -> None:
    """The real wiring: the router lifespan starts the reconciler when FAULT_LLM_DOWN=1 is in the API's env.
    `close_fds=False` lets CPython spawn the child with posix_spawn: on macOS a forked child of a process that
    has loaded numpy (Accelerate) can crash before exec."""
    script = (
        "import time, psycopg\n"
        "from fastapi import FastAPI\n"
        "from fastapi.testclient import TestClient\n"
        "from sgw.api.routers.ops import router\n"
        "app = FastAPI(); app.include_router(router)\n"
        "with TestClient(app):\n"
        "    with psycopg.connect(DSN, autocommit=True) as c:\n"
        "        for _ in range(100):\n"
        "            row = c.execute('SELECT degraded_mode FROM control_state WHERE id = 1').fetchone()\n"
        "            mode = row[0] if row else None\n"
        "            if mode == 'M2':\n"
        "                break\n"
        "            time.sleep(0.1)\n"
        "print(mode, flush=True)\n"
    ).replace("DSN", repr(db_url))
    env = {**os.environ, "FAULT_LLM_DOWN": "1", "SGW_DATABASE_URL": db_url, "SGW_OPS_RECONCILE_S": "0.5"}
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        close_fds=False,
    )
    assert out.stdout.strip().splitlines()[-1:] == ["M2"], (
        out.returncode,
        out.stdout[-500:],
        out.stderr[-2000:],
    )
    kinds = tk.audit_kinds(conn)
    assert "degraded_mode_changed" in kinds


GATEWAY_HEADERS = {
    "x-api-key": "sgw-test-caller-cli",
    "anthropic-version": "2023-06-01",
    "x-sgw-node": "test.narrate",
    "x-sgw-run": "run-sec60",
    "x-sgw-purpose": "test",
    "x-sgw-wave": "W4",
    "x-sgw-classes": "C1",
}
GATEWAY_BODY = {
    "model": "claude-sonnet-5-5",
    "max_tokens": 256,
    "output_config": {"effort": "medium"},
    "system": [{"type": "text", "text": "You brief a utility duty manager."}],
    "messages": [{"role": "user", "content": "Summarise feeder PS-17 status."}],
}
SLOTS = {"feeder": "PS-17", "customers_out": 1840, "etr_p50": "18:40"}


def _template(slots: dict[str, Any]) -> str:
    return f"{slots['feeder']}: {slots['customers_out']} customers out, ETR P50 {slots['etr_p50']}."


def test_end_to_end_fault_llm_down_gateway_refuses_and_node_takes_the_template_path(
    db_url: str, conn: Conn, tmp_path: Any
) -> None:
    from fastapi.testclient import TestClient
    from services.llm_gateway.api import create_app
    from services.llm_gateway.calls import MemorySink
    from services.llm_gateway.config import Mode, Settings

    from sgw.ops.gate import LlmDisabledError, is_llm_disabled, llm_gate, run_llm_node

    settings = Settings(
        accept_test_tokens=True,
        mode=Mode.REPLAY,
        fixture_dir=tmp_path / "fixtures",
        spend_csv=tmp_path / "llm_spend.csv",
        llm_call_dsn=db_url,
    )
    sink = MemorySink()
    gateway = TestClient(create_app(settings, sink=sink))

    def call() -> str:
        response = gateway.post("/v1/messages", json=GATEWAY_BODY, headers=GATEWAY_HEADERS)
        if is_llm_disabled(response.status_code, response.json()):
            raise LlmDisabledError(response.json()["error"]["message"])
        return "llm narrative"

    svc = tk.service({"FAULT_LLM_DOWN": "1"})
    assert svc.reconcile(conn).after is DegradedMode.M2
    refused = gateway.post("/v1/messages", json=GATEWAY_BODY, headers=GATEWAY_HEADERS)
    assert refused.status_code == 503, refused.text
    assert refused.json()["error"]["type"] == "sgw_llm_disabled"
    assert sink.records and sink.records[-1].decision == "deny"
    gate = llm_gate(conn)
    assert not gate.allowed and gate.degraded_mode is DegradedMode.M2
    text, path = run_llm_node(gate, call=call, template=lambda: _template(SLOTS))
    assert path == "template" and text == "PS-17: 1840 customers out, ETR P50 18:40."
    opened = type(gate)(True, "checked before the outage", gate.kill_level, gate.degraded_mode)
    assert run_llm_node(opened, call=call, template=lambda: _template(SLOTS))[1] == "template"
    svc.env = {}
    assert svc.reconcile(conn).after is DegradedMode.M0
    time.sleep(1.1)
    assert llm_gate(conn).allowed
    after = gateway.post("/v1/messages", json=GATEWAY_BODY, headers=GATEWAY_HEADERS)
    assert after.status_code != 503


async def _spine_run(llm: Any, gate: Any) -> dict[str, Any]:
    from tests.unit.agent.agent_testkit import run_task

    task = run_task(llm, llm_gate=gate, run_id="run-sec60-spine")
    await task.run()
    return dict(await task.state())


async def test_spine_never_calls_the_model_in_m2_and_shows_the_template_slots(
    db_url: str, conn: Conn
) -> None:
    from tests.unit.agent.agent_testkit import DownLlm

    from sgw.agent.nodes.gate import LLM_DISABLED, db_gate

    gate = db_gate(lambda: psycopg.connect(db_url, autocommit=True))
    svc = tk.service({"FAULT_LLM_DOWN": "1"})
    assert svc.reconcile(conn).after is DegradedMode.M2
    gated_llm = DownLlm()
    closed = await _spine_run(gated_llm, gate)
    assert gated_llm.calls == 0
    for key in ("narrative", "rationale"):
        assert closed[key]["path"] == "m2" and closed[key]["reason"] == LLM_DISABLED, closed[key]
    assert closed["status"] == "awaiting_approval" and closed["approval"]["proposal_id"]
    svc.env = {}
    assert svc.reconcile(conn).after is DegradedMode.M0
    time.sleep(1.1)
    open_llm = DownLlm()
    reopened = await _spine_run(open_llm, gate)
    assert open_llm.calls == 2
    for key in ("narrative", "rationale"):
        assert reopened[key]["reason"] == "gateway_unreachable"
        assert reopened[key]["rendered"] == closed[key]["rendered"]
        assert reopened[key]["slots_shown"] == closed[key]["slots_shown"]


async def test_spine_maps_the_gateway_refusal_to_the_template_path() -> None:
    from tests.unit.agent.agent_testkit import ScriptedLlm

    from sgw.agent.nodes.gate import LLM_DISABLED
    from sgw.agent.nodes.llm import LlmUnavailable
    from sgw.contracts.vocab import KillLevel
    from sgw.ops.gate import LLM_DISABLED_CODE, LlmGate

    refusal = LlmUnavailable("gateway_503", LLM_DISABLED_CODE)
    llm = ScriptedLlm({"narrate": refusal, "draft_rationale": refusal})
    state = await _spine_run(llm, lambda: LlmGate(True, "ok", KillLevel.K0, DegradedMode.M0))
    for key in ("narrative", "rationale"):
        assert state[key]["path"] == "m2" and state[key]["reason"] == LLM_DISABLED, state[key]
