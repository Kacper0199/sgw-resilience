"""K3 forecast reads over the outage-forecast publisher and the ETR publication: `GET /api/forecasts` (series
for one target and entity), `GET /api/forecasts/outages/counties` (the A2 county fans of one advisory) and
`GET /api/forecasts/outages/plan-diff` (what changed from the previous advisory). Nothing issued after the
scenario time is visible."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response

from sgw.api.deps import CurrentUser, DbConn, State
from sgw.api.errors import NotFound
from sgw.api.routers._cache import cached_json
from sgw.api.routers._scenario import read_time, scenario_name
from sgw.contracts.api_models import CountyForecast, ForecastResponse, PlanDiff
from sgw.models.outage import read

router = APIRouter(tags=["risk"])
ADVISORY = r"^N([+-][0-9]{1,2})?$"
ENTITY = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$"


@router.get("/api/forecasts", operation_id="getForecast", response_model=ForecastResponse)
async def get_forecast(
    request: Request,
    _: CurrentUser,
    conn: DbConn,
    state: State,
    target: Annotated[Literal["outages", "etr"], Query()],
    entity: Annotated[str, Query(pattern=ENTITY)],
) -> Response:
    try:
        body = await read.forecast(conn, target, entity, read_time(state))
    except read.NotPublished as exc:
        raise NotFound(str(exc), code="FORECAST_NOT_FOUND") from exc
    return cached_json(request, body)


@router.get(
    "/api/forecasts/outages/counties", operation_id="getCountyForecast", response_model=CountyForecast
)
async def get_county_forecast(
    request: Request,
    _: CurrentUser,
    conn: DbConn,
    state: State,
    advisory: Annotated[str | None, Query(pattern=ADVISORY)] = None,
) -> Response:
    try:
        body = await read.county_forecast(conn, scenario_name(state), read_time(state), advisory)
    except read.NotPublished as exc:
        raise NotFound(str(exc), code="FORECAST_NOT_PUBLISHED") from exc
    return cached_json(request, body)


@router.get("/api/forecasts/outages/plan-diff", operation_id="getPlanDiff", response_model=PlanDiff)
async def get_plan_diff(
    request: Request,
    _: CurrentUser,
    conn: DbConn,
    state: State,
    to: Annotated[str | None, Query(pattern=ADVISORY)] = None,
) -> Response:
    try:
        body = await read.plan_diff(conn, scenario_name(state), read_time(state), to)
    except read.NotPublished as exc:
        raise NotFound(str(exc), code="PLAN_DIFF_NOT_PUBLISHED") from exc
    return cached_json(request, body)
