"""Flows in the feed: a withdrawn signature, an emergency approval waiting for its co-sign, a rejected
crew assignment, a resume waiting for the second team, and one newest-first order."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sgw.api.readmodels.notifications import AuditRow, _audit_items, build
from sgw.api.sessions import AuthUser
from sgw.contracts.api_models import ProposalSummary, Proposer
from sgw.contracts.vocab import ApprovalFunction, Domain

AT = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)
WALL = datetime(2026, 11, 22, 4, 0, tzinfo=UTC)
PID = "PRP-R34"


def _user(user_id: str, function: ApprovalFunction) -> AuthUser:
    return AuthUser(
        user_id=user_id,
        display_name=user_id,
        function=function,
        roles=(),
        regions=("SC",),
        domains=(Domain.ELECTRIC,),
        step_up_at=None,
        session_hash="0" * 64,
        demo_switch=False,
    )


IC = _user("ic_01", ApprovalFunction.COMMAND)
LOG = _user("log_01", ApprovalFunction.LOGISTICS)
COMP = _user("wtr_comp_01", ApprovalFunction.COMPLIANCE)


def _proposal(state: str = "proposed") -> ProposalSummary:
    return ProposalSummary.model_construct(
        proposal_id=PID,
        title="Pre-position crews",
        state=state,
        approvals=[],
        functions_required=[ApprovalFunction.COMMAND, ApprovalFunction.LOGISTICS],
        proposed_by=Proposer.model_construct(user_id="system:rule:exercise_inject"),
        action_type="preposition_crews",
        proposal_version=1,
        effective_decide_by_utc=AT + timedelta(hours=1),
    )


def _titles(user: AuthUser, rows: list[AuditRow], state: str = "proposed") -> list[str]:
    items = _audit_items(user, rows, {PID: _proposal(state)}, WALL)
    return [i.notification.title for i in items]


def test_a_withdrawn_signature_replaces_the_signed_notice() -> None:
    rows = [
        AuditRow(
            1,
            AT,
            "ic_01",
            "approval_recorded",
            PID,
            {"approval_id": "APR-1", "decision": "approve", "function": "command"},
        ),
        AuditRow(
            2,
            AT,
            "ic_01",
            "approval_withdrawn",
            PID,
            {"signature_withdrawn": "APR-1", "function": "command", "reason": "wrong crew"},
        ),
    ]
    assert _titles(LOG, rows) == ["Command withdrew its signature"]


def test_an_emergency_approval_asks_the_second_team_until_it_co_signs() -> None:
    used = AuditRow(
        1, AT, "ic_01", "break_glass_used", PID, {"break_glass_id": 7, "cosign_functions": ["logistics"]}
    )
    waiting = _audit_items(LOG, [used], {PID: _proposal("approved")}, WALL)
    assert [(i.rank, i.notification.title) for i in waiting] == [(0, "Emergency approval needs your co-sign")]
    done = AuditRow(
        2, AT, "log_01", "break_glass_cosigned", PID, {"break_glass_id": 7, "function": "logistics"}
    )
    assert _titles(LOG, [used, done], "approved") == ["Command approved alone"]
    assert _titles(IC, [used, done], "approved") == ["Logistics co-signed the emergency approval"]


def test_the_proposer_hears_about_a_rejected_crew_assignment() -> None:
    rows = [
        AuditRow(
            1,
            AT,
            "log_01",
            "crew_assignment_proposed",
            "ASG-1",
            {"crew_id": "CRW-EGRET-07", "required_function": "operations"},
        ),
        AuditRow(
            2,
            AT,
            "ops_dm_01",
            "crew_assignment_rejected",
            "ASG-1",
            {"crew_id": "CRW-EGRET-07", "decision": "reject", "reason": "road closed"},
        ),
    ]
    items = _audit_items(LOG, rows, {}, WALL)
    assert [(i.notification.title, i.notification.detail) for i in items] == [
        ("Crew assignment rejected", "CRW-EGRET-07: road closed")
    ]


def test_a_resume_waits_for_the_other_team_in_plain_words_until_it_expires() -> None:
    req = AuditRow(
        1,
        WALL - timedelta(minutes=5),
        "ic_01",
        "kill_restore_requested",
        "control:restore:RST-1",
        {
            "restore_id": "RST-1",
            "to": "K0",
            "function": "command",
            "awaiting_function": "compliance",
            "expires_in_s": 900,
            "scenario_at": "2024-09-26T15:05:00Z",
        },
    )
    items = _audit_items(COMP, [req], {}, WALL)
    assert [(i.notification.title, i.notification.detail) for i in items] == [
        ("Resume waiting for your signature", "Command asked to return to Normal. Sign within 15 minutes.")
    ]
    assert items[0].notification.at == AT
    assert _audit_items(COMP, [req], {}, WALL + timedelta(minutes=11)) == []


def test_the_feed_is_newest_first_and_a_deadline_is_dated_when_it_entered_the_window() -> None:
    signed = AuditRow(
        1,
        AT,
        "ic_01",
        "approval_recorded",
        PID,
        {"approval_id": "APR-1", "decision": "approve", "function": "command"},
    )
    earlier = AuditRow(
        0,
        AT - timedelta(hours=3),
        "ic_01",
        "kill_switch_triggered",
        "control:kill:K2",
        {"to": "K2", "reason": "drill"},
    )
    feed = build(LOG, [_proposal("in_review")], [earlier, signed], None, AT, WALL)
    times = [n.at for n in feed]
    assert times == sorted(times, reverse=True)
    deadline = next(n for n in feed if n.kind == "deadline_soon")
    assert deadline.at == AT + timedelta(hours=1) - timedelta(hours=2)


def test_water_roles_hear_of_open_water_decisions_they_do_not_sign() -> None:
    """At at-n1 five water decisions (signed by Command and Logistics) were open and the water
    roles' feed said "Nothing for you right now"."""
    water = _proposal().model_copy(update={"decision_case_id": "DC-D3-EX-07-DIALYSIS-TANKER"})
    items = build(COMP, [water], [], None, AT, water_cases=frozenset({"DC-D3-EX-07-DIALYSIS-TANKER"}))
    assert [(n.kind, n.title) for n in items] == [("water_decision_open", "Water decision open")]
    assert build(COMP, [water], [], None, AT) == []
    assert all(
        n.kind != "water_decision_open"
        for n in build(LOG, [water], [], None, AT, water_cases=frozenset({"DC-D3-EX-07-DIALYSIS-TANKER"}))
    )
