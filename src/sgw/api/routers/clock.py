"""K3 `scenario`: read the scenario clock; play, pause, seek, speed and bookmark commands (DC-43). A command
also runs the scenario jobs (queue of the advisory in force, re-planned proposals, expiry) when enabled."""

from __future__ import annotations

from fastapi import APIRouter, Request

from sgw.api import clock_service, demo_goto, scenario_jobs
from sgw.api.deps import ClockOperator, CurrentUser, DbConn, State
from sgw.contracts.api_models import ScenarioCommand, ScenarioState

router = APIRouter(tags=["scenario"])


@router.get("/api/scenario", response_model=ScenarioState)
async def get_scenario(_: CurrentUser, state: State) -> ScenarioState:
    snap = state.clock.snapshot()
    return snap.model_copy(update={"loads_moments": demo_goto.available(state.settings)})


@router.post("/api/scenario", response_model=ScenarioState)
async def command_scenario(
    body: ScenarioCommand, user: ClockOperator, state: State, conn: DbConn, request: Request
) -> ScenarioState:
    result = await clock_service.command(conn, state.clock, body, user)
    await conn.commit()
    await scenario_jobs.after_command(request.app)
    state.broadcaster.wake()
    return result.model_copy(update={"loads_moments": demo_goto.available(state.settings)})
