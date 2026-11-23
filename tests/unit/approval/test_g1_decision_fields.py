"""G1-BE: the decision card carries what the browser used to infer (P-19-01/02/04), History reads the whole
ledger of one proposal, and agent runs never open a second proposal for the same case and action.

Runs the real approval service and the advisory re-planner on a seeded scratch database: sign at advisory N,
cross to N+1 (the re-planner revises the open proposal and voids the signature), then read the card."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest

from sgw.approval import audit
from sgw.approval import testkit as tk
from sgw.approval.ledger import MemorySink
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService, Revision
from sgw.contracts import golden
from sgw.contracts.api_models import ProposalCard, ProposalSummary
from sgw.contracts.vocab import InitiatorKind
from sgw.ingest.testing import server_available
from sgw.models.clocks import advisory
from sgw.models.clocks.story import case_story

N_TIME = datetime(2024, 9, 26, 9, 5, tzinfo=UTC)
N1_TIME = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)
CREWS = golden.PROPOSAL_CREWS


@pytest.fixture(scope="module")
def db() -> Iterator[str]:
    reason = server_available()
    if reason:
        pytest.skip(reason)  # sgw-allow-skip: needs Postgres
    with tk.seeded_database() as url:
        yield url


def _reviser(svc: ApprovalService) -> advisory.Reviser:
    def revise(
        conn: psycopg.Connection[Any], *, proposal_id: str, params: dict[str, Any], reason: str
    ) -> int:
        out = svc.revise(
            conn, actor=advisory.ACTOR, proposal_id=proposal_id, change=Revision(params=params), reason=reason
        )
        return out.value.proposal_version

    return revise


@pytest.fixture(scope="module")
def story(db: str) -> dict[str, Any]:
    """Sign the seeded crew proposal at N as Command, then cross to N+1."""
    clock = tk.MutableClock(N_TIME)
    svc = ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=clock, ledger=MemorySink())
    with psycopg.connect(db, autocommit=True) as conn:
        seeded = svc.card(conn, CREWS)
        advisory.sync_queue(conn, N_TIME, revise=_reviser(svc))
        at_n = svc.card(conn, CREWS)
        svc.decide(conn, user_id="ic_01", proposal_id=CREWS, request=tk.approve_req(at_n))
        clock.at = N1_TIME
        moved = advisory.sync_queue(conn, N1_TIME, revise=_reviser(svc))
        at_n1 = svc.card(conn, CREWS)
        summary = next(s for s in svc.summaries(conn) if s.proposal_id == CREWS)
    return {
        "svc": svc,
        "clock": clock,
        "seeded": seeded,
        "at_n": at_n,
        "at_n1": at_n1,
        "moved": moved,
        "summary": summary,
    }


def test_version_one_has_no_shift_no_voided_signature_and_no_revision_reason(story: dict[str, Any]) -> None:
    card: ProposalCard = story["seeded"]
    assert card.proposal_version == 1 and card.clock_shift is None
    assert card.voided_approvals == [] and card.revision_reason is None


def test_n_plus_1_card_names_the_shift_against_advisory_n(story: dict[str, Any]) -> None:
    card: ProposalCard = story["at_n1"]
    shift = card.clock_shift
    expected = case_story(card.decision_case_id, N1_TIME)
    assert shift is not None and expected is not None
    assert (shift.advisory_label, shift.previous_advisory_label) == ("N+1", "N")
    assert shift.previous_effective_decide_by_utc == expected.previous_effective_decide_by_utc
    minutes = (card.effective_decide_by_utc - shift.previous_effective_decide_by_utc).total_seconds() / 60
    assert shift.shift_min == round(minutes) and shift.shift_min != 0
    summary: ProposalSummary = story["summary"]
    assert summary.clock_shift == shift


def test_the_voided_signature_and_the_reason_stay_on_the_card(story: dict[str, Any]) -> None:
    card: ProposalCard = story["at_n1"]
    signed_on = story["at_n"].proposal_version
    assert card.proposal_version == signed_on + 1 and card.approvals == []
    (voided,) = card.voided_approvals
    assert (voided.approver_id, voided.function.value, voided.decision.value) == (
        "ic_01",
        "command",
        "approve",
    )
    assert voided.proposal_version == signed_on and voided.voided_by_version == signed_on + 1
    assert (
        voided.reason is not None and "advisory N+1" in voided.reason and "signatures voided" in voided.reason
    )
    assert card.revision_reason == voided.reason


def test_member_counts_behind_the_no_regret_share() -> None:
    at_n, at_n1 = case_story("DC-D3-PS17-POWER", N_TIME), case_story("DC-D3-PS17-POWER", N1_TIME)
    assert at_n is not None and at_n1 is not None
    assert (at_n.members_needing, at_n.members_total) == (13, 40)
    assert (at_n1.members_needing, at_n1.members_total) == (37, 40)
    queue = advisory.compute(advisory.member_table(), "N+1")
    power = queue.cases["DC-D3-PS17-POWER"].case
    assert (power.no_regret_members, power.ensemble_members) == (37, 40)
    assert power.no_regret_share_ppm == round(37 / 40 * 1_000_000)
    assert case_story("DC-D3-PS17-POWER", datetime(2024, 9, 26, 8, 0, tzinfo=UTC)) is None


def test_history_reads_the_whole_ledger_of_one_proposal(db: str, story: dict[str, Any]) -> None:
    with psycopg.connect(db, autocommit=True) as conn:
        events = audit.list_events(conn, subject=CREWS)
        everything = audit.list_events(conn)
    kinds = [e.kind for e in events]
    assert kinds[0] == "proposal_created" and "approval_recorded" in kinds and "proposal_revised" in kinds
    assert {e.subject for e in events} == {CREWS}
    assert [e.seq for e in events] == sorted(e.seq for e in everything if e.subject == CREWS)
    assert audit.list_events(conn=psycopg.connect(db, autocommit=True), subject="PRP-NOPE") == []


def test_agent_runs_rejoin_the_open_agent_proposal_of_the_same_case_and_action(
    db: str, story: dict[str, Any]
) -> None:
    """G1: a second water_continuity run opened a second proposal for the same case. Agent runs now rejoin the
    undecided agent proposal; a person's proposal (the seeded crew proposal) is never taken over."""
    svc: ApprovalService = story["svc"]

    def agent(run_id: str, sandhill: int) -> ProposalCard:
        request = tk.crew_request(sandhill=sandhill, millpond=9)
        return svc.create(
            conn, proposed_by="ops_dm_01", request=request, initiator_kind=InitiatorKind.AGENT, run_id=run_id
        ).value

    with psycopg.connect(db, autocommit=True) as conn:
        first = agent("run-g1-first", 14)
        assert first.proposal_id != CREWS and first.proposal_version == 1
        again = agent("run-g1-again", 14)
        assert again.proposal_id == first.proposal_id and again.proposal_version == 1
        changed = agent("run-g1-changed", 15)
        assert changed.proposal_id == first.proposal_id and changed.proposal_version == 2
        assert changed.revision_reason is not None and "run-g1-changed" in changed.revision_reason
        person = tk.new_crew_proposal(conn, svc, sandhill=9)
        assert person.proposal_id not in (CREWS, first.proposal_id)
        open_crews = conn.execute(
            "SELECT initiator_kind::text, count(*) FROM proposal WHERE decision_case_id = %s"
            " AND action_type = %s AND state = 'proposed' GROUP BY 1 ORDER BY 1",
            (golden.CASE_CREWS, "preposition_crews"),
        ).fetchall()
    assert open_crews == [("agent", 1), ("person", 2)]


def test_a_new_advisory_proposes_afresh_instead_of_rejoining(db: str, story: dict[str, Any]) -> None:
    """The golden path: the N proposal is revised by the re-planner at N+1 and later expires (D8); the
    assess run at N+1 opens its own proposal. Only re-runs within one advisory rejoin."""
    svc: ApprovalService = story["svc"]
    clock: tk.MutableClock = story["clock"]
    request = tk.staging_request(customers=300)
    with psycopg.connect(db, autocommit=True) as conn:
        clock.at = N_TIME
        at_n = svc.create(
            conn, proposed_by="ops_dm_01", request=request, initiator_kind=InitiatorKind.AGENT, run_id="run-n"
        ).value
        again_n = svc.create(
            conn,
            proposed_by="ops_dm_01",
            request=request,
            initiator_kind=InitiatorKind.AGENT,
            run_id="run-n2",
        ).value
        clock.at = N1_TIME
        at_n1 = svc.create(
            conn,
            proposed_by="ops_dm_01",
            request=request,
            initiator_kind=InitiatorKind.AGENT,
            run_id="run-n1",
        ).value
    assert again_n.proposal_id == at_n.proposal_id
    assert at_n1.proposal_id != at_n.proposal_id
