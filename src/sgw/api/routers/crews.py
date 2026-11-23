"""K3 crew reads: `GET /api/crews` (status at the scenario time from the FSM events, C0/C1 only) and
`GET /api/crews/plan` (the latest crew plan published at or before the scenario time: P50 plan and SAA
courses of action with envelope bounds, VSS and EVPI)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from sgw.api.deps import CurrentUser, DbConn, State
from sgw.api.errors import NotFound
from sgw.api.routers._cache import cached_json
from sgw.api.routers._scenario import read_time, scenario_name
from sgw.contracts.api_models import CrewItem, CrewPlanDocument
from sgw.contracts.vocab import CrewStatus
from sgw.dispatch import read as dispatch_read
from sgw.dispatch import rules
from sgw.dispatch.policy import ReferenceDispatch
from sgw.models.optimise import read as plan_read
from sgw.models.restoration import field
from sgw.scenarios import packs
from sgw.scenarios import reads as pack_reads

router = APIRouter(tags=["ops"])
DISPATCH_POLICY = ReferenceDispatch()
ADVISORY = r"^N([+-][0-9]{1,2})?$"


@router.get("/api/crews", operation_id="listCrews", response_model=list[CrewItem])
async def list_crews(
    request: Request,
    user: CurrentUser,
    conn: DbConn,
    state: State,
    status: Annotated[CrewStatus | None, Query()] = None,
) -> Response:
    """Each crew carries the dispatch actions the signed-in person may take now (none for read-only roles)."""
    pack = packs.get(scenario_name(state))
    if pack is not None:
        return cached_json(request, pack_reads.crews(pack, read_time(state), status))
    crews = await field.crews(conn, read_time(state), status)
    subject = await dispatch_read.subject(conn, user.user_id)
    return cached_json(
        request,
        [
            c.model_copy(update={"actions": rules.actions_for(rules.state_of(c), subject, DISPATCH_POLICY)})
            for c in crews
        ],
    )


@router.get("/api/crews/plan", operation_id="getCrewPlan", response_model=CrewPlanDocument)
async def get_crew_plan(
    request: Request,
    _: CurrentUser,
    conn: DbConn,
    state: State,
    advisory: Annotated[str | None, Query(pattern=ADVISORY)] = None,
) -> Response:
    try:
        body = await plan_read.crew_plan(conn, scenario_name(state), read_time(state), advisory)
    except plan_read.NotPublished as exc:
        raise NotFound(str(exc), code="CREW_PLAN_NOT_PUBLISHED") from exc
    return cached_json(request, body)
