"""K3 `GET /api/brief`: the executive Brief at the scenario time (`sgw.api.readmodels.brief`).
Any signed-in reader; C0/C1 (only counts leave the C2 water register). Every sentence is rendered by code."""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Request, Response

from sgw.api.deps import CurrentUser, State
from sgw.api.readmodels import brief
from sgw.api.readmodels.http import cached_json, read_span
from sgw.api.routers._scenario import scenario_name
from sgw.approval.deps import approval_service, db_conn
from sgw.approval.service import ApprovalService
from sgw.contracts.api_models import ExecutiveBrief
from sgw.scenarios import packs
from sgw.scenarios import reads as pack_reads

router = APIRouter(tags=["decisions"])

Conn = Annotated[psycopg.Connection[Any], Depends(db_conn)]
Service = Annotated[ApprovalService, Depends(approval_service)]


@router.get("/api/brief", response_model=ExecutiveBrief)
def get_brief(request: Request, user: CurrentUser, state: State, conn: Conn, service: Service) -> Response:
    pack = packs.get(scenario_name(state))
    if pack is not None:
        with read_span("brief", user):
            own = packs.visible(pack.scenario, service.summaries(conn), lambda p: p.proposal_id)
            return cached_json(request, pack_reads.brief(pack, state.clock.now(), own), max_age_s=0)
    with read_span("brief", user):
        doc = brief.brief(
            conn,
            state.clock.now(),
            state.settings.scenario,
            service.summaries(conn, [s.value for s in brief.OPEN_STATES]),
        )
    return cached_json(request, doc, max_age_s=0)
