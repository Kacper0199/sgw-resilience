"""Decision cases whose deadline passed with no proposal (V4-10b): `GET /api/decision-cases/missed`, the
rows Decisions > Closed shows beside the closed proposals, counted missed like After-action counts them."""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends

from sgw.api.deps import CurrentUser, State
from sgw.approval.deps import db_conn
from sgw.contracts.api_models import MissedDecisionCase
from sgw.contracts.vocab import Domain
from sgw.reports.after_action import missed_unproposed
from sgw.scenarios import packs

router = APIRouter(prefix="/api/decision-cases", tags=["decisions"])

Conn = Annotated[psycopg.Connection[Any], Depends(db_conn)]


@router.get("/missed", operation_id="listMissedDecisionCases", response_model=list[MissedDecisionCase])
def list_missed(_user: CurrentUser, state: State, conn: Conn) -> list[MissedDecisionCase]:
    pack = packs.get(state.clock.view.state.scenario)
    return [
        MissedDecisionCase(
            decision_case_id=c.decision_case_id,
            title=c.title,
            domain=Domain(c.domain),
            effective_decide_by_utc=c.effective_decide_by,
        )
        for c in missed_unproposed(conn, state.clock.now())
        if pack is None or pack.owns_case(c.decision_case_id)
    ]
