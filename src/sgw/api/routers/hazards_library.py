"""K3 `/api/hazards/library/{heat,wildfire}`: the July 2024 heat wave and the March 2025 Table Rock
fire weather as read-only views at their own as-of dates (`sgw.api.readmodels.hazards_library`). C1."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from sgw.api.deps import CurrentUser
from sgw.api.readmodels import hazards_library
from sgw.api.readmodels.http import cached_json, provenance_header, read_span
from sgw.contracts.api_models import HazardLibraryHeat, HazardLibraryWildfire

router = APIRouter(tags=["decisions"])
MAX_AGE_S = 300


@router.get(
    "/api/hazards/library/heat",
    operation_id="getHazardLibraryHeat",
    response_model=HazardLibraryHeat,
)
async def get_heat(request: Request, user: CurrentUser) -> Response:
    with read_span("hazards_library.heat", user):
        view = hazards_library.heat()
    return cached_json(request, view, headers=provenance_header(view.provenance), max_age_s=MAX_AGE_S)


@router.get(
    "/api/hazards/library/wildfire",
    operation_id="getHazardLibraryWildfire",
    response_model=HazardLibraryWildfire,
)
async def get_wildfire(request: Request, user: CurrentUser) -> Response:
    with read_span("hazards_library.wildfire", user):
        view = hazards_library.wildfire()
    return cached_json(request, view, headers=provenance_header(view.provenance), max_age_s=MAX_AGE_S)
