"""A signature a re-plan voided no longer reads as "Command signed": the co-signers see one voided line."""

from __future__ import annotations

from datetime import UTC, datetime

from sgw.api.readmodels.notifications import AuditRow, _audit_items
from sgw.api.sessions import AuthUser
from sgw.contracts.api_models import ProposalSummary, Proposer
from sgw.contracts.vocab import ApprovalFunction, Domain

AT = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)
PID = "PRP-CREWS"


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


def _proposal() -> ProposalSummary:
    return ProposalSummary.model_construct(
        proposal_id=PID,
        title="Pre-position crews",
        state="proposed",
        approvals=[],
        functions_required=[ApprovalFunction.COMMAND, ApprovalFunction.LOGISTICS],
        proposed_by=Proposer.model_construct(user_id="ops_dm_01"),
        action_type="preposition_crews",
        proposal_version=3,
        effective_decide_by_utc=AT,
    )


def _sign(seq: int, approval_id: str) -> AuditRow:
    payload = {"decision": "approve", "function": "command", "approval_id": approval_id}
    return AuditRow(seq, AT, "ic_01", "approval_recorded", PID, payload)


def _replan(seq: int, voided: list[str]) -> AuditRow:
    return AuditRow(
        seq, AT, "system:clock-replanner", "proposal_revised", PID, {"voided_approval_ids": voided}
    )


ROWS = [_sign(1, "APR-1"), _replan(2, ["APR-1"]), _sign(3, "APR-2"), _replan(4, ["APR-2"])]


def _titles(user: AuthUser, rows: list[AuditRow]) -> list[str]:
    return [i.notification.title for i in _audit_items(user, rows, {PID: _proposal()})]


def test_the_co_signer_sees_one_voided_line_instead_of_signed() -> None:
    assert _titles(_user("log_01", ApprovalFunction.LOGISTICS), ROWS) == [
        "Command signature was voided by a re-plan"
    ]


def test_the_signer_sees_one_line_for_its_own_signature() -> None:
    assert _titles(_user("ic_01", ApprovalFunction.COMMAND), ROWS) == [
        "Your signature was voided by a re-plan"
    ]


def test_a_signature_still_in_force_reads_as_signed() -> None:
    assert _titles(_user("log_01", ApprovalFunction.LOGISTICS), ROWS[:3]) == [
        "Command signature was voided by a re-plan",
        "Command signed",
    ]
