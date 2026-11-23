"""K3 `GET /api/risk`: the risk snapshot in force at the scenario time (or an earlier `as_of`), county or
asset level, from the outage-forecast publisher. Asset level returns at most `policy_c3_aggregation_assets`
ranked rows."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response

from sgw.api.deps import CurrentUser, DbConn, State
from sgw.api.errors import NotFound
from sgw.api.routers._cache import cached_json
from sgw.api.routers._scenario import read_time, scenario_name
from sgw.contracts.api_models import RiskResponse
from sgw.models.outage import read

router = APIRouter(tags=["risk"])


@router.get("/api/risk", operation_id="getRisk", response_model=RiskResponse)
async def get_risk(
    request: Request,
    _: CurrentUser,
    conn: DbConn,
    state: State,
    as_of: Annotated[datetime | None, Query()] = None,
    level: Annotated[Literal["county", "asset"], Query()] = "county",
) -> Response:
    at = read_time(state, as_of)
    try:
        body = await read.risk(conn, scenario_name(state), at, level)
    except read.NotPublished as exc:
        raise NotFound(str(exc), code="RISK_NOT_PUBLISHED") from exc
    return cached_json(request, body)
