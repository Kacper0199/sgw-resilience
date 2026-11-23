"""Scenario jobs: what must follow the scenario clock in the API process. After every scenario command and
every `SGW_SCENARIO_JOBS_S` seconds, the decision queue of the advisory in force is recomputed and stored,
open proposals whose case clock moved are revised (signatures voided), and proposals past their expiry are
marked `expired` (D8), all on the scenario clock. With `SGW_ZONE_RULES` on, the zone rules then raise the
decisions known at the scenario time (`sgw.models.clocks.zone_cases`); with `SGW_SCENARIO_INJECTS` on, so
do the scripted exercise injects (`sgw.rules.injects`).

Off unless `SGW_SCENARIO_JOBS_S` is set (compose and the demo set it), so test apps never change state on
their own.

One run at a time, each on one scenario time (R35 defect 5): the periodic run and the run after a clock
command never overlap (an asyncio lock in the API, a Postgres advisory lock across processes), the time is
read once the lock is held, and every step of a run (queue, revisions, expiry, zone rules, injects) uses
that time. Before, a periodic run that had read the time before a seek expired proposals at the new time
(the service's live clock) before the seek's own run re-planned them, and the seek answered before the
decisions of the new time were raised. A run after a command that fails on a database error is retried, so
the command answers only once its moment holds what the jobs raise."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

import psycopg
from fastapi import FastAPI

from sgw.approval.deps import app_approval_service
from sgw.approval.service import ApprovalService, Revision
from sgw.common import dbconnect
from sgw.models.clocks import advisory, zone_cases
from sgw.scenarios import packs

log = logging.getLogger("sgw.api.scenario_jobs")
INTERVAL_ENV = "SGW_SCENARIO_JOBS_S"
RUN_LOCK_KEY = 2300_0003
COMMAND_ATTEMPTS = 3
RETRY_S = 0.5


def interval_s() -> float | None:
    raw = os.environ.get(INTERVAL_ENV, "").strip()
    if not raw:
        return None
    try:
        return max(0.5, float(raw))
    except ValueError:
        return None


def reviser(service: ApprovalService) -> advisory.Reviser:
    def revise(
        conn: psycopg.Connection[Any], *, proposal_id: str, params: dict[str, Any], reason: str
    ) -> int:
        outcome = service.revise(
            conn, actor=advisory.ACTOR, proposal_id=proposal_id, change=Revision(params=params), reason=reason
        )
        return outcome.value.proposal_version

    return revise


def at_time(service: ApprovalService, now: datetime) -> ApprovalService:
    """The service on a fixed scenario time: a run never mixes its time with a clock that moved."""
    return ApprovalService(
        service.policy,
        scenario_clock=lambda: now,
        token_clock=service.token_clock,
        token_ttl_s=service.token_ttl_s,
        ledger=service.ledger,
    )


def _one_run(conn: psycopg.Connection[Any]) -> None:
    conn.execute("SELECT pg_advisory_lock(%s)", (RUN_LOCK_KEY,))


def run_pack(dsn: str, now: datetime, service: ApprovalService, scenario: str) -> zone_cases.ZoneSync:
    """A scenario pack runs only its own injects and the expiry: the Helene advisory queue, zone rules and
    injects never run on another scenario's clock."""
    service = at_time(service, now)
    with dbconnect.connect(dsn, autocommit=True) as conn:
        _one_run(conn)
        expired = service.expire_due(conn)
        zoned = zone_cases.sync_pack(conn, now, service, scenario)
    if expired or zoned.raised or zoned.refused:
        log.info(
            "scenario jobs (%s) at %s: expired=%s raised=%s refused=%s",
            scenario,
            now.isoformat(),
            expired,
            zoned.raised,
            zoned.refused,
        )
    return zoned


def pack_times(scenario: str, ran: tuple[str, datetime] | None, now: datetime) -> list[datetime]:
    """The times a pack's jobs run at to reach `now`: each moment the clock passed since the last run on
    this pack, in order, then `now`. A jump straight to a later moment leaves the state a
    presenter passing through every moment leaves (and the Ask recordings read), not one that settles the
    skipped moments' injects differently."""
    since = ran[1] if ran is not None and ran[0] == scenario else None
    if since is None:
        return [now]
    return [m.at for m in packs.load(scenario).moments if since < m.at < now] + [now]


def run_once(dsn: str, now: datetime, service: ApprovalService) -> advisory.QueueSync:
    service = at_time(service, now)
    with dbconnect.connect(dsn, autocommit=True) as conn:
        _one_run(conn)
        sync = advisory.sync_queue(conn, now, revise=reviser(service))
        expired = service.expire_due(conn)
        zoned = zone_cases.sync(conn, now, service) if zone_cases.enabled() else zone_cases.ZoneSync()
        if zone_cases.injects_enabled():
            injected = zone_cases.sync_injects(conn, now, service)
            zoned.raised.update(injected.raised)
            zoned.refused.update(injected.refused)
    if sync.stored or sync.revised or sync.refused or expired or zoned.raised or zoned.refused:
        log.info(
            "scenario jobs at %s: advisory=%s stored=%s revised=%s refused=%s expired=%s zone_raised=%s"
            " zone_refused=%s",
            now.isoformat(),
            sync.advisory,
            sync.stored,
            sync.revised,
            sync.refused,
            expired,
            zoned.raised,
            zoned.refused,
        )
    return sync


def after_load(dsn: str, at: datetime) -> advisory.QueueSync:
    """The jobs above, once, on a just-loaded demo moment at its own scenario time and outside the API
    process (approval rules from `ReferencePolicy`, the Python mirror of the OPA policy): `sgw demo goto` and
    the Ask recorder run this, so the moment holds what the API's Load moment raises before it is read."""
    from sgw.approval.ledger import default_sink
    from sgw.approval.policy import ReferencePolicy

    service = ApprovalService(ReferencePolicy(), scenario_clock=lambda: at, ledger=default_sink())
    return run_once(dsn, at, service)


def _run_lock(app: FastAPI) -> asyncio.Lock:
    lock = getattr(app.state, "scenario_jobs_lock", None)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        app.state.scenario_jobs_lock = lock
    return lock


async def _run(app: FastAPI) -> None:
    state = app.state.sgw
    await state.broadcaster.check_epoch()
    scenario = state.clock.view.state.scenario
    now = state.clock.now()
    if packs.is_pack(scenario):
        dsn = state.settings.database_url
        for at in pack_times(scenario, getattr(app.state, "pack_jobs_ran", None), now):
            await asyncio.to_thread(run_pack, dsn, at, app_approval_service(app), scenario)
        app.state.pack_jobs_ran = (scenario, now)
        return
    await asyncio.to_thread(run_once, state.settings.database_url, now, app_approval_service(app))


async def after_command(app: FastAPI, attempts: int = COMMAND_ATTEMPTS) -> None:
    """The jobs at the scenario time, after any run in progress; a database error is retried `attempts`
    times in all (the periodic run tries once: the next tick runs again)."""
    if interval_s() is None:
        return
    async with _run_lock(app):
        for attempt in range(1, attempts + 1):
            try:
                await _run(app)
                return
            except (psycopg.Error, OSError, ValueError):
                if attempt == attempts:
                    log.warning("scenario jobs after a clock command failed", exc_info=True)
                    return
                log.info("scenario jobs failed (attempt %s of %s), retrying", attempt, attempts)
            await asyncio.sleep(RETRY_S * attempt)


async def loop(app: FastAPI, every_s: float) -> None:
    while True:
        await asyncio.sleep(every_s)
        await after_command(app, attempts=1)
