"""The report graphs are reachable through the K3 run routes, each with its own deps."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI, Request

from sgw.api import deps as api_deps
from sgw.api.errors import install_error_handlers
from sgw.api.routers import runs
from sgw.contracts.wire import WireEvent, decode_stream
from sgw.reports.nodes import ReportDeps

from ..agent_testkit import DownLlm
from ..agent_testkit import deps as spine_deps
from ..test_runs_router import _user
from . import reports_testkit as rk


def test_report_graphs_are_registered_with_report_deps() -> None:
    assert {"etr", "sitrep", "after_action"} <= set(runs.GRAPHS)
    assert {"etr", "sitrep", "after_action"} == runs.REPORT_GRAPHS


async def test_sitrep_run_through_the_router_uses_its_graph_deps() -> None:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(runs.router)
    app.dependency_overrides[api_deps.current_user] = lambda: _user("ops_dm_01")
    app.dependency_overrides[api_deps.writer] = lambda: _user("ops_dm_01")
    app.dependency_overrides[api_deps.csrf_protect] = lambda: _user("ops_dm_01")
    built: list[Any] = []

    def report_factory(_: Request) -> ReportDeps:
        d = rk.deps(DownLlm())
        built.append(d)
        return d

    app.state.agent_runtime = runs.AgentRuntime(
        deps_factory=lambda _: spine_deps(DownLlm()),
        graph_deps=dict.fromkeys(runs.REPORT_GRAPHS, report_factory),
        epoch=3,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        r = await client.post("/api/threads", json={"module": "decisions"})
        thread_id = r.json()["thread_id"]
        r = await client.post(f"/api/threads/{thread_id}/runs", json={"graph": "sitrep", "input": {}})
        assert r.status_code == 202, r.text
        r = await client.get(f"/api/threads/{thread_id}/events")
    frames = [f for _, f in decode_stream(r.text)]
    assert frames[0].type is WireEvent.RUN_START and frames[-1].type is WireEvent.RUN_END
    assert len(built) == 1 and isinstance(built[0], ReportDeps)
    drafts = [f for f in frames if f.type is WireEvent.ARTIFACT and f.payload.get("kind") == "sitrep_draft"]
    assert drafts and drafts[0].payload["tier"] == "T1"
