"""Queue severity (one test per level, boundaries on the K10 policy numbers), proposer and owner
function, and both on the service's summaries over a seeded database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from sgw.approval import testkit as tk
from sgw.approval.proposer import owner_function, proposer, system_display_name
from sgw.approval.service import ApprovalService
from sgw.approval.severity import ELEVATED_KEY, SEVERE_KEY, decision_severity
from sgw.common import numbers
from sgw.contracts.api_models import ProposalSummary
from sgw.contracts.vocab import ApprovalFunction, InitiatorKind, ProposalState, UiSeverity

NOW = datetime(2024, 9, 26, 15, 30, tzinfo=UTC)
SEVERE_MIN = numbers.value(SEVERE_KEY)
ELEVATED_MIN = numbers.value(ELEVATED_KEY)


def _sev(
    left: timedelta, *, state: ProposalState = ProposalState.IN_REVIEW, critical_path: bool = False
) -> UiSeverity:
    return decision_severity(
        state=state, effective_decide_by_utc=NOW + left, on_critical_path=critical_path, now=NOW
    )


def test_thresholds_are_k10_policy_numbers() -> None:
    entries = numbers.numbers()
    assert entries[SEVERE_KEY].kind.value == "policy" and entries[ELEVATED_KEY].kind.value == "policy"
    assert 0 < SEVERE_MIN < ELEVATED_MIN


def test_critical_when_the_decide_by_is_missed() -> None:
    assert _sev(timedelta(seconds=-1)) is UiSeverity.CRITICAL
    assert _sev(timedelta(hours=-5), critical_path=True) is UiSeverity.CRITICAL


def test_severe_inside_the_last_window() -> None:
    assert _sev(timedelta(0)) is UiSeverity.SEVERE
    assert _sev(timedelta(minutes=SEVERE_MIN) - timedelta(seconds=1)) is UiSeverity.SEVERE
    assert _sev(timedelta(minutes=1), critical_path=True) is UiSeverity.SEVERE


def test_elevated_inside_the_advisory_cycle_or_on_the_critical_path() -> None:
    assert _sev(timedelta(minutes=SEVERE_MIN)) is UiSeverity.ELEVATED
    assert _sev(timedelta(minutes=ELEVATED_MIN) - timedelta(seconds=1)) is UiSeverity.ELEVATED
    assert _sev(timedelta(hours=30), critical_path=True) is UiSeverity.ELEVATED


def test_advisory_when_open_and_far_off() -> None:
    assert _sev(timedelta(minutes=ELEVATED_MIN)) is UiSeverity.ADVISORY
    assert _sev(timedelta(days=2), state=ProposalState.PROPOSED) is UiSeverity.ADVISORY
    assert _sev(timedelta(days=2), state=ProposalState.ESCALATED) is UiSeverity.ADVISORY


@pytest.mark.parametrize(
    "state",
    [
        s
        for s in ProposalState
        if s not in {ProposalState.PROPOSED, ProposalState.IN_REVIEW, ProposalState.ESCALATED}
    ],
)
def test_normal_when_nothing_waits_on_a_signer(state: ProposalState) -> None:
    assert _sev(timedelta(hours=-1), state=state, critical_path=True) is UiSeverity.NORMAL


def test_unknown_stale_is_never_a_clock_verdict() -> None:
    seen = {
        _sev(timedelta(minutes=m), state=s, critical_path=c)
        for m in (-60, 0, 30, 120, 600)
        for s in ProposalState
        for c in (False, True)
    }
    assert UiSeverity.UNKNOWN_STALE not in seen
    assert seen == set(UiSeverity) - {UiSeverity.UNKNOWN_STALE}


def test_proposer_for_people_and_system_initiators() -> None:
    person = proposer(
        user_id="ops_dm_01",
        initiator_kind="person",
        display_name="Duty Manager, Electric Operations",
        function="operations",
    )
    assert person.function is ApprovalFunction.OPERATIONS
    assert owner_function(person, ["command", "logistics"]) is ApprovalFunction.OPERATIONS
    rule = proposer(
        user_id="system:rule:ps17_pressure_floor",
        initiator_kind=InitiatorKind.SYSTEM_RULE,
        display_name=None,
        function=None,
    )
    assert rule.display_name == "SGW rule ps17_pressure_floor" and rule.function is None
    assert owner_function(rule, ["command", "water_operations"]) is ApprovalFunction.COMMAND
    optimiser = proposer(
        user_id="system:optimiser", initiator_kind="system_rule", display_name=None, function=None
    )
    assert optimiser.display_name == "SGW optimiser"
    assert owner_function(optimiser, []) is None
    assert system_display_name("system:watch:commitments") == "SGW watch commitments"


def test_agent_proposal_is_owned_by_the_lead_signer_not_the_requester() -> None:
    agent = proposer(
        user_id="ops_dm_01", initiator_kind="agent", display_name="Duty Manager", function="operations"
    )
    assert agent.display_name == "Duty Manager" and agent.function is ApprovalFunction.OPERATIONS
    assert owner_function(agent, ["command", "logistics"]) is ApprovalFunction.COMMAND


def test_unknown_user_falls_back_to_the_id() -> None:
    who = proposer(user_id="ghost_01", initiator_kind="person", display_name=None, function=None)
    assert who.display_name == "ghost_01" and owner_function(who, ["command"]) is ApprovalFunction.COMMAND


def test_summaries_carry_severity_proposer_and_owner(
    conn: psycopg.Connection[Any], svc: ApprovalService, clock: tk.MutableClock
) -> None:
    card = tk.new_crew_proposal(conn, svc)
    assert card.proposed_by.user_id == "ops_dm_01"
    assert card.proposed_by.display_name == "Duty Manager, Electric Operations"
    assert card.proposed_by.function is ApprovalFunction.OPERATIONS
    assert card.proposed_by.initiator_kind is InitiatorKind.PERSON
    assert card.owner_function is ApprovalFunction.OPERATIONS
    decide_by = card.effective_decide_by_utc
    expected = decision_severity(
        state=card.state,
        effective_decide_by_utc=decide_by,
        on_critical_path=card.on_critical_path,
        now=clock(),
    )
    assert card.severity is expected

    def listed() -> ProposalSummary:
        return next(s for s in svc.summaries(conn) if s.proposal_id == card.proposal_id)

    assert listed().severity is expected
    clock.advance(seconds=(decide_by - clock()).total_seconds() + 60)
    assert listed().severity is UiSeverity.CRITICAL
    assert svc.summary(conn, card.proposal_id).severity is UiSeverity.CRITICAL
    assert listed().proposed_by == card.proposed_by


def test_mock_severity_vectors_come_from_the_server_rule() -> None:
    from sgw.contracts.export import render_all, severity_vectors

    vectors = severity_vectors()
    now = datetime.fromisoformat(vectors["now"])
    for case in vectors["cases"]:
        assert case["severity"] == decision_severity(
            state=case["state"],
            effective_decide_by_utc=datetime.fromisoformat(case["effective_decide_by_utc"]),
            on_critical_path=case["on_critical_path"],
            now=now,
        )
    assert {c["severity"] for c in vectors["cases"]} == {s.value for s in UiSeverity} - {"unknown_stale"}
    assert "export const SEVERITY_VECTORS = " in render_all()["web/src/contracts/vectors.gen.ts"]
