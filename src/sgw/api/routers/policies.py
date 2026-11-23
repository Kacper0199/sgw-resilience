"""K3 `/api/policies`: every K10 policy parameter (`kind=policy`), the target of the UI policy
chips. Read-only for any signed-in user; C0."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from sgw.api.deps import CurrentUser
from sgw.api.readmodels.http import cached_json, read_span
from sgw.api.readmodels.policies import policies
from sgw.contracts.api_models import PolicyParam
from sgw.contracts.vocab import Classification

router = APIRouter(tags=["governance"])


@router.get("/api/policies", response_model=list[PolicyParam])
async def list_policies(request: Request, user: CurrentUser) -> Response:
    with read_span("policies", user, Classification.C0):
        items = policies()
    return cached_json(request, items, max_age_s=300)
