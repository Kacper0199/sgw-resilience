"""The read models behind the copilot's tools: the same functions the REST pages call, at the injected time.

`ReadPort` is what an executor may read; each method takes the time the REST route would pass (`read_time`:
the caller's `as_of`, never ahead of the scenario clock; feed health: the replay clock, none in live mode;
readiness: none, it is judged at its pre-season review) and returns the REST response model.
`DbReads` implements it on the platform database (async psycopg for the ledger and publisher reads, a worker
thread for the sync approval and ops reads); tests pass a fake. Nothing here writes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

import psycopg

from sgw.common import dbconnect
from sgw.contracts.api_models import (
    AnomalyItem,
    CrewItem,
    CrewPlanDocument,
    DamageQueue,
    FeedHealthItem,
    ForecastResponse,
    OutageItem,
    ProposalSummary,
    ReadinessItem,
    RiskResponse,
    WhatIfGrid,
)


class NotAvailable(LookupError):
    """The read model has nothing for this time or entity (the REST route answers 404)."""


class ReadPort(Protocol):
    async def risk(self, at: datetime, level: str) -> RiskResponse: ...

    async def forecast(self, at: datetime, target: str, entity: str) -> ForecastResponse: ...

    async def outages(self, at: datetime) -> list[OutageItem]: ...

    async def crews(self, at: datetime) -> list[CrewItem]: ...

    async def crew_plan(self, at: datetime) -> CrewPlanDocument: ...

    async def anomalies(self, at: datetime) -> list[AnomalyItem]: ...

    async def feeds(self, at: datetime | None) -> list[FeedHealthItem]: ...

    async def whatif(self) -> WhatIfGrid: ...

    async def decisions(self, at: datetime, states: Sequence[str] | None) -> list[ProposalSummary]: ...

    async def readiness(self) -> list[ReadinessItem]: ...

    async def damage_queue(self, limit: int) -> DamageQueue: ...

    async def surges(
        self, at: datetime, fips: Sequence[str] | None, active_only: bool, limit: int
    ) -> Any: ...


class _ReadOnlyPolicy:
    """Approval reads never consult the policy engine; a write through this service is a bug."""

    def propose(self, payload: Any) -> Any:
        raise PermissionError("the copilot's approval reads cannot propose")

    def approve(self, payload: Any) -> Any:
        raise PermissionError("the copilot's approval reads cannot approve")


def surge_report(
    at: datetime, fips: Sequence[str] | None, active_only: bool, limit: int, scenario: str
) -> Any:
    try:
        from sgw.models.surge import read as surge_read  # type: ignore[import-not-found,unused-ignore]
    except ImportError as exc:
        raise NotAvailable("outage surge detection is not available") from exc
    try:
        return surge_read.list_outage_surges(
            at, fips=list(fips) if fips else None, scenario=scenario, active_only=active_only, limit=limit
        )
    except surge_read.SurgeUnavailable as exc:
        raise NotAvailable(str(exc)) from exc


class FileReads:
    """The read models served from committed artefacts (no database): anomalies, readiness, what-if grid,
    damage queue and outage surges."""

    def __init__(self, scenario: str = "helene") -> None:
        self.scenario = scenario

    async def anomalies(self, at: datetime) -> list[AnomalyItem]:
        from sgw.api.readmodels import anomalies

        return anomalies.anomalies(at)

    async def whatif(self) -> WhatIfGrid:
        from sgw.models.whatif import read

        return read.whatif()

    async def readiness(self) -> list[ReadinessItem]:
        from sgw.api.readmodels import readiness

        return readiness.readiness()

    async def damage_queue(self, limit: int) -> DamageQueue:
        from sgw.models.cv import read

        return read.damage_queue(limit)

    async def surges(self, at: datetime, fips: Sequence[str] | None, active_only: bool, limit: int) -> Any:
        return surge_report(at, fips, active_only, limit, self.scenario)


class DbReads(FileReads):
    """Every read model on the platform database at `dsn` (the API's `SGW_DATABASE_URL`)."""

    def __init__(self, dsn: str, scenario: str = "helene") -> None:
        super().__init__(scenario)
        self.dsn = dsn

    async def _aconn(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(self.dsn, autocommit=True)

    async def risk(self, at: datetime, level: str) -> RiskResponse:
        from sgw.models.outage import read

        async with await self._aconn() as conn:
            try:
                return await read.risk(conn, self.scenario, at, level)
            except read.NotPublished as exc:
                raise NotAvailable(str(exc)) from exc

    async def forecast(self, at: datetime, target: str, entity: str) -> ForecastResponse:
        from sgw.models.outage import read

        async with await self._aconn() as conn:
            try:
                return await read.forecast(conn, target, entity, at)
            except read.NotPublished as exc:
                raise NotAvailable(str(exc)) from exc

    async def outages(self, at: datetime) -> list[OutageItem]:
        from sgw.models.restoration import field

        async with await self._aconn() as conn:
            return await field.open_outages(conn, at)

    async def crews(self, at: datetime) -> list[CrewItem]:
        from sgw.models.restoration import field

        async with await self._aconn() as conn:
            return await field.crews(conn, at, None)

    async def crew_plan(self, at: datetime) -> CrewPlanDocument:
        from sgw.models.optimise import read

        async with await self._aconn() as conn:
            try:
                return await read.crew_plan(conn, self.scenario, at)
            except read.NotPublished as exc:
                raise NotAvailable(str(exc)) from exc

    async def readiness(self) -> list[ReadinessItem]:
        from sgw.api.readmodels import readiness

        async with await self._aconn() as conn:
            return await readiness.current(conn)

    async def feeds(self, at: datetime | None) -> list[FeedHealthItem]:
        from sgw.ops import health

        def read() -> list[FeedHealthItem]:
            with dbconnect.connect(self.dsn, autocommit=True) as conn:
                return health.feeds(conn, at)

        return await asyncio.to_thread(read)

    async def decisions(self, at: datetime, states: Sequence[str] | None) -> list[ProposalSummary]:
        from sgw.approval.service import ApprovalService

        service = ApprovalService(_ReadOnlyPolicy(), scenario_clock=lambda: at)  # type: ignore[arg-type]

        def read() -> list[ProposalSummary]:
            with dbconnect.connect(self.dsn, autocommit=True) as conn:
                return service.summaries(conn, list(states) if states else None)

        return await asyncio.to_thread(read)

    async def missed_cases(self, at: datetime) -> list[Any]:
        """Decisions whose deadline passed with no proposal (`sgw.reports.after_action.missed_unproposed`):
        missed, as Decisions > Closed and After-action count them."""
        from sgw.reports.after_action import missed_unproposed

        def read() -> list[Any]:
            with dbconnect.connect(self.dsn, autocommit=True) as conn:
                return list(missed_unproposed(conn, at))

        return await asyncio.to_thread(read)


class PackReads(DbReads):
    """Ask on a scenario pack (R34, e.g. the Ian exercise): decisions are the pack's own; customers out,
    facilities and crew counts come from the pack's scripted data (`sgw.scenarios`, so data a pack adds
    flows in without code changes); the Helene-only models say plainly that they are not modelled."""

    def __init__(self, dsn: str, scenario: str) -> None:
        from sgw.scenarios import packs

        super().__init__(dsn, scenario)
        self.pack = packs.load(scenario)

    def not_modelled(self, what: str) -> NotAvailable:
        return NotAvailable(f"{what} is not modelled for this scenario ({self.pack.label})")

    async def risk(self, at: datetime, level: str) -> RiskResponse:
        raise self.not_modelled("outage risk")

    async def forecast(self, at: datetime, target: str, entity: str) -> ForecastResponse:
        raise self.not_modelled("the outage and restoration forecast")

    async def outages(self, at: datetime) -> list[OutageItem]:
        return []

    async def crews(self, at: datetime) -> list[CrewItem]:
        from sgw.scenarios import reads

        return reads.crews(self.pack, at)

    async def crew_plan(self, at: datetime) -> CrewPlanDocument:
        raise self.not_modelled("the crew plan")

    async def anomalies(self, at: datetime) -> list[AnomalyItem]:
        raise self.not_modelled("water sensor anomaly detection")

    async def whatif(self) -> WhatIfGrid:
        raise self.not_modelled("the what-if grid")

    async def damage_queue(self, limit: int) -> DamageQueue:
        raise self.not_modelled("damage photo triage")

    async def surges(self, at: datetime, fips: Sequence[str] | None, active_only: bool, limit: int) -> Any:
        raise self.not_modelled("outage surge detection")

    async def decisions(self, at: datetime, states: Sequence[str] | None) -> list[ProposalSummary]:
        rows = await super().decisions(at, states)
        return [r for r in rows if self.pack.owns(r.proposal_id)]

    async def missed_cases(self, at: datetime) -> list[Any]:
        return [c for c in await super().missed_cases(at) if self.pack.owns_case(c.decision_case_id)]
