"""`ClockBreached` from the clock service: once per passed decide-by without an approval (needs Postgres)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg import AsyncConnection

from sgw.api.clock_service import emit_clock_breaches
from sgw.approval import testkit
from sgw.contracts import golden
from sgw.contracts.vocab import RunMode
from sgw.models.commitments import seed

WALL = datetime(2026, 11, 20, 3, 30, tzinfo=UTC)


def _cases(url: str) -> dict[str, datetime]:
    with psycopg.connect(url) as c:
        rows = c.execute("SELECT decision_case_id, effective_decide_by_utc FROM decision_case").fetchall()
    return {r[0]: r[1] for r in rows}


async def _emit(url: str, now: datetime) -> tuple[list[int], list[dict[str, Any]]]:
    async with await AsyncConnection.connect(url) as conn:
        async with conn.transaction():
            seqs = await emit_clock_breaches(conn, scenario_now=now, wall_now=WALL, run_mode=RunMode.REPLAY)
        cur = await conn.execute("SELECT payload FROM event WHERE type = 'ClockBreached' ORDER BY ledger_seq")
        return seqs, [r[0] for r in await cur.fetchall()]


def test_breach_is_emitted_once_per_case_and_never_for_an_approved_case() -> None:
    if testkit.admin_dsn() is None:
        pytest.skip("no Postgres")  # sgw-allow-skip: clock breach tests need Postgres
    with testkit.seeded_database() as url:
        with psycopg.connect(url, autocommit=True) as c:
            seed.seed_ps17_case(c)
        cases = _cases(url)
        assert golden.CASE_PS17 in cases
        earliest = min(cases.values())
        assert asyncio.run(_emit(url, earliest - timedelta(minutes=1))) == ([], [])
        latest = max(cases.values())
        seqs, payloads = asyncio.run(_emit(url, latest + timedelta(minutes=1)))
        assert len(seqs) == len(cases) and {p["decision_case_id"] for p in payloads} == set(cases)
        ps17 = next(p for p in payloads if p["decision_case_id"] == golden.CASE_PS17)
        assert ps17["proposal_id"] is None
        assert ps17["breached_at_utc"].startswith(cases[golden.CASE_PS17].astimezone(UTC).isoformat()[:16])
        again, payloads_again = asyncio.run(_emit(url, latest + timedelta(hours=2)))
        assert again == [] and len(payloads_again) == len(payloads)


def test_an_approved_case_does_not_breach() -> None:
    if testkit.admin_dsn() is None:
        pytest.skip("no Postgres")  # sgw-allow-skip: clock breach tests need Postgres
    from sgw.approval.ledger import MemorySink
    from sgw.approval.policy import ReferencePolicy
    from sgw.approval.service import ApprovalService

    with testkit.seeded_database() as url:
        clock = testkit.MutableClock(golden.ADVISORY_N1.issued)
        approvals = ApprovalService(
            ReferencePolicy(), scenario_clock=clock, token_clock=clock, ledger=MemorySink()
        )

        def set_time(at: Any) -> None:
            clock.at = at

        with psycopg.connect(url, autocommit=True) as c:
            seed.seed_ps17_approved(c, approvals, set_time)
        after = _cases(url)[golden.CASE_PS17] + timedelta(minutes=1)
        _, payloads = asyncio.run(_emit(url, after))
        assert golden.CASE_PS17 not in {p["decision_case_id"] for p in payloads}
