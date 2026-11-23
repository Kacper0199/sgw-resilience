"""K3 `demo`: `POST /api/demo/goto` loads a demo moment's full state for a presenter (clock operator
roles, DEMO_MODE only; `sgw.api.demo_goto`). The request holds no database connection: the copy replaces the
database the pool points at, and the API follows the new database epoch before it answers."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import psycopg
from fastapi import APIRouter, Request

from sgw.api import clock_service, demo_goto, scenario_jobs
from sgw.api.deps import ReleasedClockOperator, State
from sgw.api.errors import Conflict, NotFound, Unavailable
from sgw.api.scenario_info import scenario_period
from sgw.approval.deps import refresh_owned_pool
from sgw.contracts.api_models import DemoGotoRequest, DemoGotoResult, ScenarioLoadRequest, ScenarioLoadResult
from sgw.demo import snapshots
from sgw.demo.bookmarks import BY_ID
from sgw.scenarios import packs

PACK_BASE_MOMENT = "before-n"
HELENE_RETURN_MOMENT = "at-n1"

router = APIRouter(tags=["scenario"])
_running = asyncio.Lock()


async def _follow_clock(state: Any) -> None:
    """The loaded copy carries its own clock: install it before answering, so the first reads after the
    load see the loaded moment and not the previous one until the control poller catches up."""
    async with state.pool.connection() as conn:
        await clock_service.load(conn, state.clock, state.settings.scenario)
        await conn.commit()


@router.post("/api/demo/goto", operation_id="loadDemoMoment", response_model=DemoGotoResult)
async def load_demo_moment(
    body: DemoGotoRequest, user: ReleasedClockOperator, state: State, request: Request
) -> DemoGotoResult:
    """The scenario jobs run on the loaded moment before the answer (as `sgw demo goto` runs them), so the
    first reads after a load see its advisory queue, zone rules and injects."""
    if not demo_goto.available(state.settings):
        raise Unavailable(
            "loading a demo moment is available only in the demo with a goto connection",
            code="DEMO_GOTO_UNAVAILABLE",
        )
    bm = BY_ID.get(body.bookmark)
    if bm is None:
        raise NotFound(f"no demo moment {body.bookmark}", code="DEMO_MOMENT_NOT_FOUND")
    if _running.locked():
        raise Conflict("another demo moment is loading", code="DEMO_GOTO_RUNNING")
    async with _running:
        try:
            loaded = await asyncio.to_thread(demo_goto.load, state.settings, bm, user.session_hash)
        except (LookupError, snapshots.TargetRefused, demo_goto.GotoUnavailable) as error:
            raise Unavailable(str(error), code="DEMO_GOTO_UNAVAILABLE") from None
        except psycopg.Error:
            raise Unavailable("the demo moment could not be loaded", code="DEMO_GOTO_FAILED") from None
        await state.pool.check()
        await asyncio.to_thread(refresh_owned_pool, request.app)
        await state.broadcaster.check_epoch()
        await _follow_clock(state)
        await scenario_jobs.after_command(request.app)
        state.broadcaster.wake()
    return DemoGotoResult(
        bookmark=bm.id, title=bm.title, scenario_time=loaded.scenario_time, seconds=round(loaded.seconds, 2)
    )


@router.post("/api/demo/scenario", operation_id="loadScenario", response_model=ScenarioLoadResult)
async def load_scenario(
    body: ScenarioLoadRequest, user: ReleasedClockOperator, state: State, request: Request
) -> ScenarioLoadResult:
    """Load another scenario for every user (presenters): a pack starts from the quiet Helene
    template with the clock switched to the pack's first moment, so no Helene decision or signature is
    carried over; the way back loads the Helene demo moment's saved state. The clock is switched before the
    API follows the new database, so clients resync once, into the pack, never into the template's moment."""
    if not demo_goto.available(state.settings):
        raise Unavailable(
            "loading a scenario is available only in the demo with a goto connection",
            code="DEMO_GOTO_UNAVAILABLE",
        )
    if _running.locked():
        raise Conflict("another demo moment is loading", code="DEMO_GOTO_RUNNING")
    started = time.perf_counter()
    pack = packs.get(body.scenario)
    bm = BY_ID[PACK_BASE_MOMENT if pack is not None else HELENE_RETURN_MOMENT]
    async with _running:
        try:
            loaded = await asyncio.to_thread(demo_goto.load, state.settings, bm, user.session_hash)
        except (LookupError, snapshots.TargetRefused, demo_goto.GotoUnavailable) as error:
            raise Unavailable(str(error), code="DEMO_GOTO_UNAVAILABLE") from None
        except psycopg.Error:
            raise Unavailable("the scenario could not be loaded", code="DEMO_GOTO_FAILED") from None
        at = loaded.scenario_time
        if pack is not None:
            at = pack.moments[0].at
            async with state.pool.connection() as conn:
                await clock_service.switch_scenario(conn, state.clock, pack.scenario, at, user)
                await conn.commit()
        await state.pool.check()
        await asyncio.to_thread(refresh_owned_pool, request.app)
        await state.broadcaster.check_epoch()
        await _follow_clock(state)
        if pack is not None:
            await scenario_jobs.after_command(request.app)
        state.broadcaster.wake()
    return ScenarioLoadResult(
        scenario=body.scenario,
        title=scenario_period(body.scenario).title,
        scenario_time=at,
        seconds=round(time.perf_counter() - started, 2),
    )
