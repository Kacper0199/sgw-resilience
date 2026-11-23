"""Two open proposals with one title never read as two identical feed lines."""

from __future__ import annotations

from datetime import UTC, datetime

from sgw.api.readmodels.notifications import _open_items
from sgw.api.sessions import AuthUser
from sgw.contracts.api_models import ProposalSummary, Proposer
from sgw.contracts.vocab import ApprovalFunction, Domain

NOW = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)
TITLE = "Pre-position the Aiken crews"


def _proposal(proposal_id: str, title: str, decide_by: datetime) -> ProposalSummary:
    return ProposalSummary.model_construct(
        proposal_id=proposal_id,
        title=title,
        state="proposed",
        approvals=[],
        functions_required=[ApprovalFunction.COMMAND],
        proposed_by=Proposer.model_construct(user_id="system:rule:zones"),
        action_type="preposition_crews",
        proposal_version=1,
        effective_decide_by_utc=decide_by,
    )


def _commander() -> AuthUser:
    return AuthUser(
        user_id="ic_01",
        display_name="ic_01",
        function=ApprovalFunction.COMMAND,
        roles=("incident_commander",),
        regions=("SC",),
        domains=(Domain.ELECTRIC,),
        step_up_at=None,
        session_hash="0" * 64,
        demo_switch=False,
    )


def _details(proposals: list[ProposalSummary]) -> dict[str, str | None]:
    items = _open_items(_commander(), proposals, NOW, {})
    return {
        i.notification.href: i.notification.detail for i in items if i.notification.kind == "decision_waiting"
    }


def test_a_shared_title_names_the_decide_by_time() -> None:
    details = _details(
        [
            _proposal("PRP-A", TITLE, datetime(2024, 9, 26, 22, 0, tzinfo=UTC)),
            _proposal("PRP-B", TITLE, datetime(2024, 9, 27, 1, 40, tzinfo=UTC)),
        ]
    )
    assert details == {
        "/decisions/PRP-A": f"{TITLE}, decide by 18:00 ET",
        "/decisions/PRP-B": f"{TITLE}, decide by 21:40 ET",
    }


def test_a_unique_title_stays_as_it_is() -> None:
    details = _details(
        [
            _proposal("PRP-A", TITLE, datetime(2024, 9, 26, 22, 0, tzinfo=UTC)),
            _proposal("PRP-B", "Send the fuel truck", datetime(2024, 9, 27, 1, 40, tzinfo=UTC)),
        ]
    )
    assert details == {"/decisions/PRP-A": TITLE, "/decisions/PRP-B": "Send the fuel truck"}
