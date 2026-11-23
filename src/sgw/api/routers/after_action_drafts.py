"""K3 after-action draft routes: `GET /api/after-action/drafts` lists drafts of `after_action`
runs and `POST /api/after-action/drafts` starts one at the scenario time for the command function or the
auditor (an independent reviewer, read-only for every other write). The run belongs to the person who
started it, like any run; the start is one `after_action_drafted` audit record. Nothing is filed."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from sgw.agent.nodes.run_store import RunRow, ThreadRow
from sgw.api.deps import CurrentUser, SessionWrite, State
from sgw.api.errors import Conflict, Forbidden
from sgw.api.readmodels import after_action_drafts as aad
from sgw.api.readmodels.http import cached_json, read_span
from sgw.api.routers.runs import (
    GRAPHS,
    AgentRuntime,
    _playback_task,
    _task,
    agent_runtime,
    server_run_mode,
)
from sgw.approval.deps import db_conn
from sgw.common.telemetry import sgw_span
from sgw.contracts.api_models import AfterActionDraft, RunAccepted
from sgw.contracts.vocab import Classification, Module, RunMode

router = APIRouter(tags=["governance"])

Conn = Annotated[psycopg.Connection[Any], Depends(db_conn)]
Runtime = Annotated[AgentRuntime, Depends(agent_runtime)]


def _reader(runtime: AgentRuntime) -> aad.StateReader:
    graph = GRAPHS[aad.GRAPH](runtime.checkpointer)

    async def read(thread: str) -> dict[str, Any]:
        snap = await graph.aget_state({"configurable": {"thread_id": thread}})
        return dict(snap.values or {})

    return read


@router.get(
    "/api/after-action/drafts", operation_id="listAfterActionDrafts", response_model=list[AfterActionDraft]
)
async def list_drafts(request: Request, user: CurrentUser, conn: Conn, runtime: Runtime) -> Response:
    owner = None if aad.sees_all(user.function) else user.user_id
    with read_span("after_action.drafts", user, Classification.C2):
        items = await aad.drafts(conn, _reader(runtime), user_id=owner)
    return cached_json(request, items, max_age_s=0)


@router.post(
    "/api/after-action/drafts",
    operation_id="draftAfterAction",
    status_code=202,
    response_model=RunAccepted,
)
async def draft_after_action(
    request: Request, user: SessionWrite, conn: Conn, runtime: Runtime, state: State
) -> RunAccepted:
    if not aad.may_draft(user.function, user.roles):
        raise Forbidden(
            "only the Incident Commander or the auditor drafts the after-action review",
            code="AFTER_ACTION_DRAFT_DENIED",
        )
    if any(r["status"] == "running" for r in aad.runs(conn, user_id=None)):
        raise Conflict("an after-action draft is already being written", code="RUN_ACTIVE")
    thread = ThreadRow(
        f"thr-{uuid.uuid4().hex[:12]}", user.user_id, Module.AFTER_ACTION.value, datetime.now(UTC)
    )
    await runtime.store.add_thread(thread)
    row = RunRow(
        run_id=f"run-{uuid.uuid4().hex[:12]}",
        thread_id=thread.thread_id,
        user_id=user.user_id,
        graph=aad.GRAPH,
        run_mode=server_run_mode(request, RunMode.REPLAY).value,
        status="created",
    )
    with sgw_span(
        "api.write.after_action.draft",
        run_id=row.run_id,
        classification=Classification.C2,
        user_role=user.role,
        run_mode=RunMode(row.run_mode),
    ):
        await runtime.store.add_run(row)
        await run_in_threadpool(
            aad.record_drafted,
            conn,
            run_id=row.run_id,
            thread_id=thread.thread_id,
            actor_id=user.user_id,
            at=state.clock.now(),
        )
        task = await _playback_task(runtime, row, request, {}) or _task(
            runtime, row, request, user.function.value, {}
        )
        runtime.keep(task)
        task.start()
    return RunAccepted(
        run_id=row.run_id, thread_id=thread.thread_id, events_url=f"/api/threads/{thread.thread_id}/events"
    )
