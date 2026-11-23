"""K3 `GET /api/outages/surges?as_of=` (G1): county outage surges from the EAGLE-I CUSUM detector at the
scenario time (`sgw.models.surge.read`); looking back is allowed, never ahead of the scenario clock."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from sgw.api.deps import CurrentUser, State
from sgw.api.errors import NotFound
from sgw.api.readmodels.http import cached_json, provenance_header, read_span
from sgw.api.routers._scenario import read_time, scenario_name
from sgw.contracts.api_models import Provenance, SurgeReport
from sgw.contracts.vocab import NumberLabel
from sgw.models.surge.read import SurgeUnavailable, list_outage_surges
from sgw.scenarios import packs
from sgw.scenarios import reads as pack_reads

router = APIRouter(tags=["ops"])


@router.get("/api/outages/surges", operation_id="listOutageSurges", response_model=SurgeReport)
async def get_outage_surges(
    request: Request,
    user: CurrentUser,
    state: State,
    as_of: Annotated[datetime | None, Query()] = None,
) -> Response:
    at = read_time(state, as_of)
    pack = packs.get(scenario_name(state))
    if pack is not None:
        return cached_json(request, pack_reads.no_surges(pack, at))
    with read_span("outage_surges", user):
        try:
            report = list_outage_surges(at, scenario=scenario_name(state))
        except SurgeUnavailable as exc:
            raise NotFound(str(exc), code="SURGES_UNAVAILABLE") from exc
    provenance = Provenance(
        source="data/artefacts/surge/helene_series.csv.gz",
        model_id=report.model_version,
        as_of=report.data_through,
        label=NumberLabel.C,
        detail="EAGLE-I public outage data; evals/reports/outage_surge.json",
    )
    return cached_json(request, report, headers=provenance_header(provenance))
