"""K3 `GET /api/outages`: outages open at the scenario time, from the OMS events in the ledger (C0/C1 only),
largest first; `GET /api/outages/counties`: customers out per county in the replayed outage feed."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from sgw.api.deps import CurrentUser, DbConn, State
from sgw.api.routers._cache import cached_json
from sgw.api.routers._scenario import read_time, scenario_name
from sgw.contracts.api_models import CountyOutagesNow, OutageItem
from sgw.models.outage.read import county_outages_now
from sgw.models.restoration import field
from sgw.scenarios import packs
from sgw.scenarios import reads as pack_reads

router = APIRouter(tags=["ops"])


@router.get("/api/outages", operation_id="listOutages", response_model=list[OutageItem])
async def list_outages(request: Request, _: CurrentUser, conn: DbConn, state: State) -> Response:
    return cached_json(request, await field.open_outages(conn, read_time(state)))


@router.get("/api/outages/counties", operation_id="listCountyOutages", response_model=CountyOutagesNow)
async def list_county_outages(
    request: Request, _: CurrentUser, state: State, as_of: Annotated[datetime | None, Query()] = None
) -> Response:
    pack = packs.get(scenario_name(state))
    if pack is not None:
        return cached_json(request, pack_reads.county_outages(pack, read_time(state, as_of)))
    return cached_json(request, county_outages_now(read_time(state, as_of)))
