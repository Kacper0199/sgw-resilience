"""K3 `/api/anomalies`: A7/A8 water anomaly alarms detected by the scenario time, newest first
(`sgw.api.readmodels.anomalies`). Read-only for any signed-in user; C1 (sensor ids and alarm kinds)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from sgw.api.deps import CurrentUser, State
from sgw.api.readmodels import anomalies
from sgw.api.readmodels.http import cached_json, provenance_header, read_span
from sgw.contracts.api_models import AnomalyItem

router = APIRouter(tags=["ops"])


@router.get("/api/anomalies", response_model=list[AnomalyItem])
async def list_anomalies(request: Request, user: CurrentUser, state: State) -> Response:
    at = state.clock.now()
    with read_span("anomalies", user):
        items = anomalies.anomalies(at)
    return cached_json(request, items, headers=provenance_header(anomalies.provenance(at)))
