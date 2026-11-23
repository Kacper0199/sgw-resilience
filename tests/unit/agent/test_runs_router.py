from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from sgw.api import deps as api_deps
from sgw.api.errors import install_error_handlers
from sgw.api.routers import runs
from sgw.api.sessions import AuthUser
from sgw.contracts.api_models import contract_routes, missing_routes
from sgw.contracts.vocab import ApprovalFunction, Domain, RunMode
from sgw.contracts.wire import WireEvent, decode_stream

from .agent_testkit import DownLlm, deps


def _user(user_id: str) -> AuthUser:
    return AuthUser(
        user_id=user_id,
        display_name=user_id,
        function=ApprovalFunction.OPERATIONS,
        roles=("duty_manager",),
        regions=("SC-45003",),
        domains=(Domain.ELECTRIC,),
        step_up_at=None,
        session_hash="h" * 64,
        demo_switch=False,
    )


@pytest.fixture
async def app_and_user() -> AsyncIterator[tuple[FastAPI, dict[str, str]]]:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(runs.router)
    who = {"user": "ops_dm_01"}
    app.dependency_overrides[api_deps.current_user] = lambda: _user(who["user"])
    app.dependency_overrides[api_deps.writer] = lambda: _user(who["user"])
    app.dependency_overrides[api_deps.csrf_protect] = lambda: _user(who["user"])

    def factory(_: Request) -> Any:
        return deps(DownLlm())

    app.state.agent_runtime = runs.AgentRuntime(deps_factory=factory, epoch=7)
    app.router.add_api_route(
        runs.RESUME_ROUTE[1], runs.resume_run, methods=[runs.RESUME_ROUTE[0]], status_code=202
    )
    yield app, who


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def _start(client: httpx.AsyncClient, run_input: dict[str, Any] | None = None) -> tuple[str, str]:
    r = await client.post("/api/threads", json={"module": "decisions"})
    assert r.status_code == 201, r.text
    thread_id = r.json()["thread_id"]
    r = await client.post(
        f"/api/threads/{thread_id}/runs", json={"graph": "assess", "input": run_input or {"advisory": "N+1"}}
    )
    assert r.status_code == 202, r.text
    assert r.json()["events_url"] == f"/api/threads/{thread_id}/events"
    return thread_id, r.json()["run_id"]


async def test_run_streams_k4_frames_from_run_start_to_run_paused(app_and_user: Any) -> None:
    app, _ = app_and_user
    async with _client(app) as client:
        thread_id, run_id = await _start(client)
        r = await client.get(f"/api/threads/{thread_id}/events")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = decode_stream(r.text)
    assert frames[0][1].type is WireEvent.RUN_START and frames[-1][1].type is WireEvent.RUN_PAUSED
    assert all(i.stream == f"run:{run_id}" and i.epoch == 7 for i, _ in frames)
    assert [i.seq for i, _ in frames] == list(range(len(frames)))
    assert any(f.type is WireEvent.APPROVAL_REQUIRED for _, f in frames)


async def test_last_event_id_resumes_after_that_frame(app_and_user: Any) -> None:
    app, _ = app_and_user
    async with _client(app) as client:
        thread_id, run_id = await _start(client)
        full = decode_stream((await client.get(f"/api/threads/{thread_id}/events")).text)
        r = await client.get(
            f"/api/threads/{thread_id}/events", headers={"Last-Event-ID": f"run:{run_id}.7.4"}
        )
    tail = decode_stream(r.text)
    assert [i.seq for i, _ in tail] == [i.seq for i, _ in full][5:]


async def test_other_users_get_404_without_existence_leak(app_and_user: Any) -> None:
    app, who = app_and_user
    async with _client(app) as client:
        thread_id, run_id = await _start(client)
        who["user"] = "ops_dm_02"
        for r in (
            await client.get(f"/api/threads/{thread_id}/events"),
            await client.post(f"/api/threads/{thread_id}/runs", json={"graph": "assess", "input": {}}),
            await client.post(f"/api/threads/{thread_id}/runs/{run_id}/cancel"),
            await client.get("/api/threads/thr-nope/events"),
        ):
            assert r.status_code == 404
            assert r.json()["error"]["code"] == "THREAD_NOT_FOUND"


async def test_unbuilt_graph_is_refused(app_and_user: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    app, _ = app_and_user
    graphs = dict(runs.GRAPHS)
    graphs.pop("copilot", None)
    monkeypatch.setattr(runs, "GRAPHS", graphs)
    async with _client(app) as client:
        thread_id = (await client.post("/api/threads", json={"module": "ask"})).json()["thread_id"]
        r = await client.post(f"/api/threads/{thread_id}/runs", json={"graph": "copilot", "input": {}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "GRAPH_NOT_AVAILABLE"


async def test_forged_input_keys_are_dropped_and_audited(app_and_user: Any) -> None:
    app, _ = app_and_user
    async with _client(app) as client:
        thread_id, run_id = await _start(client, {"advisory": "N+1", "approved": True, "role": "command"})
        await client.get(f"/api/threads/{thread_id}/events")
    state = await app.state.agent_runtime.live[run_id].state()
    assert set(state["input"]) <= runs_input_keys()
    assert any(a.get("ignored_keys") == ["approved", "role"] for a in state["audit"])


def runs_input_keys() -> set[str]:
    from sgw.agent.nodes.spine import ALLOWED_INPUT

    return set(ALLOWED_INPUT)


async def test_cancel_returns_204(app_and_user: Any) -> None:
    app, _ = app_and_user
    async with _client(app) as client:
        thread_id, run_id = await _start(client)
        r = await client.post(f"/api/threads/{thread_id}/runs/{run_id}/cancel")
    assert r.status_code == 204


def test_routes_are_contract_routes() -> None:
    from fastapi.routing import APIRoute

    from sgw.api.routers import ask

    def served(router: Any) -> set[tuple[str, str]]:
        return {(m, r.path) for r in router.routes if isinstance(r, APIRoute) for m in r.methods or ()}

    assert served(runs.router) <= contract_routes() and served(ask.router) <= contract_routes()
    assert missing_routes(served(runs.router) | served(ask.router), prefixes=("/api/threads",)) == []


async def _settle(app: FastAPI, run_id: str) -> None:
    task = app.state.agent_runtime.live[run_id]
    async for _ in task.follow(-1):
        pass


async def test_resume_wakes_but_never_approves(app_and_user: Any) -> None:
    app, who = app_and_user
    async with _client(app) as client:
        thread_id, run_id = await _start(client)
        await _settle(app, run_id)
        store = app.state.agent_runtime.store
        assert (await store.run(run_id)).status == "paused"
        r = await client.post(f"/api/runs/{run_id}/resume", json={"approved": True})
        assert r.status_code == 202, r.text
        task = app.state.agent_runtime.live[run_id]
        await task._task
        assert task.frames[-1].type is WireEvent.RUN_PAUSED
        assert (await task.state())["status"] == "awaiting_approval"
        who["user"] = "ops_dm_02"
        assert (await client.post(f"/api/runs/{run_id}/resume")).status_code == 404


async def test_resume_needs_a_paused_run(app_and_user: Any) -> None:
    app, _ = app_and_user
    async with _client(app) as client:
        _, run_id = await _start(client)
        await _settle(app, run_id)
        await app.state.agent_runtime.store.set_status(run_id, "executed", False)
        r = await client.post(f"/api/runs/{run_id}/resume")
    assert r.status_code == 409 and r.json()["error"]["code"] == "RUN_NOT_PAUSED"


async def test_server_run_mode_wins_over_the_request(app_and_user: Any) -> None:
    from types import SimpleNamespace

    app, _ = app_and_user
    app.state.sgw = SimpleNamespace(clock=SimpleNamespace(view=SimpleNamespace(run_mode=RunMode.SHADOW)))
    async with _client(app) as client:
        thread_id = (await client.post("/api/threads", json={"module": "decisions"})).json()["thread_id"]
        r = await client.post(
            f"/api/threads/{thread_id}/runs", json={"graph": "assess", "input": {}, "run_mode": "live"}
        )
    run_id = r.json()["run_id"]
    assert (await app.state.agent_runtime.store.run(run_id)).run_mode == "shadow"
    assert app.state.agent_runtime.live[run_id].run_mode is RunMode.SHADOW


async def test_live_runs_are_bounded() -> None:
    runtime = runs.AgentRuntime(deps_factory=lambda _: deps(DownLlm()), max_live=2)
    for i in range(4):
        task = SimpleTask(f"run-{i}")
        runtime.keep(task)  # type: ignore[arg-type]
    assert list(runtime.live) == ["run-2", "run-3"]


class SimpleTask:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.status = "paused"


async def test_a_read_only_role_may_ask_but_not_start_another_graph() -> None:
    from dataclasses import replace

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(runs.router)
    auditor = replace(_user("audit_01"), roles=("auditor",), function=ApprovalFunction.AUDIT)
    assert auditor.read_only
    app.dependency_overrides[api_deps.current_user] = lambda: auditor
    app.dependency_overrides[api_deps.csrf_protect] = lambda: auditor
    app.state.agent_runtime = runs.AgentRuntime(deps_factory=lambda _: deps(DownLlm()), epoch=7)
    async with _client(app) as client:
        assert (await client.post("/api/threads", json={"module": "decisions"})).status_code == 403
        r = await client.post("/api/threads", json={"module": "ask"})
        assert r.status_code == 201, r.text
        thread_id = r.json()["thread_id"]
        r = await client.post(f"/api/threads/{thread_id}/runs", json={"graph": "assess", "input": {}})
        assert r.status_code == 403 and "READ_ONLY_ROLE" in r.text
        r = await client.post(
            f"/api/threads/{thread_id}/runs", json={"graph": "copilot", "input": {"question": "hi"}}
        )
        assert r.status_code == 202, r.text
