"""Defect 5: scenario-job runs never overlap and each runs on one scenario time, so a periodic run that
started before a seek cannot expire what the seek's own run re-plans; a command's run retries a database
error before the command answers."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest

from sgw.api import scenario_jobs
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService

T0 = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.at = T0
        self.view = SimpleNamespace(state=SimpleNamespace(scenario="helene"))

    def now(self) -> datetime:
        return self.at


def app_with(clock: Clock) -> Any:
    async def check_epoch() -> None:
        return None

    sgw = SimpleNamespace(
        clock=clock,
        broadcaster=SimpleNamespace(check_epoch=check_epoch),
        settings=SimpleNamespace(database_url="postgresql://unused"),
    )
    return SimpleNamespace(state=SimpleNamespace(sgw=sgw))


@pytest.fixture(autouse=True)
def jobs_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(scenario_jobs.INTERVAL_ENV, "2")
    monkeypatch.setattr(scenario_jobs, "app_approval_service", lambda app: "service")
    monkeypatch.setattr(scenario_jobs, "RETRY_S", 0.01)


async def test_runs_never_overlap_and_a_run_waiting_for_another_reads_the_time_after_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    spans: list[tuple[float, float, datetime]] = []

    def run_once(dsn: str, now: datetime, service: Any) -> None:
        start = time.monotonic()
        time.sleep(0.1)
        spans.append((start, time.monotonic(), now))

    monkeypatch.setattr(scenario_jobs, "run_once", run_once)
    app = app_with(clock)
    periodic = asyncio.create_task(scenario_jobs.after_command(app, attempts=1))
    await asyncio.sleep(0.02)
    clock.at = T0 + timedelta(hours=10)
    await asyncio.gather(periodic, scenario_jobs.after_command(app))
    (s1, e1, at1), (s2, e2, at2) = sorted(spans)
    assert e1 <= s2, "two runs overlapped"
    assert (at1, at2) == (T0, T0 + timedelta(hours=10))


async def test_a_command_run_retries_a_database_error_before_the_command_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tries: list[datetime] = []

    def run_once(dsn: str, now: datetime, service: Any) -> None:
        tries.append(now)
        if len(tries) < 3:
            raise psycopg.OperationalError("remaining connection slots are reserved")

    monkeypatch.setattr(scenario_jobs, "run_once", run_once)
    await scenario_jobs.after_command(app_with(Clock()))
    assert len(tries) == 3
    tries.clear()
    await scenario_jobs.after_command(app_with(Clock()), attempts=1)
    assert len(tries) == 1, "the periodic run tries once; the next tick runs again"


def test_a_run_uses_one_scenario_time_for_every_step() -> None:
    live = Clock()
    service = ApprovalService(ReferencePolicy(), scenario_clock=live.now)
    pinned = scenario_jobs.at_time(service, T0)
    live.at = T0 + timedelta(hours=10)
    assert pinned.scenario_clock() == T0 and pinned.policy is service.policy


async def test_a_jump_on_a_pack_runs_the_jobs_of_every_moment_it_passed_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Load scenario, then a jump straight to the last moment: the state of passing through."""
    from sgw.scenarios import packs

    moments = [m.at for m in packs.load("ian").moments]
    clock = Clock()
    clock.view.state.scenario = "ian"
    clock.at = moments[0]
    ran: list[datetime] = []
    monkeypatch.setattr(scenario_jobs, "run_pack", lambda dsn, at, service, scenario: ran.append(at))
    app = app_with(clock)
    await scenario_jobs.after_command(app)
    clock.at = moments[-1] + timedelta(minutes=5)
    await scenario_jobs.after_command(app)
    assert ran == [moments[0], *moments[1:], moments[-1] + timedelta(minutes=5)]
    ran.clear()
    clock.at = moments[0]
    await scenario_jobs.after_command(app)
    assert ran == [moments[0]], "a jump back runs only its own time"
