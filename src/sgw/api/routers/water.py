"""K3 water routes: pressure zones, the boil-water advisory register and the BWA rule book.

Read-only for any signed-in user, like the other read routes. A boil-water notice concerns everyone on duty,
so every reader gets the register's notices, states and due times; the C2 zone forecasts behind them (the
`water_continuity` evidence class) go only to users whose domains include water. Values are
read at the scenario time (`sgw.api.readmodels.water`); the register lists every zone's notice with its
stage and clean sample count. Responses carry an `ETag` (304 on `If-None-Match`).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from sgw.api.deps import CurrentUser, DbConn, State
from sgw.api.readmodels import water
from sgw.api.readmodels.http import cached_json, provenance_header, read_span
from sgw.api.routers._scenario import scenario_name
from sgw.contracts.api_models import BwaRegister, BwaRules, WaterZone
from sgw.contracts.vocab import Classification, Domain
from sgw.scenarios import packs

router = APIRouter(tags=["ops"])


@router.get("/api/water/zones", response_model=list[WaterZone])
async def list_water_zones(request: Request, user: CurrentUser, state: State) -> Response:
    at = state.clock.now()
    with read_span("water.zones", user):
        zones = [r.zone for r in water.zone_readings(at)]
    return cached_json(request, zones, headers=provenance_header(water.zones_provenance(at)))


@router.get("/api/water/advisories", response_model=BwaRegister)
async def list_water_advisories(request: Request, user: CurrentUser, conn: DbConn, state: State) -> Response:
    at = state.clock.now()
    water_reader = Domain.WATER in user.domains
    if packs.is_pack(scenario_name(state)):
        return cached_json(request, BwaRegister(as_of=at, advisories=[], forecasts_withheld=not water_reader))
    with read_span("water.advisories", user, Classification.C2 if water_reader else Classification.C1):
        proposals = {z: await water.latest_bwa_proposal(conn, z) for z in water.zone_ids()}
        lifts = {z: await water.latest_bwa_proposal(conn, z, water.LIFT_ACTION) for z in water.zone_ids()}
        register = water.register(at, proposals, lifts)
    return cached_json(request, register if water_reader else water.without_forecasts(register))


@router.get("/api/water/rules", response_model=BwaRules)
async def list_water_rules(request: Request, user: CurrentUser) -> Response:
    with read_span("water.rules", user, Classification.C0):
        rules = water.rules()
    return cached_json(request, rules, max_age_s=300)
