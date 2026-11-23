"""K3/K4 agent run routes: create a thread, start a graph run (202), stream its K4 run frames as SSE, cancel,
and wake a paused run.

A run executes in the API process as a `RunTask`. Thread and run rows live in Postgres (migration 3500) and
the graph state in the LangGraph Postgres checkpointer, so a paused run survives an API restart; run frames
stay in memory for the most recent runs only (`MAX_LIVE_RUNS`), and a client reconnecting with
`Last-Event-ID: run:<run_id>.<epoch>.<seq>` gets the frames after that seq. Threads and runs belong to the
user who created them (others get 404, no existence leak). The user's identity and function come from the
session and the run mode from the server's scenario state; the `run_mode` in the request body is ignored
when the server has one. Graph input keys outside the graph's schema are dropped by the graph and audited.

`resume` is a wake-up only: the approval store decides whether the run executes (the graph asks it). It is
mounted when the K3 contract lists `POST /api/runs/{run_id}/resume`.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from sgw.agent.copilot import graph as copilot
from sgw.agent.graphs import after_action, assess, etr, sitrep, water
from sgw.agent.nodes.gate import db_gate
from sgw.agent.nodes.llm import GatewayClient
from sgw.agent.nodes.ports import ApprovalServicePort, ProposalPort
from sgw.agent.nodes.run_store import MemoryRunStore, PostgresRunStore, RunRow, RunStore, ThreadRow
from sgw.agent.nodes.run_task import RunTask
from sgw.agent.nodes.spine import SpineDeps
from sgw.api.deps import CurrentUser, SessionWrite, Writer
from sgw.api.errors import Conflict, Forbidden, NotFound, Unavailable
from sgw.api.sessions import AuthUser
from sgw.common import dbconnect
from sgw.common.app_scope import on_close
from sgw.contracts.api_models import RunAccepted, RunCreate, Thread, ThreadCreate, contract_routes
from sgw.contracts.vocab import Module, RunMode
from sgw.contracts.wire import SseId, encode_frame
from sgw.models.clocks.advisory import TWIN_TABLE

router = APIRouter(tags=["agent"])

GRAPHS: dict[str, Callable[[BaseCheckpointSaver[Any] | None], Any]] = {
    assess.GRAPH_ID: assess.build,
    water.GRAPH_ID: water.build,
    etr.GRAPH_ID: etr.build,
    sitrep.GRAPH_ID: sitrep.build,
    after_action.GRAPH_ID: after_action.build,
    copilot.GRAPH_ID: copilot.build,
}
REPORT_GRAPHS = frozenset({etr.GRAPH_ID, sitrep.GRAPH_ID, after_action.GRAPH_ID})
MEMBER_TABLE_ENV = "SGW_PS17_MEMBER_TABLE"
DEFAULT_MEMBER_TABLE = TWIN_TABLE
SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
HEARTBEAT_S = 10.0
MAX_LIVE_RUNS = 64
EPOCH = int(time.time())
RESUME_ROUTE = ("POST", "/api/runs/{run_id}/resume")


@dataclass
class AgentRuntime:
    """What runs need besides the request: built once per app (tests inject their own)."""

    deps_factory: Callable[[Request], SpineDeps]
    graph_deps: dict[str, Callable[[Request], SpineDeps]] = field(default_factory=dict)
    store: RunStore = field(default_factory=MemoryRunStore)
    checkpointer: BaseCheckpointSaver[Any] = field(default_factory=InMemorySaver)
    live: OrderedDict[str, RunTask] = field(default_factory=OrderedDict)
    epoch: int = EPOCH
    max_live: int = MAX_LIVE_RUNS

    def keep(self, task: RunTask) -> None:
        self.live[task.run_id] = task
        self.live.move_to_end(task.run_id)
        while len(self.live) > self.max_live:
            oldest = next((k for k, t in self.live.items() if t.status not in ("created", "running")), None)
            if oldest is None:
                break
            del self.live[oldest]


def _member_table() -> dict[str, Any]:
    path = Path(os.environ.get(MEMBER_TABLE_ENV, str(DEFAULT_MEMBER_TABLE)))
    if not path.is_file():
        raise Unavailable("the PS-17 member table is not available", code="EVIDENCE_UNAVAILABLE")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def default_deps(request: Request) -> SpineDeps:
    from sgw.approval.deps import approval_service

    settings = request.app.state.sgw.settings
    service = approval_service(request)

    def connect() -> psycopg.Connection[Any]:
        return dbconnect.connect(settings.database_url, autocommit=True)

    port: ProposalPort = ApprovalServicePort(connect=connect, service=service)
    return SpineDeps(
        llm=GatewayClient(), proposals=port, member_table=_member_table(), llm_gate=db_gate(connect)
    )


def _scenario_now(request: Request) -> datetime:
    clock = getattr(getattr(request.app.state, "sgw", None), "clock", None)
    now = getattr(clock, "now", None)
    value = now() if callable(now) else None
    return value if isinstance(value, datetime) else datetime.now(UTC)


def report_deps(request: Request) -> SpineDeps:
    """Deps of the after-action graphs: the latest ETR publication, the after-action review over the verified
    audit chain (a broken chain is recorded as a SEC-52 alert), and the outbox publisher that burns the
    execution token."""
    from sgw.approval.breakglass_deps import audit_paths
    from sgw.approval.deps import approval_service
    from sgw.approval.ledger import OutboxSink
    from sgw.approval.signer import Keyring
    from sgw.reports import after_action as aa
    from sgw.reports import sc_103_314
    from sgw.reports.nodes import ReportDeps
    from sgw.reports.publisher import OutboxEtrPublisher
    from sgw.reports.sources import db_estimates

    settings = request.app.state.sgw.settings
    service = approval_service(request)
    paths = audit_paths(request)
    as_of = _scenario_now(request)

    def connect() -> psycopg.Connection[Any]:
        return dbconnect.connect(settings.database_url, autocommit=True)

    def estimates() -> list[Any]:
        from sgw.api.readmodels.etr import draft_estimates

        with connect() as conn:
            found = draft_estimates(conn, as_of)
        if not found:
            raise Unavailable(
                "no ETR publication from the restoration model yet", code="EVIDENCE_UNAVAILABLE"
            )
        return found

    def review(at: datetime) -> aa.AfterActionReview:
        from sgw.approval import audit

        with connect() as conn:
            found = aa.review(
                conn, at, keyring=Keyring.load(paths.keyring), anchors=audit.AnchorStore(paths.anchors)
            )
            return aa.counted_like_decisions(found, aa.still_open(conn))

    def scorecard() -> list[Any]:
        from sgw.reports import scorecard as sc

        with connect() as conn:
            found = db_estimates(conn, as_of)
        return sc.score_publication(found)

    def on_chain_broken(chain: aa.ChainCheck) -> bool:
        with connect() as conn:
            return aa.record_chain_alert(conn, chain, as_of)

    def etr_case() -> str:
        from sgw.api.readmodels.etr import published
        from sgw.reports.seed import ETR_CASE, ensure_revision_case

        with connect() as conn:
            return ensure_revision_case(conn, as_of) if published(conn) is not None else ETR_CASE

    return ReportDeps(
        llm=GatewayClient(),
        proposals=ApprovalServicePort(connect=connect, service=service),
        llm_gate=db_gate(connect),
        estimates=estimates,
        review=review,
        on_chain_broken=on_chain_broken,
        etr_case=etr_case,
        scorecard=scorecard,
        publisher=OutboxEtrPublisher(connect=connect, sink=OutboxSink(), approvals=service),
        interruptions=lambda: sc_103_314.build(as_of=as_of),
        as_of=as_of,
    )


def copilot_deps(request: Request) -> SpineDeps:
    """Copilot runs: the default deps plus the API scenario clock (`as_of` never runs ahead of it)."""
    return copilot.with_clock(default_deps(request), request)


def default_graph_deps() -> dict[str, Callable[[Request], SpineDeps]]:
    """Per-graph deps factories (one mechanism for every graph); graphs not listed use `deps_factory`."""
    return {**dict.fromkeys(REPORT_GRAPHS, report_deps), copilot.GRAPH_ID: copilot_deps}


async def _close_async_pool(pool: Any) -> None:
    await pool.close()


async def _default_runtime(request: Request) -> AgentRuntime:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    api = request.app.state.sgw
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        api.settings.database_url,
        min_size=1,
        max_size=4,
        open=False,
        name="sgw-agent-checkpoints",
        check=AsyncConnectionPool.check_connection,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": "-c search_path=lg",
        },
    )
    await pool.open(wait=True, timeout=15)
    on_close(request.app, "agent_runtime", _close_async_pool, pool)
    return AgentRuntime(
        deps_factory=default_deps,
        graph_deps=default_graph_deps(),
        store=PostgresRunStore(api.pool),
        checkpointer=AsyncPostgresSaver(pool),
    )


async def agent_runtime(request: Request) -> AgentRuntime:
    runtime = getattr(request.app.state, "agent_runtime", None)
    if runtime is None:
        runtime = await _default_runtime(request)
        request.app.state.agent_runtime = runtime
    return runtime


Runtime = Annotated[AgentRuntime, Depends(agent_runtime)]


def server_run_mode(request: Request, asked: RunMode) -> RunMode:
    api = getattr(request.app.state, "sgw", None)
    clock = getattr(api, "clock", None)
    view = getattr(clock, "view", None)
    mode = getattr(view, "run_mode", None)
    return mode if isinstance(mode, RunMode) else asked


async def _owned_thread(runtime: AgentRuntime, thread_id: str, user_id: str) -> ThreadRow:
    thread = await runtime.store.thread(thread_id)
    if thread is None or thread.user_id != user_id:
        raise NotFound("thread not found", code="THREAD_NOT_FOUND")
    return thread


def _graph_deps(graph: str, deps: SpineDeps) -> SpineDeps:
    """The water graph runs on the water-twin PS-17 table with a rule port beside the spine's."""
    return water.from_spine(deps) if graph == water.GRAPH_ID else deps


def _task(
    runtime: AgentRuntime, row: RunRow, request: Request, user_role: str, run_input: dict[str, Any]
) -> RunTask:
    build = GRAPHS.get(row.graph)
    if build is None:
        raise Conflict(f"graph {row.graph!r} is not available yet", code="GRAPH_NOT_AVAILABLE")
    store = runtime.store
    holder: list[RunTask] = []

    async def on_status(status: str) -> None:
        tainted = bool((await holder[0].state()).get("tainted")) if status != "running" else row.tainted
        await store.set_status(row.run_id, status, tainted)

    task = RunTask(
        run_id=row.run_id,
        thread_id=row.thread_id,
        graph_id=row.graph,
        graph=build(runtime.checkpointer),
        deps=_miss_recording(
            runtime.graph_deps[row.graph](request)
            if row.graph in runtime.graph_deps
            else _graph_deps(row.graph, runtime.deps_factory(request)),
            row.graph,
            request,
        ),
        user_id=row.user_id,
        user_role=user_role,
        run_mode=RunMode(row.run_mode),
        run_input=run_input,
        on_status=on_status,
    )
    holder.append(task)
    return task


def _demo_mode(request: Request) -> bool:
    settings = getattr(getattr(request.app.state, "sgw", None), "settings", None)
    return bool(getattr(settings, "demo_mode", False))


async def _playback_task(
    runtime: AgentRuntime, row: RunRow, request: Request, run_input: dict[str, Any]
) -> Any:
    """K19: in DEMO_MODE, the recorded run of the bookmark the database is at, when the gateway cannot
    serve it."""
    from sgw.agent.nodes.run_store import GRAPH_VERSIONS
    from sgw.demo import eventlog

    if not eventlog.playback_allowed(_demo_mode(request)):
        return None
    now = _scenario_now(request)
    marked = await eventlog.database_bookmark(getattr(getattr(request.app.state, "sgw", None), "pool", None))
    version = GRAPH_VERSIONS.get(row.graph, f"{row.graph}@1")
    log = eventlog.match(row.graph, now, marked, version, run_input=run_input)
    gateway = os.environ.get("SGW_GATEWAY_URL", "http://127.0.0.1:8100")
    if log is None or not await eventlog.gateway_cannot_answer(gateway, row.graph, now):
        return None
    store = runtime.store

    async def on_status(status: str) -> None:
        await store.set_status(row.run_id, status, False)

    return eventlog.PlaybackTask(log=log, run_id=row.run_id, thread_id=row.thread_id, on_status=on_status)


def _miss_recording(deps: SpineDeps, graph: str, request: Request) -> SpineDeps:
    """In DEMO_MODE a replay miss of this run marks its graph and scenario time for K19 playback."""
    if not _demo_mode(request):
        return deps
    from dataclasses import replace

    from sgw.demo.eventlog import MissRecorder

    return replace(deps, llm=MissRecorder(deps.llm, graph, lambda: _scenario_now(request)))


@router.post("/api/threads", operation_id="createThread", status_code=201, response_model=Thread)
async def create_thread(body: ThreadCreate, user: SessionWrite, runtime: Runtime) -> Thread:
    """Read-only roles (the auditor) may open Ask threads: Ask only reads; every other module needs a
    role that may write."""
    if user.read_only and body.module is not Module.ASK:
        raise Forbidden("this role is read-only", code="READ_ONLY_ROLE")
    thread = Thread(
        thread_id=f"thr-{uuid.uuid4().hex[:12]}", created_at=datetime.now(UTC), module=body.module
    )
    await runtime.store.add_thread(
        ThreadRow(thread.thread_id, user.user_id, body.module.value, thread.created_at)
    )
    return thread


@router.post(
    "/api/threads/{thread_id}/runs", operation_id="createRun", status_code=202, response_model=RunAccepted
)
async def create_run(
    thread_id: str, body: RunCreate, user: SessionWrite, runtime: Runtime, request: Request
) -> RunAccepted:
    if user.read_only and body.graph != "copilot":
        raise Forbidden("this role is read-only", code="READ_ONLY_ROLE")
    await _owned_thread(runtime, thread_id, user.user_id)
    latest = await runtime.store.latest_run(thread_id)
    if latest is not None and latest.status == "running":
        raise Conflict("a run is already active on this thread", code="RUN_ACTIVE")
    if body.graph not in GRAPHS:
        raise Conflict(f"graph {body.graph!r} is not available yet", code="GRAPH_NOT_AVAILABLE")
    row = RunRow(
        run_id=f"run-{uuid.uuid4().hex[:12]}",
        thread_id=thread_id,
        user_id=user.user_id,
        graph=body.graph,
        run_mode=server_run_mode(request, body.run_mode).value,
        status="created",
    )
    run_input = {k: v for k, v in body.input.items() if k != "history"}
    await runtime.store.add_run(row)
    playback = await _playback_task(runtime, row, request, run_input)
    if playback is None and body.graph == "copilot":
        from sgw.api.routers.ask import conversation

        run_input["history"] = await conversation(runtime, thread_id, user.user_id)
    task = playback or _task(runtime, row, request, user.function.value, run_input)
    runtime.keep(task)
    task.start()
    return RunAccepted(run_id=row.run_id, thread_id=thread_id, events_url=f"/api/threads/{thread_id}/events")


def _after_seq(last_event_id: str | None, run_id: str, epoch: int) -> int:
    if not last_event_id:
        return -1
    try:
        sse_id = SseId.parse(last_event_id)
    except ValueError:
        return -1
    if sse_id.stream != f"run:{run_id}" or sse_id.epoch != epoch:
        return -1
    return sse_id.seq


async def _sse(task: RunTask, after: int, epoch: int) -> AsyncIterator[str]:
    async for frame in task.follow(after, heartbeat_s=HEARTBEAT_S):
        if frame is None:
            yield ": heartbeat\n\n"
            continue
        yield encode_frame(frame, SseId(stream=f"run:{task.run_id}", epoch=epoch, seq=frame.seq))


@router.get("/api/threads/{thread_id}/events", operation_id="streamRun")
async def stream_run(
    thread_id: str, request: Request, user: CurrentUser, runtime: Runtime
) -> StreamingResponse:
    await _owned_thread(runtime, thread_id, user.user_id)
    row = await runtime.store.latest_run(thread_id)
    task = runtime.live.get(row.run_id) if row else None
    if task is None:
        raise NotFound("no live run on this thread", code="RUN_NOT_FOUND")
    after = _after_seq(request.headers.get("last-event-id"), task.run_id, runtime.epoch)
    return StreamingResponse(
        _sse(task, after, runtime.epoch), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.post("/api/threads/{thread_id}/runs/{run_id}/cancel", operation_id="cancelRun", status_code=204)
async def cancel_run(thread_id: str, run_id: str, user: Writer, runtime: Runtime) -> Response:
    await _owned_thread(runtime, thread_id, user.user_id)
    row = await runtime.store.run(run_id)
    if row is None or row.thread_id != thread_id:
        raise NotFound("run not found", code="RUN_NOT_FOUND")
    task = runtime.live.get(run_id)
    if task is not None:
        await task.cancel()
    return Response(status_code=204)


async def _may_wake(runtime: AgentRuntime, row: RunRow, user: AuthUser, task: RunTask | None) -> bool:
    if user.user_id == row.user_id:
        return True
    if task is None:
        return False
    approval = (await task.state()).get("approval") or {}
    return user.function.value in approval.get("functions_required", [])


async def resume_run(run_id: str, user: Writer, runtime: Runtime, request: Request) -> RunAccepted:
    """Wake a paused run. The body is ignored: the graph's execute step reads the approval store, so a
    resume can never approve; it only lets the run look again (and pause again while approvals are due)."""
    row = await runtime.store.run(run_id)
    task = runtime.live.get(run_id) if row else None
    if row is None or not await _may_wake(runtime, row, user, task):
        raise NotFound("run not found", code="RUN_NOT_FOUND")
    if row.status != "paused":
        raise Conflict("only a paused run can be resumed", code="RUN_NOT_PAUSED")
    if task is None:
        task = _task(runtime, row, request, user.function.value, {})
        runtime.keep(task)
    task.start_resume({"by": user.user_id})
    return RunAccepted(
        run_id=run_id, thread_id=row.thread_id, events_url=f"/api/threads/{row.thread_id}/events"
    )


if RESUME_ROUTE in contract_routes():
    router.add_api_route(
        RESUME_ROUTE[1],
        resume_run,
        methods=[RESUME_ROUTE[0]],
        operation_id="resumeRun",
        status_code=202,
        response_model=RunAccepted,
    )
