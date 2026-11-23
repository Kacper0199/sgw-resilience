"""K3 sitrep routes: `GET /api/sitreps` lists the drafts of finished `sitrep` runs (C2; command,
executive and planning see every draft, others their own) and `POST /api/sitreps/{run_id}/promote` lets a
person in the command function promote a verified T1 draft (`sgw.api.readmodels.sitreps`)."""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from sgw.api.deps import CurrentUser, State, Writer
from sgw.api.errors import Conflict, Forbidden, NotFound
from sgw.api.readmodels import sitreps
from sgw.api.readmodels.http import cached_json, read_span
from sgw.api.routers.runs import GRAPHS, AgentRuntime, agent_runtime
from sgw.api.sessions import AuthUser
from sgw.approval.deps import db_conn
from sgw.common.telemetry import sgw_span
from sgw.contracts.api_models import SitrepDraft, SitrepPromote
from sgw.contracts.vocab import Classification, RunMode

router = APIRouter(tags=["decisions"])

Conn = Annotated[psycopg.Connection[Any], Depends(db_conn)]
Runtime = Annotated[AgentRuntime, Depends(agent_runtime)]
SITREP = "sitrep"


def _reader(runtime: AgentRuntime) -> sitreps.StateReader:
    graph = GRAPHS[SITREP](runtime.checkpointer)

    async def read(thread: str) -> dict[str, Any]:
        snap = await graph.aget_state({"configurable": {"thread_id": thread}})
        return dict(snap.values or {})

    return read


def _owner(user: AuthUser) -> str | None:
    return None if sitreps.sees_all(user.function) else user.user_id


@router.get("/api/sitreps", response_model=list[SitrepDraft])
async def list_sitreps(request: Request, user: CurrentUser, conn: Conn, runtime: Runtime) -> Response:
    with read_span("sitreps", user, Classification.C2):
        items = await sitreps.drafts(conn, _reader(runtime), user_id=_owner(user))
    return cached_json(request, items, max_age_s=0)


@router.post("/api/sitreps/{run_id}/promote", response_model=SitrepDraft)
async def promote_sitrep(
    run_id: str, body: SitrepPromote, user: Writer, conn: Conn, runtime: Runtime, state: State
) -> SitrepDraft:
    if user.function not in sitreps.PROMOTER_FUNCTIONS:
        raise Forbidden("only the command function promotes a sitrep", code="PROMOTE_COMMAND_ONLY")
    found = await sitreps.drafts(conn, _reader(runtime), user_id=None, run_id=run_id)
    if not found:
        raise NotFound("sitrep draft not found", code="SITREP_NOT_FOUND")
    item = found[0]
    if item.status != "draft":
        raise Conflict(f"the sitrep is {item.status}, not a draft", code="SITREP_NOT_PROMOTABLE")
    note = (body.note or "").strip() or None
    if item.tainted and note is None:
        raise Conflict(
            "the draft read untrusted text; promote it only with a note saying why it is safe",
            code="SITREP_TAINTED",
        )
    with sgw_span(
        "api.write.sitreps.promote",
        run_id=item.run_id,
        classification=Classification.C2,
        user_role=user.role,
        run_mode=RunMode.REPLAY,
    ):
        seq = await run_in_threadpool(
            sitreps.promote, conn, item, actor_id=user.user_id, at=state.clock.now(), note=note
        )
    if seq is None:
        raise Conflict("the sitrep was already promoted", code="SITREP_NOT_PROMOTABLE")
    promoted = await sitreps.drafts(conn, _reader(runtime), user_id=None, run_id=run_id)
    return promoted[0]
