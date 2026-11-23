"""D1/D2: the queue follows the scenario clock and a moved clock re-plans open proposals (SC-3)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest

from sgw.approval import testkit as tk
from sgw.approval.ledger import MemorySink
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService, Revision
from sgw.ingest.testing import server_available
from sgw.models.clocks import advisory

N_TIME = datetime(2024, 9, 26, 9, 5, tzinfo=UTC)
N1_TIME = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)


def test_advisory_in_force_follows_the_issue_times() -> None:
    table = advisory.member_table()
    assert advisory.advisory_in_force(table, datetime(2024, 9, 26, 8, 59, tzinfo=UTC)) is None
    assert advisory.advisory_in_force(table, N_TIME) == "N"
    assert advisory.advisory_in_force(table, N1_TIME) == "N+1"


@pytest.fixture
def db() -> Iterator[str]:
    reason = server_available()
    if reason:
        pytest.skip(reason)  # sgw-allow-skip: needs Postgres (SGW_TEST_DATABASE_URL)
    with tk.seeded_database() as url:
        yield url


def _reviser(svc: ApprovalService) -> advisory.Reviser:
    def revise(
        conn: psycopg.Connection[Any], *, proposal_id: str, params: dict[str, Any], reason: str
    ) -> int:
        change = Revision(params=params)
        return svc.revise(
            conn, actor=advisory.ACTOR, proposal_id=proposal_id, change=change, reason=reason
        ).value.proposal_version

    return revise


def test_crossing_n_plus_1_stores_the_queue_and_voids_the_pending_signature(db: str) -> None:
    clock = tk.MutableClock(N_TIME)
    sink = MemorySink()
    svc = ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=clock, ledger=sink)
    with psycopg.connect(db, autocommit=True) as conn:
        first = advisory.sync_queue(conn, N_TIME, revise=_reviser(svc))
        assert first.advisory == "N" and first.stored
        assert advisory.sync_queue(conn, N_TIME, revise=_reviser(svc)).stored is False
        card = tk.new_crew_proposal(conn, svc)
        svc.decide(conn, user_id="ic_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
        clock.at = N1_TIME
        moved = advisory.sync_queue(conn, N1_TIME, revise=_reviser(svc))
        assert moved.advisory == "N+1" and moved.stored and not moved.refused
        assert moved.revised[card.proposal_id] == 2
        assert "DC-D2-CREWS-AIK" in moved.moved and "DC-D3-PS17-POWER" in moved.moved
        power = conn.execute(
            "SELECT effective_decide_by_utc, no_regret_verdict FROM decision_case"
            " WHERE decision_case_id = 'DC-D3-PS17-POWER'"
        ).fetchone()
        assert power == (datetime(2024, 9, 27, 3, 29, tzinfo=UTC), "decide_now")
        after = svc.card(conn, card.proposal_id)
        assert after.proposal_version == 2 and after.state.value == "proposed" and after.approvals == []
        assert after.params["decide_by_advisory"] == "N+1"
        revised = conn.execute(
            "SELECT count(*) FROM audit_event WHERE kind = 'proposal_revised' AND subject = %s",
            (card.proposal_id,),
        ).fetchone()
        assert revised == (1,)
        assert advisory.sync_queue(conn, N1_TIME, revise=_reviser(svc)).stored is False
