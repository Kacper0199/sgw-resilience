"""Hazard reads for the map (A1): `GET /api/hazard/advisories` (advisories issued by the scenario time) and
`GET /api/hazard/advisories/{label}` (analysis track, official track, cone, county peak gusts)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from sgw.api.deps import CurrentUser, State
from sgw.api.errors import NotFound
from sgw.api.routers._cache import cached_json
from sgw.api.routers._scenario import read_time, scenario_name
from sgw.contracts.api_models import HazardAdvisory, HazardAdvisoryDetail
from sgw.models.hazard import read
from sgw.scenarios import packs
from sgw.scenarios import reads as pack_reads

router = APIRouter(tags=["risk"])


@router.get(
    "/api/hazard/advisories", operation_id="listHazardAdvisories", response_model=list[HazardAdvisory]
)
async def list_hazard_advisories(request: Request, _: CurrentUser, state: State) -> Response:
    pack = packs.get(scenario_name(state))
    if pack is not None:
        return cached_json(request, pack_reads.advisories(pack, read_time(state)))
    try:
        items = read.advisories(scenario_name(state), read_time(state))
    except FileNotFoundError:
        items = []
    return cached_json(request, items)


@router.get(
    "/api/hazard/advisories/{label}", operation_id="getHazardAdvisory", response_model=HazardAdvisoryDetail
)
async def get_hazard_advisory(label: str, request: Request, _: CurrentUser, state: State) -> Response:
    pack = packs.get(scenario_name(state))
    if pack is not None:
        try:
            return cached_json(request, pack_reads.advisory(pack, label, read_time(state)))
        except pack_reads.NotIssued as exc:
            raise NotFound(
                f"advisory {label!r} is not issued yet or unknown", code="ADVISORY_NOT_FOUND"
            ) from exc
    try:
        body = read.advisory(scenario_name(state), label, read_time(state))
    except (read.NotIssued, FileNotFoundError) as exc:
        raise NotFound(f"advisory {label!r} is not issued yet or unknown", code="ADVISORY_NOT_FOUND") from exc
    return cached_json(request, body)
