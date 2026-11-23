"""Exercise injects on the scenario jobs: off by default, raised once per moment next to the zone rules,
hidden on a jump back, map assets with positions, signers from the approval policy (reference)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest

from sgw.api import scenario_jobs
from sgw.approval import testkit as tk
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.ingest.testing import server_available
from sgw.models.clocks import zone_cases
from sgw.rules import injects

AT_N1 = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)
MORNING_AFTER = datetime(2024, 9, 27, 12, 0, tzinfo=UTC)
OPEN = ("proposed", "in_review", "draft")


@pytest.fixture
def db() -> Iterator[str]:
    reason = server_available()
    if reason:
        pytest.skip(reason)  # sgw-allow-skip: injects need Postgres (SGW_TEST_DATABASE_URL)
    with tk.seeded_database() as url:
        with psycopg.connect(url, autocommit=True) as conn:
            for region in sorted({a.region_id for a in injects.load().assets}):
                conn.execute(
                    "INSERT INTO region (region_id, state, county_fips, name) VALUES (%s, %s, %s, %s)"
                    " ON CONFLICT (region_id) DO NOTHING",
                    (region, region[:2], region[3:], f"County {region[3:]}"),
                )
        yield url


def _service(clock: tk.MutableClock) -> ApprovalService:
    return ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=clock)


def _run(db: str, svc: ApprovalService, clock: tk.MutableClock, at: datetime) -> None:
    clock.at = at
    scenario_jobs.run_once(db, at, svc)


def _injected(db: str) -> list[tuple[str, str, str]]:
    with psycopg.connect(db) as conn:
        rows = conn.execute(
            "SELECT decision_case_id, state::text, proposed_by FROM proposal"
            " WHERE proposal_id LIKE 'PRP-EX-%' ORDER BY decision_case_id"
        ).fetchall()
    return [(str(a), str(b), str(c)) for a, b, c in rows]


def test_injects_are_off_by_default(db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(zone_cases.INJECTS_FLAG_ENV, raising=False)
    monkeypatch.setenv(zone_cases.FLAG_ENV, "1")
    clock = tk.MutableClock(AT_N1)
    _run(db, _service(clock), clock, AT_N1)
    assert _injected(db) == []


def test_injects_raise_each_moment_once_with_map_positions(db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(zone_cases.INJECTS_FLAG_ENV, "1")
    clock = tk.MutableClock(AT_N1)
    svc = _service(clock)
    _run(db, svc, clock, AT_N1)
    first = _injected(db)
    with psycopg.connect(db) as conn:
        known = {str(r[0]) for r in conn.execute("SELECT asset_id FROM asset").fetchall()}
    expected = {h.case_id for h in injects.active(AT_N1) if set(h.target_ids) <= known}
    assert len(expected) >= 5
    assert {c for c, _, _ in first} == expected
    assert all(state in OPEN and who == "system:rule:exercise_inject" for _, state, who in first)
    _run(db, svc, clock, AT_N1)
    assert _injected(db) == first
    with psycopg.connect(db) as conn:
        placed = conn.execute(
            "SELECT count(*) FROM asset WHERE asset_id = ANY(%s) AND geom IS NOT NULL",
            ([a.asset_id for a in injects.load().assets],),
        ).fetchone()
        tiers = dict(
            conn.execute(
                "SELECT decision_case_id, tier::text FROM proposal WHERE proposal_id LIKE 'PRP-EX-%'"
            ).fetchall()
        )
    assert placed == (len(injects.load().assets),)
    assert tiers["DC-D3-EX-06-SHELTER-GENERATOR"] == "T2", "a mobile resource order is signed by logistics"
    assert tiers["DC-D3-EX-04-HYPOCHLORITE-HOLLOWPINE"] == "T2"
    _run(db, svc, clock, MORNING_AFTER)
    morning = {c for c, state, _ in _injected(db) if state in OPEN}
    assert {h.case_id for h in injects.active(MORNING_AFTER) if set(h.target_ids) <= known} <= morning
    clock.at = AT_N1
    with psycopg.connect(db) as conn:
        listed = {s.decision_case_id for s in svc.summaries(conn) if s.proposal_id.startswith("PRP-EX-")}
    later = {h.case_id for h in injects.active(MORNING_AFTER)}
    assert not listed & later, "a jump back shows injects that are not known yet"
