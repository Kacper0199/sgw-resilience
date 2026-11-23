"""K3 ETR routes: `GET /api/etr` (global and per-area ETR with the D4 publication state) and
`GET /api/etr/areas/{region_id}` (one estimate), both at the scenario time (`sgw.api.readmodels.etr`).

Drafting runs the existing `etr` graph through the run routes (it proposes `publish_global_etr` through the
approval service); publishing wakes that paused run after command and operations signed, and the graph's
execute step burns the execution token and appends `etr_published`."""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Request, Response

from sgw.api.deps import CurrentUser, State
from sgw.api.errors import NotFound
from sgw.api.readmodels import etr
from sgw.api.readmodels.http import cached_json, provenance_header, read_span
from sgw.approval.deps import db_conn
from sgw.contracts.api_models import EtrArea, EtrView

router = APIRouter(tags=["risk"])

Conn = Annotated[psycopg.Connection[Any], Depends(db_conn)]


@router.get("/api/etr", operation_id="getEtr", response_model=EtrView)
def get_etr(request: Request, user: CurrentUser, state: State, conn: Conn) -> Response:
    with read_span("etr", user):
        doc = etr.view(conn, state.clock.now(), user.user_id)
    return cached_json(request, doc, max_age_s=0)


@router.get("/api/etr/areas/{region_id}", operation_id="getEtrArea", response_model=EtrArea)
def get_etr_area(region_id: str, request: Request, user: CurrentUser, state: State, conn: Conn) -> Response:
    with read_span("etr", user):
        found = etr.one_area(conn, state.clock.now(), region_id)
    if found is None:
        raise NotFound("no estimate for this area at the scenario time", code="ETR_AREA_NOT_FOUND")
    item, source = found
    return cached_json(request, item, headers=provenance_header(source), max_age_s=0)
