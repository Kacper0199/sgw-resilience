"""`GET /api/whatif`: the precomputed what-if grid (W10, T0): baseline and the named scenarios, each one
grid cell. Static artefact, so it may be cached for a few minutes."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from sgw.api.deps import CurrentUser
from sgw.api.routers._cache import cached_json
from sgw.contracts.api_models import WhatIfGrid
from sgw.models.whatif import read

router = APIRouter(tags=["risk"])


@router.get("/api/whatif", operation_id="getWhatIf", response_model=WhatIfGrid)
async def get_whatif(request: Request, _: CurrentUser) -> Response:
    return cached_json(request, read.whatif(), "private, max-age=300")
