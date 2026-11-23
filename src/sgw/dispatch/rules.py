"""Crew dispatch state rules, shared by the write service and the read model so the actions a
person is offered are exactly the ones the service accepts. Who may act is the policy's question
(`sgw.dispatch.policy`); whether the crew's state allows the move is answered here."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sgw.contracts.api_models import CrewAction, CrewItem, CrewMove
from sgw.contracts.vocab import CrewStatus
from sgw.dispatch.policy import DispatchPolicy

NOT_ASSIGNABLE = frozenset({CrewStatus.BLOCKED, CrewStatus.OFF_SHIFT})
ARRIVAL: dict[str, CrewStatus] = {"decision": CrewStatus.ONSITE, "yard": CrewStatus.STAGED}


@dataclass(frozen=True)
class CrewState:
    status: CrewStatus
    assignment_state: str | None
    target_kind: str | None
    proposed_by: str | None = None
    required_function: str | None = None


def state_of(crew: CrewItem) -> CrewState:
    a = crew.assignment
    return CrewState(
        status=crew.status,
        assignment_state=a.state if a else None,
        target_kind=a.target_kind if a else None,
        proposed_by=a.proposed_by if a else None,
        required_function=a.required_function.value if a else None,
    )


def move_allowed(move: CrewMove, crew: CrewState) -> bool:
    assigned = crew.assignment_state == "assigned"
    blocked = crew.status is CrewStatus.BLOCKED
    if move == "blocked":
        return not blocked
    if move == "unblock":
        return blocked
    if move == "release":
        return assigned
    if not assigned or blocked:
        return False
    if move == "enroute":
        return crew.status is not CrewStatus.ENROUTE and crew.status is not ARRIVAL[str(crew.target_kind)]
    arrival = ARRIVAL[str(crew.target_kind)]
    return move == arrival.value and crew.status is not arrival


def assign_allowed(crew: CrewState) -> bool:
    return crew.assignment_state is None and crew.status not in NOT_ASSIGNABLE


def actions_for(crew: CrewState, subject: Mapping[str, Any], policy: DispatchPolicy) -> list[CrewAction]:
    """What `subject` may do with this crew now; empty for read-only personas (no disabled buttons)."""
    out: list[CrewAction] = []
    if crew.assignment_state == "proposed":
        sign = policy.sign(
            {
                "subject": subject,
                "assignment": {
                    "state": crew.assignment_state,
                    "proposed_by": crew.proposed_by,
                    "required_function": crew.required_function,
                },
            }
        )
        if sign.allow:
            out += ["sign", "reject"]
    if not policy.act({"subject": subject}).allow:
        return out
    if assign_allowed(crew):
        out.append("assign")
    if crew.assignment_state == "proposed":
        out.append("withdraw")
    moves: tuple[tuple[CrewMove, CrewAction], ...] = (
        ("enroute", "enroute"),
        ("onsite", "onsite"),
        ("staged", "staged"),
        ("blocked", "block"),
        ("unblock", "unblock"),
        ("release", "release"),
    )
    out += [action for move, action in moves if move_allowed(move, crew)]
    return out
