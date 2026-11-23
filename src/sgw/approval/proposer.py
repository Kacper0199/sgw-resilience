"""Who proposed a decision and which function owns it, for the K3 `ProposalSummary`.

Owner rule: a person who proposes owns the follow-through, so the owner is the proposer's function; a
system or agent proposal is owned by the first required approval function (the lead signer of the K8 tier
row); a system proposal without approvers (T1) has no owner function.
"""

from __future__ import annotations

from collections.abc import Sequence

from sgw.contracts.api_models import Proposer
from sgw.contracts.vocab import ApprovalFunction, InitiatorKind

SYSTEM_PREFIX = "system:"
SYSTEM_LABELS = {"rule": "SGW rule", "optimiser": "SGW optimiser"}


def system_display_name(user_id: str) -> str:
    """`system:rule:ps17_pressure_floor` -> "SGW rule ps17_pressure_floor"; `system:optimiser` -> "SGW
    optimiser"."""
    kind, _, rest = user_id.removeprefix(SYSTEM_PREFIX).partition(":")
    label = SYSTEM_LABELS.get(kind, f"SGW {kind}")
    return f"{label} {rest}".strip()


def proposer(
    *,
    user_id: str,
    initiator_kind: InitiatorKind | str,
    display_name: str | None,
    function: ApprovalFunction | str | None,
) -> Proposer:
    if user_id.startswith(SYSTEM_PREFIX):
        return Proposer(
            user_id=user_id,
            display_name=system_display_name(user_id),
            function=None,
            initiator_kind=InitiatorKind(initiator_kind),
        )
    return Proposer(
        user_id=user_id,
        display_name=display_name or user_id,
        function=ApprovalFunction(function) if function else None,
        initiator_kind=InitiatorKind(initiator_kind),
    )


def owner_function(
    who: Proposer, functions_required: Sequence[ApprovalFunction | str]
) -> ApprovalFunction | None:
    if who.initiator_kind is InitiatorKind.PERSON and who.function is not None:
        return who.function
    return ApprovalFunction(functions_required[0]) if functions_required else None
