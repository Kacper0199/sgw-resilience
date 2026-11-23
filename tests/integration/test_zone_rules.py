"""Zone rules on the scenario jobs: proposals at each storm moment, idempotent, hidden on a jump back,
off by default, every clock with a basis, signers from the approval policy (reference and OPA)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest

from sgw.api import scenario_jobs
from sgw.approval import testkit as tk
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.ingest.testing import server_available
from sgw.models.clocks import zone_cases
from sgw.rules import zones

MORNING_AFTER = datetime(2024, 9, 27, 12, 0, tzinfo=UTC)
NIGHT_2 = datetime(2024, 9, 28, 6, 0, tzinfo=UTC)
ETR = datetime(2024, 9, 28, 17, 0, tzinfo=UTC)
LIFTED = datetime(2024, 9, 30, 12, 0, tzinfo=UTC)
AT_N1 = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)
EVENING_N1 = datetime(2024, 9, 26, 20, 0, tzinfo=UTC)
MORNING_KEYS = {
    "hospital_tanker_observed",
    "bwa_issue:WZ-PS23-LAURELSPUR",
    "restoration_order",
    "ami_dark_section",
}
KEY_OF = {zone_cases.proposal_base(h.key): h.key for h in zones.timeline()}


@pytest.fixture
def db() -> Iterator[str]:
    reason = server_available()
    if reason:
        pytest.skip(reason)  # sgw-allow-skip: zone rules need Postgres (SGW_TEST_DATABASE_URL)
    with tk.seeded_database() as url:
        yield url


@pytest.fixture
def flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(zone_cases.FLAG_ENV, "1")


def _service(clock: tk.MutableClock) -> ApprovalService:
    return ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=clock)


def _run(db: str, svc: ApprovalService, clock: tk.MutableClock, at: datetime) -> None:
    clock.at = at
    scenario_jobs.run_once(db, at, svc)


def _rows(db: str) -> list[dict[str, Any]]:
    with psycopg.connect(db) as conn, conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT proposal_id, state::text AS state, tier::text AS tier, required_functions::text[] AS fns,"
            " action_type::text AS action_type, decision_case_id, proposed_by FROM proposal"
            " WHERE proposal_id LIKE 'PRP-ZR-%' ORDER BY proposal_id"
        )
        return list(cur.fetchall())


def _key(proposal_id: str) -> str:
    return KEY_OF["-".join(proposal_id.split("-")[:3])]


def _keys(db: str) -> set[str]:
    return {_key(r["proposal_id"]) for r in _rows(db)}


def _visible(db: str, svc: ApprovalService) -> set[str]:
    with psycopg.connect(db) as conn:
        return {_key(s.proposal_id) for s in svc.summaries(conn) if s.proposal_id.startswith("PRP-ZR-")}


def test_flag_off_raises_nothing(db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(zone_cases.FLAG_ENV, raising=False)
    clock = tk.MutableClock(MORNING_AFTER)
    svc = _service(clock)
    for at in (MORNING_AFTER, LIFTED):
        _run(db, svc, clock, at)
    assert _rows(db) == []
    with psycopg.connect(db) as conn:
        cases = conn.execute(
            "SELECT count(*) FROM decision_case WHERE decision_case_id = ANY(%s)",
            ([h.case_id for h in zones.timeline() if h.clock is not None],),
        ).fetchone()
    assert cases == (0,)


@pytest.mark.usefixtures("flag_on")
def test_the_storm_timeline_raises_each_moment_once(db: str) -> None:
    clock = tk.MutableClock(AT_N1)
    svc = _service(clock)
    _run(db, svc, clock, MORNING_AFTER)
    assert _keys(db) == MORNING_KEYS
    before = _rows(db)
    _run(db, svc, clock, MORNING_AFTER)
    assert _rows(db) == before
    _run(db, svc, clock, NIGHT_2)
    assert _keys(db) - MORNING_KEYS == {"ps38_fuel_reroute", "bwa_issue:WZ-PS38-COPPERLEAF"}
    night = _keys(db)
    _run(db, svc, clock, ETR)
    assert _keys(db) - night == {"ps52_mobile_generator", "bwa_issue:WZ-PS52-DEERWATER"}
    etr = _keys(db)
    _run(db, svc, clock, LIFTED)
    assert _keys(db) - etr == {
        "bwa_lift:WZ-PS17-CEDARFALL",
        "bwa_lift:WZ-PS23-LAURELSPUR",
        "bwa_lift:WZ-PS38-COPPERLEAF",
    }
    undecided = [r for r in _rows(db) if r["state"] in ("proposed", "in_review", "draft")]
    assert len({_key(r["proposal_id"]) for r in undecided}) == len(undecided)


@pytest.mark.usefixtures("flag_on")
def test_an_expired_rule_proposal_is_raised_again_while_its_facts_hold(db: str) -> None:
    clock = tk.MutableClock(AT_N1)
    svc = _service(clock)
    _run(db, svc, clock, AT_N1)
    first = {r["proposal_id"] for r in _rows(db)}
    assert {_key(p) for p in first} == {"ps17_fuel_dispatch", "hospital_tanker"}
    _run(db, svc, clock, EVENING_N1)
    rows = {r["proposal_id"]: r["state"] for r in _rows(db)}
    assert all(rows[p] == "expired" for p in first)
    fuel = next(p for p in first if _key(p) == "ps17_fuel_dispatch")
    assert {p + "-2" for p in first} <= set(rows)
    _run(db, svc, clock, MORNING_AFTER)
    rows = {r["proposal_id"]: r["state"] for r in _rows(db)}
    assert not any(p.endswith("-3") for p in rows), "a resolved forecast-case order was raised again"
    with psycopg.connect(db) as conn:
        listed = [x.proposal_id for x in svc.summaries(conn) if x.proposal_id.startswith("PRP-ZR-")]
    assert fuel not in listed and fuel + "-2" in listed
    assert len(listed) == len({_key(p) for p in listed})


@pytest.mark.usefixtures("flag_on")
def test_a_jump_back_hides_later_rule_proposals(db: str) -> None:
    clock = tk.MutableClock(MORNING_AFTER)
    svc = _service(clock)
    _run(db, svc, clock, MORNING_AFTER)
    _run(db, svc, clock, LIFTED)
    clock.at = LIFTED
    assert "bwa_lift:WZ-PS17-CEDARFALL" in _visible(db, svc)
    clock.at = MORNING_AFTER
    visible = _visible(db, svc)
    assert visible and visible <= MORNING_KEYS
    assert not any(k.startswith("bwa_lift") for k in visible)


@pytest.mark.usefixtures("flag_on")
def test_signers_follow_the_tier_table(db: str) -> None:
    clock = tk.MutableClock(MORNING_AFTER)
    svc = _service(clock)
    _run(db, svc, clock, MORNING_AFTER)
    _run(db, svc, clock, LIFTED)
    by_key = {_key(r["proposal_id"]): r for r in _rows(db)}
    want = {
        "hospital_tanker_observed": ("T2", ["logistics"]),
        "bwa_issue:WZ-PS23-LAURELSPUR": ("T3", ["compliance", "water_operations"]),
        "restoration_order": ("T3", ["command", "water_operations"]),
        "ami_dark_section": ("T1", []),
        "bwa_lift:WZ-PS17-CEDARFALL": ("T3", ["compliance", "water_operations"]),
    }
    for key, (tier, fns) in want.items():
        assert (by_key[key]["tier"], sorted(by_key[key]["fns"])) == (tier, fns), key
    assert by_key["ami_dark_section"]["state"] == "draft"
    assert by_key["restoration_order"]["proposed_by"] == "system:rule:zone_restoration_order"


@pytest.mark.usefixtures("flag_on")
def test_logistics_signs_the_tanker(db: str) -> None:
    clock = tk.MutableClock(MORNING_AFTER)
    svc = _service(clock)
    _run(db, svc, clock, MORNING_AFTER)
    pid = next(r["proposal_id"] for r in _rows(db) if _key(r["proposal_id"]) == "hospital_tanker_observed")
    with psycopg.connect(db, autocommit=True) as conn:
        card = svc.card(conn, pid)
        assert card.state.value == "proposed"
        svc.decide(conn, user_id="log_01", proposal_id=pid, request=tk.approve_req(card))
        assert svc.card(conn, pid).state.value == "approved"


@pytest.mark.usefixtures("flag_on")
def test_every_rule_case_clock_cites_its_bases(db: str) -> None:
    clock = tk.MutableClock(MORNING_AFTER)
    svc = _service(clock)
    for at in (MORNING_AFTER, NIGHT_2, ETR, LIFTED):
        _run(db, svc, clock, at)
    ids = sorted({h.case_id for h in zones.timeline() if h.clock is not None and h.known_at <= LIFTED})
    with psycopg.connect(db) as conn:
        rows = conn.execute(
            "SELECT decision_case_id, consequence_basis ->> 'basis_id', lead_time_basis ->> 'basis_id',"
            " (SELECT count(*) FROM clock_waterfall_term t WHERE t.decision_case_id = c.decision_case_id"
            "  AND t.term_kind IN ('anchor', 'term', 'lead_time') AND t.basis IS NULL)"
            " FROM decision_case c WHERE decision_case_id = ANY(%s) ORDER BY 1",
            (ids,),
        ).fetchall()
        for pid in (r["proposal_id"] for r in _rows(db)):
            waterfall = svc.clock(conn, pid)
            assert waterfall.consequence_basis.basis_id and waterfall.lead_time_basis.basis_id, pid
    assert [r[0] for r in rows] == ids
    for case_id, consequence, lead, unbased in rows:
        assert consequence and lead.startswith("lead_time.") and unbased == 0, case_id


def test_opa_classifies_the_rule_proposals_like_the_reference(
    db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(zone_cases.FLAG_ENV, "1")
    clock = tk.MutableClock(MORNING_AFTER)
    with tk.opa_server() as url:
        svc = tk.service_for("opa", url, clock)
        if svc is None:
            pytest.skip("no OPA server")  # sgw-allow-skip: needs docker or SGW_TEST_OPA_URL
        _run(db, svc, clock, MORNING_AFTER)
    by_key = {_key(r["proposal_id"]): r for r in _rows(db)}
    assert set(by_key) == MORNING_KEYS
    assert (by_key["hospital_tanker_observed"]["tier"], list(by_key["hospital_tanker_observed"]["fns"])) == (
        "T2",
        ["logistics"],
    )
    assert by_key["bwa_issue:WZ-PS23-LAURELSPUR"]["tier"] == "T3"
