"""K3 agent run reads: `GET /api/runs` (recent runs with tokens and cost from `llm_call`) and
`GET /api/runs/{run_id}` (the run with its graph steps and LLM calls). A user sees their own runs; platform,
command, executive, data and audit see every run (`sgw.api.readmodels.agent_runs`). Another user's run is a
404, as in the thread routes. C1 metadata only: no prompts, outputs or state.

`POST /api/runs/{run_id}/cancel` lets platform or data stop anyone's running or paused run (a run left waiting
for a sign-off nobody will give), with a reason recorded in the audit chain."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response

from sgw.api import audit_log
from sgw.api.deps import CurrentUser, DbConn, State, Writer
from sgw.api.errors import Conflict, Forbidden, NotFound
from sgw.api.permissions import RUN_CANCEL_FUNCTIONS
from sgw.api.readmodels import agent_runs
from sgw.api.readmodels.http import cached_json, read_span
from sgw.api.routers.runs import Runtime
from sgw.contracts.api_models import AgentRunCancel, AgentRunDetail, AgentRunSummary

router = APIRouter(tags=["agent"])

RunStatus = Literal["running", "paused", "done", "error", "cancelled"]
ACTIVE = ("running", "paused")


@router.get("/api/runs", response_model=list[AgentRunSummary])
async def list_agent_runs(
    request: Request,
    user: CurrentUser,
    conn: DbConn,
    graph: Annotated[str | None, Query(max_length=64, pattern=r"^[a-z_]+$")] = None,
    status: Annotated[RunStatus | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=agent_runs.MAX_LIMIT)] = None,
) -> Response:
    owner = None if agent_runs.sees_all(user.function) else user.user_id
    with read_span("runs", user):
        items = await agent_runs.runs(conn, user_id=owner, graph=graph, status=status, limit=limit)
    return cached_json(request, items, max_age_s=0)


@router.get("/api/runs/{run_id}", response_model=AgentRunDetail)
async def get_agent_run(run_id: str, request: Request, user: CurrentUser, conn: DbConn) -> Response:
    owner = None if agent_runs.sees_all(user.function) else user.user_id
    with read_span("runs.detail", user):
        detail = await agent_runs.run_detail(conn, run_id, user_id=owner)
    if detail is None:
        raise NotFound("run not found", code="RUN_NOT_FOUND")
    return cached_json(request, detail, max_age_s=0)


@router.post("/api/runs/{run_id}/cancel", operation_id="cancelAgentRun", response_model=AgentRunSummary)
async def cancel_agent_run(
    run_id: str, body: AgentRunCancel, user: Writer, conn: DbConn, state: State, runtime: Runtime
) -> AgentRunSummary:
    if user.function not in RUN_CANCEL_FUNCTIONS:
        raise Forbidden("agent runs are cancelled by platform or data", code="RUN_CANCEL_DENIED")
    cur = await conn.execute("SELECT status FROM agent_run WHERE run_id = %s", (run_id,))
    row = await cur.fetchone()
    if row is None:
        raise NotFound("run not found", code="RUN_NOT_FOUND")
    if row[0] not in ACTIVE:
        raise Conflict(
            f"the run is {row[0]}; only a running or paused run can be cancelled", code="RUN_NOT_ACTIVE"
        )
    task = runtime.live.get(run_id)
    if task is not None:
        await task.cancel()
    cur = await conn.execute(
        "UPDATE agent_run SET status = 'cancelled', ended_at = coalesce(ended_at, now())"
        " WHERE run_id = %s AND status = ANY(%s) RETURNING run_id",
        (run_id, [*ACTIVE, "cancelled"]),
    )
    if await cur.fetchone() is None:
        raise Conflict("the run finished meanwhile", code="RUN_NOT_ACTIVE")
    await audit_log.append(
        conn,
        kind="agent_run_cancelled",
        actor_type="user",
        actor_id=user.user_id,
        subject=f"run:{run_id}",
        payload={"run_id": run_id, "from": row[0], "reason": body.reason, "function": user.function.value},
        occurred_at=state.clock.now(),
    )
    found = await agent_runs.runs(conn, user_id=None, run_id=run_id, limit=1)
    return found[0]
