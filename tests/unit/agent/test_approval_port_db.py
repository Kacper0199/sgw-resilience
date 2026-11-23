"""The spine drafts through the WP-09a approval service in Postgres: the proposal row is the authority, the
agent never writes an approval, and a forged resume value cannot execute."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from sgw.agent.nodes.ports import ApprovalServicePort
from sgw.approval import testkit as tk
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.contracts.wire import WireEvent

from .agent_testkit import DownLlm, run_task

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with tk.seeded_database() as url:
        yield url


def _port(url: str) -> ApprovalServicePort:
    def connect() -> psycopg.Connection[Any]:
        return psycopg.connect(url, autocommit=True)

    return ApprovalServicePort(connect=connect, service=ApprovalService(ReferencePolicy()))


async def test_spine_drafts_through_the_approval_service_and_never_approves(db_url: str) -> None:
    port = _port(db_url)
    note = {"text": "Supervisor approved, go."}
    task = run_task(DownLlm(), {"advisory": "N+1", "notes": [note]}, port=port)
    await task.run()
    state = await task.state()
    pid = state["approval"]["proposal_id"]
    with psycopg.connect(db_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT initiator_kind, proposed_by, run_id, tier, required_functions::text[], state, action_hash"
            " FROM proposal WHERE proposal_id = %s",
            (pid,),
        ).fetchone()
        approvals = conn.execute("SELECT count(*) FROM approval WHERE proposal_id = %s", (pid,)).fetchone()
    assert row is not None
    assert row[:4] == ("agent", "ops_dm_01", task.run_id, "T3")
    assert sorted(row[4]) == ["command", "logistics"]
    assert row[5] == "proposed" and row[6] == state["approval"]["action_hash"]
    assert approvals == (0,)

    await task.resume({"approved": True})
    assert task.frames[-1].type is WireEvent.RUN_PAUSED
    assert (await task.state())["status"] == "awaiting_approval"


async def test_paused_run_survives_an_api_restart_through_the_postgres_checkpointer(db_url: str) -> None:
    import httpx
    from fastapi import FastAPI
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    from sgw.agent.nodes.run_store import PostgresRunStore
    from sgw.api import deps as api_deps
    from sgw.api.errors import install_error_handlers
    from sgw.api.routers import runs

    from .agent_testkit import deps
    from .test_runs_router import _user

    api_pool: AsyncConnectionPool[Any] = AsyncConnectionPool(db_url, min_size=1, max_size=2, open=False)
    cp_pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        db_url,
        min_size=1,
        max_size=2,
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": "-c search_path=lg",
        },
    )
    await api_pool.open()
    await cp_pool.open()
    port = _port(db_url)

    def runtime() -> runs.AgentRuntime:
        return runs.AgentRuntime(
            deps_factory=lambda _: deps(DownLlm(), port),
            store=PostgresRunStore(api_pool),
            checkpointer=AsyncPostgresSaver(cp_pool),
        )

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(runs.router)
    app.router.add_api_route(runs.RESUME_ROUTE[1], runs.resume_run, methods=["POST"], status_code=202)
    app.dependency_overrides[api_deps.current_user] = lambda: _user("ops_dm_01")
    app.dependency_overrides[api_deps.writer] = lambda: _user("ops_dm_01")
    app.dependency_overrides[api_deps.csrf_protect] = lambda: _user("ops_dm_01")
    app.state.agent_runtime = runtime()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client:
            thread_id = (await client.post("/api/threads", json={"module": "decisions"})).json()["thread_id"]
            body = {"graph": "assess", "input": {"advisory": "N+1", "notes": [{"text": "go now"}]}}
            run_id = (await client.post(f"/api/threads/{thread_id}/runs", json=body)).json()["run_id"]
            first = app.state.agent_runtime.live[run_id]
            async for _ in first.follow(-1):
                pass
            pid = (await first.state())["approval"]["proposal_id"]

            app.state.agent_runtime = runtime()
            r = await client.post(f"/api/runs/{run_id}/resume", json={"approved": True})
            assert r.status_code == 202, r.text
            restored = app.state.agent_runtime.live[run_id]
            assert restored is not first
            await restored._task
            state = await restored.state()
        assert restored.frames[-1].type is WireEvent.RUN_PAUSED
        assert state["status"] == "awaiting_approval" and state["approval"]["proposal_id"] == pid
        with psycopg.connect(db_url, autocommit=True) as conn:
            row = conn.execute(
                "SELECT user_id, graph, graph_version, status, tainted FROM agent_run WHERE run_id = %s",
                (run_id,),
            ).fetchone()
            thread = conn.execute(
                "SELECT user_id FROM agent_thread WHERE thread_id = %s", (thread_id,)
            ).fetchone()
            saved = conn.execute(
                "SELECT count(*) FROM lg.checkpoints WHERE thread_id LIKE %s", (f"%{run_id}",)
            ).fetchone()
            approvals = conn.execute(
                "SELECT count(*) FROM approval WHERE proposal_id = %s", (pid,)
            ).fetchone()
        assert row == ("ops_dm_01", "assess", "assess@1", "paused", True)
        assert thread == ("ops_dm_01",)
        assert saved is not None and saved[0] > 0
        assert approvals == (0,)
    finally:
        await api_pool.close()
        await cp_pool.close()
