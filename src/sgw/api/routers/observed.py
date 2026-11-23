"""Real Helene open data (GD): `GET /api/hazard/observed?as_of=` (USGS gauges with NWS flood categories, ASOS
gusts, NWS warnings in force; peaks so far only) and `GET /api/after-action/official-record` (FEMA
declarations and NCEI Storm Events in the service area). Both are bounded by the scenario clock."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from sgw.api.deps import CurrentUser, State
from sgw.api.routers._cache import cached_json
from sgw.api.routers._scenario import read_time, scenario_name
from sgw.contracts.api_models import ObservedHazard, OfficialRecord
from sgw.opendata import read
from sgw.scenarios import packs

router = APIRouter(tags=["risk"])


@router.get("/api/hazard/observed", operation_id="getObservedHazard", response_model=ObservedHazard)
async def get_observed_hazard(
    request: Request,
    _: CurrentUser,
    state: State,
    as_of: Annotated[datetime | None, Query()] = None,
) -> Response:
    if packs.is_pack(scenario_name(state)):
        empty = ObservedHazard(as_of=read_time(state, as_of), gauges=[], stations=[], warnings=[], sources=[])
        return cached_json(request, empty)
    return cached_json(request, read.observed(read_time(state, as_of)))


@router.get(
    "/api/after-action/official-record",
    operation_id="getOfficialRecord",
    response_model=OfficialRecord,
    tags=["governance"],
)
async def get_official_record(request: Request, _: CurrentUser, state: State) -> Response:
    return cached_json(request, read.official_record(read_time(state)))
