"""High 1: one outcome for a closed decision (on time, late, missed), computed once on the server from
the decision clock, the proposal state and the first authority record on the scenario clock; the queue and
the copilot's clock state read the same rule."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from sgw.approval import testkit as tk
from sgw.approval.outcome import decision_outcome
from sgw.approval.service import ApprovalService
from sgw.contracts.vocab import ProposalState

DUE = datetime(2024, 9, 26, 23, 29, tzinfo=UTC)


@pytest.mark.parametrize(
    ("state", "decided_at", "want"),
    [
        (ProposalState.EXECUTED, DUE - timedelta(hours=2), "on_time"),
        (ProposalState.APPROVED, DUE, "on_time"),
        (ProposalState.APPROVED, DUE + timedelta(minutes=1), "late"),
        (ProposalState.EXECUTED, None, None),
        (ProposalState.EXPIRED, None, "missed"),
        (ProposalState.REJECTED, None, None),
        (ProposalState.WITHDRAWN, None, None),
        (ProposalState.PROPOSED, None, None),
        (ProposalState.DRAFT, None, None),
    ],
)
def test_outcome_of_a_closed_decision(
    state: ProposalState, decided_at: datetime | None, want: str | None
) -> None:
    assert decision_outcome(state=state, effective_decide_by_utc=DUE, decided_at=decided_at) == want


def test_an_expired_decision_is_missed_even_with_an_authority_record() -> None:
    assert decision_outcome(state="expired", effective_decide_by_utc=DUE, decided_at=DUE) == "missed"


def test_the_copilot_clock_state_reads_the_same_rule() -> None:
    from types import SimpleNamespace

    from sgw.agent.copilot.clock_state import clock_state

    late = SimpleNamespace(
        proposal_id="PRP-1",
        decision_case_id="DC-X",
        state=ProposalState.EXECUTED,
        proposal_version=1,
        effective_decide_by_utc=DUE,
    )
    after = DUE + timedelta(days=1)
    assert clock_state("DC-X", DUE, [late], after, {"PRP-1": DUE + timedelta(hours=1)})["decision"] == (
        "decided_late"
    )


def test_summaries_carry_the_outcome_and_when_it_was_decided(
    conn: psycopg.Connection[Any], svc: ApprovalService, clock: tk.MutableClock
) -> None:
    card = tk.new_crew_proposal(conn, svc)
    assert card.outcome is None and card.decided_at_utc is None
    svc.decide(conn, user_id="ic_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    signed_at = clock()
    svc.decide(conn, user_id="log_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    clock.advance(hours=6)
    listed = next(s for s in svc.summaries(conn) if s.proposal_id == card.proposal_id)
    assert listed.outcome == "on_time"
    assert listed.decided_at_utc == signed_at
    assert svc.card(conn, card.proposal_id).outcome == "on_time"


def test_an_unsigned_expired_decision_reads_missed(
    conn: psycopg.Connection[Any], svc: ApprovalService, clock: tk.MutableClock
) -> None:
    card = tk.new_crew_proposal(conn, svc)
    clock.advance(hours=3)
    svc.expire_due(conn)
    closed = svc.card(conn, card.proposal_id)
    assert closed.state is ProposalState.EXPIRED
    assert closed.outcome == "missed" and closed.decided_at_utc is None
