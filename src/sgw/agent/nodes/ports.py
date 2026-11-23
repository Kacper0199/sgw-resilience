"""Proposal port: how the spine drafts a proposal and later asks whether it may execute.

Authority is a DB row (PLAN 2.4): the graph never creates an approval and never trusts the value a client
passes when it resumes the interrupt; `execute` asks the port, which reads the approval state. The tier and
required functions come from the approval policy (WP-09a's Python twin of `policy/approval.rego`), not from
the graph. `ApprovalServicePort` drafts through the approval service in the run's database;
`InMemoryProposalPort` mirrors it for replay tests and the keyless demo.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import psycopg

from sgw.approval import repository as approval_repo
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.contracts import approval as ap
from sgw.contracts.api_models import ProposalCreate
from sgw.contracts.vocab import ActionType, InitiatorKind, RiskBand, Tier
from sgw.contracts.wire import ApprovalRequiredPayload


class PolicyDenied(Exception):
    def __init__(self, deny: tuple[str, ...]) -> None:
        super().__init__(f"approval policy denied the proposal: {', '.join(deny)}")
        self.deny = deny


TAINT_NOTE = (
    "Tainted run: untrusted free text was present; it was quarantined and is not evidence for this action."
)


def with_taint_note(rationale: str, tainted: bool) -> str:
    return f"{TAINT_NOTE} {rationale}".strip() if tainted else rationale


@dataclass(frozen=True)
class DraftResult:
    payload: ApprovalRequiredPayload
    escalators: tuple[str, ...]
    base_tier: Tier


class ProposalPort(Protocol):
    def draft(
        self,
        request: ProposalCreate,
        *,
        proposed_by: str,
        rationale: str,
        run_id: str,
        facts: dict[str, Any],
        tainted: bool = False,
    ) -> DraftResult: ...

    def approval_state(self, proposal_id: str) -> tuple[str, int, str]: ...

    def record_effect(self, proposal_id: str, run_id: str) -> str: ...


@dataclass
class InMemoryProposalPort:
    policy: ReferencePolicy = field(default_factory=ReferencePolicy)
    proposals: dict[str, dict[str, Any]] = field(default_factory=dict)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    effects: list[dict[str, Any]] = field(default_factory=list)

    def draft(
        self,
        request: ProposalCreate,
        *,
        proposed_by: str,
        rationale: str,
        run_id: str,
        facts: dict[str, Any],
        tainted: bool = False,
    ) -> DraftResult:
        payload = {
            "action": "propose",
            "subject": {"user_id": proposed_by},
            "proposal": {
                "action_type": request.action_type.value,
                "proposed_by": proposed_by,
                "requested_by": proposed_by,
                "initiator_kind": InitiatorKind.AGENT.value,
                "target_ids": list(request.target_ids),
            },
            "facts": facts,
            "context": {"degraded_mode": "normal"},
        }
        decision = self.policy.propose(payload)
        if not decision.allow:
            raise PolicyDenied(decision.deny)
        c = decision.classification
        tier = Tier(c.tier)
        material = ap.MaterialFields(
            action_type=request.action_type,
            params=request.model_dump(mode="json")["params"],
            target_ids=list(request.target_ids),
            risk_band=RiskBand.HIGH,
            preconditions={},
            tier=tier,
            escalators=list(c.escalators),
        )
        action_hash = ap.action_hash(material, c.policy_version)
        pid = "PRP-" + hashlib.sha256(f"{run_id}:{action_hash}".encode()).hexdigest()[:12].upper()
        self.proposals[pid] = {
            "request": request.model_dump(mode="json"),
            "state": "proposed",
            "version": 1,
            "action_hash": action_hash,
            "rationale": with_taint_note(rationale, tainted),
            "run_id": run_id,
            "tainted": tainted,
        }
        return DraftResult(
            payload=ApprovalRequiredPayload(
                proposal_id=pid,
                proposal_version=1,
                action_hash=action_hash,
                tier=tier,
                functions_required=list(c.required_functions),  # type: ignore[arg-type]
                tainted=tainted,
            ),
            escalators=c.escalators,
            base_tier=Tier(c.base_tier),
        )

    def approval_state(self, proposal_id: str) -> tuple[str, int, str]:
        p = self.proposals[proposal_id]
        return str(p["state"]), int(p["version"]), str(p["action_hash"])

    def record_effect(self, proposal_id: str, run_id: str) -> str:
        effect_id = f"EFF-{proposal_id}-{len(self.effects) + 1}"
        self.effects.append({"effect_id": effect_id, "proposal_id": proposal_id, "run_id": run_id})
        return effect_id


@dataclass
class ApprovalServicePort:
    """Drafts through WP-09a's service (OPA or reference policy, DB triggers, outbox) in one connection per
    call: initiator kind `agent`, proposed on behalf of the run's user, recorded with the run id. Facts are
    computed server-side by the service from its own tables."""

    connect: Callable[[], psycopg.Connection[Any]]
    service: ApprovalService

    def draft(
        self,
        request: ProposalCreate,
        *,
        proposed_by: str,
        rationale: str,
        run_id: str,
        facts: dict[str, Any],
        tainted: bool = False,
    ) -> DraftResult:
        with self.connect() as conn:
            outcome = self.service.create(
                conn,
                proposed_by=proposed_by,
                request=request,
                initiator_kind=InitiatorKind.AGENT,
                rationale=with_taint_note(rationale, tainted),
                run_id=run_id,
            )
        card = outcome.value
        return DraftResult(
            payload=ApprovalRequiredPayload(
                proposal_id=card.proposal_id,
                proposal_version=card.proposal_version,
                action_hash=card.action_hash,
                tier=card.tier,
                functions_required=list(card.functions_required),
                tainted=tainted,
            ),
            escalators=tuple(card.escalators),
            base_tier=card.tier,
        )

    def approval_state(self, proposal_id: str) -> tuple[str, int, str]:
        with self.connect() as conn:
            card = self.service.card(conn, proposal_id)
        return card.state.value, card.proposal_version, card.action_hash

    def record_effect(self, proposal_id: str, run_id: str) -> str:
        return burn_execution_token(self.connect, self.service, proposal_id)


def burn_execution_token(
    connect: Callable[[], psycopg.Connection[Any]],
    service: ApprovalService,
    proposal_id: str,
    channel: str = "work_management",
) -> str:
    """Execute an approved proposal by burning its execution token through the approval service (bound to
    the approved version and hash) and return the effect id. The token from the approval lives 60 s, so an
    expired or missing one is reissued first. Idempotent: an executed proposal returns its effect id."""
    with connect() as conn:
        card = service.card(conn, proposal_id)
        if card.state.value == "executed":
            return f"EFF-{proposal_id}"
        token = approval_repo.token_for(conn, proposal_id)
        usable = (
            token is not None and token["burned_at"] is None and token["expires_at"] > service.token_clock()
        )
        token_id = str(token["token_id"]) if usable and token else service.reissue_token(conn, proposal_id)
        return service.burn(
            conn,
            token_id=token_id,
            proposal_id=proposal_id,
            proposal_version=card.proposal_version,
            action_hash=card.action_hash,
            channel=channel,
        )


EXECUTED_STATES = frozenset({"approved", "executed"})


ACTION_FOR_CASE: dict[str, ActionType] = {"DC-D2-CREWS-AIK": ActionType.PREPOSITION_CREWS}
