"""Approval service: proposal creation, compare-and-set approvals, material revision, withdrawal and the
single-use execution token. Transport-free: functions take a psycopg connection and plain models, and
return K3 models plus the K2 events they caused. "Authority is a DB row": the OPA decision runs first and
the 0005 triggers check the same rules again on insert (SQLSTATE 42501 -> 403, 09000 -> 412).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg import pq

from sgw.approval import audit, policy_data
from sgw.approval import repository as repo
from sgw.approval.errors import (
    ApprovalError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    PreconditionFailedError,
    UnprocessableError,
    from_db_error,
)
from sgw.approval.ledger import LedgerSink, envelope
from sgw.approval.outcome import authority_times, decision_outcome
from sgw.approval.policy import PolicyEngine, PolicyInput
from sgw.approval.proposer import owner_function, proposer
from sgw.approval.severity import QUEUE_OPEN_STATES, decision_severity
from sgw.contracts import approval as ap
from sgw.contracts.api_models import (
    ApprovalRequest,
    ApprovalResponse,
    Approver,
    ClockShift,
    ProposalCard,
    ProposalCreate,
    ProposalSummary,
    StaleProposal,
    VoidedApproval,
    WithdrawRequest,
)
from sgw.contracts.base import Contract, utc_iso
from sgw.contracts.clocks import ClockBasis, ClockWaterfall, DecisionCase, DecisionClock
from sgw.contracts.events import ApprovalRecorded, DecisionApproved, ProposalCreated, ProposalUpdated
from sgw.contracts.vocab import (
    ActionType,
    ApprovalDecision,
    ApprovalFunction,
    Classification,
    InitiatorKind,
    ProposalState,
    RiskBand,
    Tier,
    UiSeverity,
)

log = logging.getLogger("sgw.approval")
Clock = Callable[[], datetime]
EXECUTION_TOKEN_TTL_S = 60
DEFAULT_RISK_BAND = RiskBand.MODERATE
OPEN_STATES = frozenset({"proposed", "in_review"})
WITHDRAWABLE_STATES = frozenset({"draft", "proposed", "in_review", "approved", "escalated"})
REVISABLE_STATES = WITHDRAWABLE_STATES
RERUN_ACTOR = "system:agent-rerun"
UNDECIDED_STATES = frozenset({"draft", "proposed", "in_review", "escalated"})
OBSERVED_PARAMS = ("zone_id", "station_id", "destination_id", "facility_id")


def wall_clock() -> datetime:
    return datetime.now(UTC)


def etag(version: int, action_hash: str) -> str:
    return f'"{version}-{action_hash}"'


def etag_matches(if_match: str | None, version: int, action_hash: str) -> bool:
    if if_match is None:
        return True
    wanted = etag(version, action_hash)
    candidates = [c.strip() for c in if_match.split(",")]
    return any(c == "*" or c == wanted for c in candidates)


@dataclass(frozen=True)
class Principal:
    user_id: str
    functions: tuple[str, ...]
    can_approve: bool
    break_glass_eligible: bool
    on_shift: bool

    def as_input(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "functions": list(self.functions),
            "can_approve": self.can_approve,
            "on_shift": self.on_shift,
        }


@dataclass(frozen=True)
class Outcome[T]:
    value: T
    etag: str | None = None
    events: tuple[Contract, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Revision:
    params: dict[str, Any] | None = None
    target_ids: list[str] | None = None
    preconditions: dict[str, bool] | None = None
    risk_band: RiskBand | None = None
    retracted_evidence_ids: list[str] | None = None
    rationale: str | None = None


@contextmanager
def _db_errors(stale: Callable[[], PreconditionFailedError] | None = None) -> Iterator[None]:
    """Map database authority errors; a 09000 (stale version or hash) is rebuilt as the K3
    `StaleProposal` of the current row when `stale` is given (it runs after the rollback)."""
    try:
        yield
    except psycopg.Error as error:
        mapped = from_db_error(error)
        if mapped is None:
            raise
        if isinstance(mapped, PreconditionFailedError) and stale is not None:
            raise stale() from error
        raise mapped from error


def _event_key(event: Contract) -> str:
    if isinstance(event, ApprovalRecorded):
        return event.approval_id
    if isinstance(event, DecisionApproved):
        return f"{event.proposal_id}:v{event.proposal_version}:approved"
    return uuid.uuid4().hex


def _ns(value: datetime | None) -> int | None:
    return None if value is None else int(value.timestamp() * 1_000_000_000)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16].upper()}"


def load_principal(conn: psycopg.Connection[Any], user_id: str) -> Principal:
    row = repo.load_user(conn, user_id)
    if row is None:
        raise ForbiddenError(f"unknown user {user_id}", code="UNKNOWN_USER")
    return Principal(
        user_id=row["user_id"],
        functions=tuple(row["functions"]),
        can_approve=bool(row["can_approve"]),
        break_glass_eligible=bool(row["break_glass_eligible"]),
        on_shift=bool(row["on_shift"]),
    )


def material_of(row: dict[str, Any]) -> ap.MaterialFields:
    return ap.MaterialFields(
        action_type=ActionType(row["action_type"]),
        params=row["params"],
        target_ids=list(row["targets"]),
        risk_band=RiskBand(row["risk_band"]),
        preconditions=row["preconditions"],
        tier=Tier(row["tier"]),
        escalators=list(row["escalators"]),
        retracted_evidence_ids=list(row.get("retracted_evidence_ids") or []),
    )


def case_of(row: dict[str, Any]) -> DecisionCase:
    clock = DecisionClock(
        decide_by_utc=row["c_decide_by_utc"],
        decide_by_p10_utc=row["c_decide_by_p10_utc"],
        decide_by_p90_utc=row["c_decide_by_p90_utc"],
        consequence_utc=row["c_consequence_utc"],
        consequence_p10_utc=row["c_consequence_p10_utc"],
        consequence_p90_utc=row["c_consequence_p90_utc"],
        consequence_basis=ClockBasis.model_validate(row["c_consequence_basis"]),
        action_lead_time_min=row["c_action_lead_time_min"],
        lead_time_basis=ClockBasis.model_validate(row["c_lead_time_basis"]),
        clock_kind=row["c_clock_kind"],
        if_late=row["c_if_late"],
    )
    return DecisionCase(
        decision_case_id=row["c_id"],
        step=row["c_step"],
        title=row["c_title"],
        domain=row["c_domain"],
        region_id=row["c_region_id"],
        clock=clock,
        effective_decide_by_utc=row["c_effective_decide_by_utc"],
        on_critical_path=row["c_on_critical_path"],
        no_regret_share_ppm=row["c_no_regret_share_ppm"],
        no_regret_verdict=row["c_no_regret_verdict"],
        next_advisory_utc=row["c_next_advisory_utc"],
    )


def _story(case_id: str, now: datetime) -> Any:
    from sgw.models.clocks.story import case_story

    try:
        return case_story(case_id, now)
    except (OSError, KeyError, ValueError):
        return None


def same_advisory(proposed_at: datetime | None, now: datetime) -> bool:
    """A re-run rejoins an open proposal only within the advisory it was proposed under. A proposal from an
    earlier advisory is the re-planner's (revised, signatures voided) and runs out by its expiry (D8), while
    the new advisory's run proposes afresh: the agreed PS-17 story (golden path steps 3a, 4, 6, 10)."""
    if proposed_at is None:
        return False
    from sgw.models.clocks import story

    try:
        return story.advisory_at(proposed_at) == story.advisory_at(now)
    except (OSError, KeyError, ValueError):
        return False


def clock_shift(case_id: str, effective: datetime, now: datetime) -> ClockShift | None:
    """The move of the case's stored effective decide-by against the previous advisory."""
    story = _story(case_id, now)
    if story is None or story.previous_effective_decide_by_utc is None:
        return None
    shift = round((effective - story.previous_effective_decide_by_utc).total_seconds() / 60)
    if shift == 0:
        return None
    return ClockShift(
        advisory_label=story.advisory_label,
        previous_advisory_label=story.previous_advisory_label,
        previous_effective_decide_by_utc=story.previous_effective_decide_by_utc,
        shift_min=shift,
    )


def with_links(conn: psycopg.Connection[Any], case: DecisionCase, now: datetime) -> DecisionCase:
    """The stored prerequisite edges, the chain and the Timing shown; the stored verdict is kept."""
    from sgw.models.clocks.links import case_links, facts_from_rows

    facts = facts_from_rows(repo.case_graph(conn))
    if case.decision_case_id not in facts:
        return case
    links = case_links(case.decision_case_id, facts, now)
    return case.model_copy(
        update={
            "prerequisite_ids": links.blocked_by,
            "blocked_by": links.blocked_by,
            "blocks": links.blocks,
            "chain": links.chain,
            "chain_order": links.chain_order,
            "timing": links.timing,
            "timing_reason": links.timing_reason,
            "timing_basis": links.timing_basis,
        }
    )


def with_members(case: DecisionCase, now: datetime) -> DecisionCase:
    """The ensemble behind the no-regret share; the stored case row has the share only."""
    if case.no_regret_share_ppm is None:
        return case
    story = _story(case.decision_case_id, now)
    if story is None or story.members_total is None:
        return case
    return case.model_copy(
        update={"no_regret_members": story.members_needing, "ensemble_members": story.members_total}
    )


class ApprovalService:
    def __init__(
        self,
        policy: PolicyEngine,
        *,
        scenario_clock: Clock = wall_clock,
        token_clock: Clock = wall_clock,
        token_ttl_s: int = EXECUTION_TOKEN_TTL_S,
        ledger: LedgerSink | None = None,
    ) -> None:
        self.policy = policy
        self.scenario_clock = scenario_clock
        self.token_clock = token_clock
        self.token_ttl_s = token_ttl_s
        self.ledger = ledger

    def _emit(
        self, conn: psycopg.Connection[Any], row: dict[str, Any], events: Sequence[tuple[str, Contract]]
    ) -> None:
        """Queue K2 envelopes in the caller's transaction (outbox); `_drain` after commit."""
        if self.ledger is None or not events:
            return
        at = self.scenario_clock()
        classification = Classification.C2 if row["domain"] == "water" else Classification.C1
        envelopes = [
            envelope(
                payload,
                at=at,
                key=key,
                region_id=row["region_id"],
                domain=row["domain"],
                classification=classification,
            )
            for key, payload in events
        ]
        self.ledger.enqueue(conn, envelopes)

    def _audit(
        self,
        conn: psycopg.Connection[Any],
        kind: str,
        *,
        actor_id: str,
        subject: str,
        payload: dict[str, Any],
        at: datetime | None = None,
        key: str | None = None,
    ) -> None:
        """Append to the hash-chained audit log in the caller's transaction, next to `_emit`."""
        actor_type: audit.ActorType = "system" if actor_id.startswith("system:") else "user"
        if actor_id == "agent" or actor_id.startswith("agent:"):
            actor_type = "agent"
        audit.append(
            conn,
            kind=kind,
            actor_type=actor_type,
            actor_id=actor_id,
            subject=subject,
            payload=payload,
            occurred_at=at or self.scenario_clock(),
            event_key=f"{kind}:{key}" if key else None,
        )

    def _drain(self, conn: psycopg.Connection[Any]) -> None:
        """After commit only, on an idle autocommit connection; otherwise the relay drains later."""
        idle = conn.info.transaction_status == pq.TransactionStatus.IDLE
        if self.ledger is not None and conn.autocommit and idle:
            try:
                self.ledger.drain(conn)
            except Exception:
                log.warning("ledger drain after commit failed; the relay will retry", exc_info=True)

    # ---- inputs ----------------------------------------------------------------------------------------

    def _facts(
        self, conn: psycopg.Connection[Any], params: dict[str, Any], targets: Sequence[str]
    ) -> dict[str, Any]:
        """Server-side escalation facts. Unknown targets are refused; missing data escalates (fail closed);
        a client-claimed customer count can only raise the count."""
        unknown = repo.unknown_targets(conn, targets)
        if unknown:
            raise UnprocessableError(
                "unknown target ids", code="UNKNOWN_TARGET", details={"target_ids": unknown}
            )
        found = repo.target_facts(conn, targets)
        customers = int(found["customers"])
        claimed = params.get("customers_affected")
        if isinstance(claimed, int) and not isinstance(claimed, bool):
            customers = max(customers, claimed)
        return {
            "customers_affected": customers,
            "customers_unknown": int(found["customers_unknown"]) > 0,
            "critical_facility": bool(found["critical"]),
            "hazard_zone_entry": int(found["in_zone"]) > 0,
        }

    def _propose_input(
        self,
        conn: psycopg.Connection[Any],
        *,
        subject: Principal | None,
        action_type: str,
        proposed_by: str,
        initiator_kind: InitiatorKind,
        params: dict[str, Any],
        targets: Sequence[str],
    ) -> PolicyInput:
        return {
            "action": "propose",
            "subject": subject.as_input() if subject else {"user_id": proposed_by},
            "proposal": {
                "action_type": action_type,
                "proposed_by": proposed_by,
                "requested_by": proposed_by if initiator_kind is InitiatorKind.AGENT else None,
                "initiator_kind": initiator_kind.value,
                "target_ids": list(targets),
            },
            "facts": self._facts(conn, params, targets),
            "context": {
                "degraded_mode": repo.degraded_mode(conn),
                "now_ns": _ns(self.scenario_clock()),
            },
        }

    def _expires(self, tier: Tier, now: datetime) -> datetime | None:
        if tier not in ap.TIER_TTL_MIN:
            return None
        return ap.expires_at(
            now=now,
            tier=tier,
            earliest_evidence_expiry=None,
            next_forecast_issue=None,
            approver_shift_end=None,
        )

    # ---- create ----------------------------------------------------------------------------------------

    def create(
        self,
        conn: psycopg.Connection[Any],
        *,
        proposed_by: str,
        request: ProposalCreate,
        initiator_kind: InitiatorKind = InitiatorKind.PERSON,
        subject: Principal | None = None,
        incident_id: str = "INC-HELENE-2024",
        rationale: str = "",
        run_id: str | None = None,
        proposal_id: str | None = None,
    ) -> Outcome[ProposalCard]:
        if run_id is not None and proposal_id is None:
            now = self.scenario_clock()
            for found in repo.open_proposals_for(
                conn, request.decision_case_id, request.action_type.value, sorted(UNDECIDED_STATES)
            ):
                if same_advisory(found["proposed_at"], now):
                    return self._rejoin(conn, str(found["proposal_id"]), request, run_id)
        if initiator_kind is InitiatorKind.PERSON and subject is None:
            subject = load_principal(conn, proposed_by)
        with _db_errors(), conn.transaction():
            case = repo.load_case(conn, request.decision_case_id)
            if case is None:
                raise NotFoundError(
                    f"decision case {request.decision_case_id} not found", code="CASE_NOT_FOUND"
                )
            params: dict[str, Any] = dict(request.params)
            payload = self._propose_input(
                conn,
                subject=subject,
                action_type=request.action_type.value,
                proposed_by=proposed_by,
                initiator_kind=initiator_kind,
                params=params,
                targets=request.target_ids,
            )
            decision = self.policy.propose(payload)
            if not decision.allow:
                raise ForbiddenError(
                    "the approval policy does not allow this proposal",
                    code="POLICY_DENIED",
                    details={"deny": list(decision.deny)},
                )
            c = decision.classification
            tier = Tier(c.tier)
            band = repo.max_risk_band(conn, request.target_ids) or DEFAULT_RISK_BAND.value
            material = ap.MaterialFields(
                action_type=request.action_type,
                params=params,
                target_ids=list(request.target_ids),
                risk_band=RiskBand(band),
                preconditions={},
                tier=tier,
                escalators=list(c.escalators),
            )
            pid = proposal_id or _new_id("PRP")
            row = {
                "proposal_id": pid,
                "decision_case_id": request.decision_case_id,
                "incident_id": incident_id,
                "action_type": material.action_type.value,
                "params": material.params,
                "targets": material.target_ids,
                "risk_band": material.risk_band.value,
                "preconditions": material.preconditions,
                "tier": tier.value,
                "required_functions": list(c.required_functions),
                "escalators": material.escalators,
                "state": "draft" if tier is Tier.T1 else "proposed",
                "proposal_version": 1,
                "action_hash": ap.action_hash(material, c.policy_version),
                "policy_version": c.policy_version,
                "snapshot_id": None,
                "evidence_ids": sorted(set(request.evidence_ids)),
                "initiator_kind": initiator_kind.value,
                "proposed_by": proposed_by,
                "run_id": run_id,
                "region_id": case["c_region_id"],
                "domain": case["c_domain"],
                "rationale": rationale,
                "expires_at": self._expires(tier, self.scenario_clock()),
            }
            repo.insert_proposal(conn, row)
            self._audit(
                conn,
                "proposal_created",
                actor_id=proposed_by,
                subject=pid,
                payload={
                    "proposal_version": 1,
                    "action_hash": row["action_hash"],
                    "action_type": row["action_type"],
                    "tier": row["tier"],
                    "required_functions": row["required_functions"],
                    "escalators": row["escalators"],
                    "policy_version": row["policy_version"],
                    "initiator_kind": row["initiator_kind"],
                },
                key=pid,
            )
            repo.add_delta(conn, pid, 1, True, {"created": True, "fields": [], "by": proposed_by})
            card = self.card(conn, pid)
            event = ProposalCreated(
                proposal_id=pid,
                decision_case_id=card.decision_case_id,
                action_type=card.action_type,
                tier=card.tier,
                proposal_version=1,
                action_hash=card.action_hash,
                proposed_by=proposed_by,
                decide_by_utc=card.decide_by_utc,
                clock_kind=card.case.clock.clock_kind,
            )
            self._emit(conn, row, [(f"{pid}:v1:created", event)])
        self._drain(conn)
        return Outcome(card, etag(1, card.action_hash), (event,))

    def _rejoin(
        self, conn: psycopg.Connection[Any], proposal_id: str, request: ProposalCreate, run_id: str
    ) -> Outcome[ProposalCard]:
        """One open proposal per decision case and action for agent runs: a later run that proposes the same
        action returns the open proposal, or revises it when its parameters or targets changed (the
        re-planner's basis keys already on the proposal are kept, so an unchanged re-run voids nothing)."""
        card = self.card(conn, proposal_id)
        params = {**card.params, **dict(request.params)}
        targets = list(request.target_ids)
        if params == card.params and sorted(targets) == sorted(card.target_ids):
            return Outcome(card, etag(card.proposal_version, card.action_hash))
        return self.revise(
            conn,
            actor=RERUN_ACTOR,
            proposal_id=proposal_id,
            change=Revision(params=params, target_ids=targets),
            reason=f"run {run_id} proposed the same action again with changed parameters or targets",
        )

    # ---- read ------------------------------------------------------------------------------------------

    def _approvers(self, conn: psycopg.Connection[Any], ids: Sequence[str]) -> dict[str, list[Approver]]:
        out: dict[str, list[Approver]] = {pid: [] for pid in ids}
        for a in repo.current_approvals(conn, ids):
            out[a["proposal_id"]].append(
                Approver(
                    approver_id=a["approver_id"],
                    function=a["function"],
                    decision=a["decision"],
                    at=a["signed_at"],
                )
            )
        return out

    def _observed(self, row: dict[str, Any]) -> UiSeverity | None:
        """Severe while anything the decision acts on (a target, or the zone, station or facility its
        parameters name) sits in a water zone below the state floor at the scenario time."""
        if ProposalState(row["state"]) in QUEUE_OPEN_STATES:
            return None
        from sgw.api.readmodels.water import below_floor_ids

        params = row["params"] or {}
        concerned = {*row["targets"], *(str(params[k]) for k in OBSERVED_PARAMS if params.get(k))}
        return UiSeverity.SEVERE if concerned & below_floor_ids(self.scenario_clock()) else None

    def _summary_fields(
        self, row: dict[str, Any], approvals: list[Approver], decided_at: datetime | None
    ) -> dict[str, Any]:
        who = proposer(
            user_id=row["proposed_by"],
            initiator_kind=row["initiator_kind"],
            display_name=row["u_display_name"],
            function=row["u_function"],
        )
        return {
            "proposal_id": row["proposal_id"],
            "decision_case_id": row["decision_case_id"],
            "action_type": row["action_type"],
            "title": row["c_title"],
            "tier": row["tier"],
            "state": row["state"],
            "proposal_version": row["proposal_version"],
            "action_hash": row["action_hash"],
            "decide_by_utc": row["c_decide_by_utc"],
            "effective_decide_by_utc": row["c_effective_decide_by_utc"],
            "on_critical_path": row["c_on_critical_path"],
            "functions_required": row["required_functions"],
            "approvals": approvals,
            "expires_at": row["expires_at"],
            "severity": decision_severity(
                state=row["state"],
                effective_decide_by_utc=row["c_effective_decide_by_utc"],
                on_critical_path=row["c_on_critical_path"],
                now=self.scenario_clock(),
                observed=self._observed(row),
            ),
            "proposed_by": who,
            "owner_function": owner_function(who, row["required_functions"]),
            "clock_shift": clock_shift(row["c_id"], row["c_effective_decide_by_utc"], self.scenario_clock()),
            "outcome": decision_outcome(
                state=row["state"],
                effective_decide_by_utc=row["c_effective_decide_by_utc"],
                decided_at=decided_at,
            ),
            "decided_at_utc": decided_at,
        }

    def summaries(
        self, conn: psycopg.Connection[Any], states: Sequence[str] | None = None
    ) -> list[ProposalSummary]:
        rows = repo.list_proposals(conn, states, known_by=self.scenario_clock())
        ids = [r["proposal_id"] for r in rows]
        approvals = self._approvers(conn, ids)
        decided = authority_times(conn, ids, self.scenario_clock())
        return [
            ProposalSummary(
                **self._summary_fields(r, approvals[r["proposal_id"]], decided.get(r["proposal_id"]))
            )
            for r in rows
        ]

    def card(self, conn: psycopg.Connection[Any], proposal_id: str) -> ProposalCard:
        row = repo.get_proposal(conn, proposal_id)
        if row is None:
            raise NotFoundError(f"proposal {proposal_id} not found", code="PROPOSAL_NOT_FOUND")
        approvals = self._approvers(conn, [proposal_id])[proposal_id]
        decided_at = authority_times(conn, [proposal_id], self.scenario_clock()).get(proposal_id)
        env = repo.envelope_for(conn, proposal_id)
        bg = repo.break_glass_for(conn, proposal_id)
        return ProposalCard(
            **self._summary_fields(row, approvals, decided_at),
            case=with_links(conn, with_members(case_of(row), self.scenario_clock()), self.scenario_clock()),
            voided_approvals=[
                VoidedApproval(
                    approver_id=v["approver_id"],
                    function=v["function"],
                    decision=v["decision"],
                    at=v["created_at"],
                    proposal_version=v["proposal_version"],
                    voided_by_version=v["voided_by_version"],
                    voided_at=v["voided_at"],
                    reason=v["voided_reason"],
                )
                for v in repo.voided_approvals(conn, proposal_id)
            ],
            revision_reason=repo.version_reason(conn, proposal_id, row["proposal_version"])
            if row["proposal_version"] > 1
            else None,
            params=row["params"],
            target_ids=list(row["targets"]),
            preconditions=row["preconditions"],
            escalators=list(row["escalators"]),
            evidence_ids=list(row["evidence_ids"]),
            rationale=row["rationale"],
            policy_version=row["policy_version"],
            envelope=ap.Envelope(
                envelope_id=env["envelope_id"],
                proposal_id=env["proposal_id"],
                bounds=env["bounds"],
                valid_until_utc=env["valid_until"],
            )
            if env
            else None,
            break_glass=ap.BreakGlass(
                proposal_id=bg["proposal_id"],
                ic_id=bg["ic_id"],
                reason=bg["reason"],
                used_at_utc=bg["used_at"],
                cosign_due_utc=bg["cosign_due"],
                cosigned_by=bg["cosigned_by"],
                cosigned_at_utc=bg["cosigned_at"],
                flagged_for_after_action=bg["flagged"],
            )
            if bg
            else None,
        )

    def card_with_etag(self, conn: psycopg.Connection[Any], proposal_id: str) -> Outcome[ProposalCard]:
        card = self.card(conn, proposal_id)
        return Outcome(card, etag(card.proposal_version, card.action_hash))

    def clock(self, conn: psycopg.Connection[Any], proposal_id: str) -> ClockWaterfall:
        card = self.card(conn, proposal_id)
        clk = card.case.clock
        return ClockWaterfall(
            decision_case_id=card.decision_case_id,
            consequence_utc=clk.consequence_utc,
            consequence_range_utc=(clk.consequence_p10_utc, clk.consequence_p90_utc),
            consequence_basis=clk.consequence_basis,
            action_lead_time_min=clk.action_lead_time_min,
            lead_time_basis=clk.lead_time_basis,
            decide_by_utc=clk.decide_by_utc,
            effective_decide_by_utc=card.case.effective_decide_by_utc,
            bound_by_case_id=repo.bound_by_case(conn, card.decision_case_id),
        )

    # ---- approve or reject (CAS) -----------------------------------------------------------------------

    def _stale(
        self, conn: psycopg.Connection[Any], row: dict[str, Any], seen_version: int
    ) -> PreconditionFailedError:
        body = StaleProposal(
            current_version=row["proposal_version"],
            current_action_hash=row["action_hash"],
            changed_fields=repo.changed_fields_since(conn, row["proposal_id"], seen_version),
        )
        return PreconditionFailedError(
            "the proposal changed since you saw it; review the new version",
            details=body.model_dump(mode="json"),
            stale=body,
        )

    def _stale_now(
        self, conn: psycopg.Connection[Any], proposal_id: str, seen_version: int
    ) -> Callable[[], PreconditionFailedError]:
        def build() -> PreconditionFailedError:
            row = repo.get_proposal(conn, proposal_id)
            if row is None:
                return PreconditionFailedError("the proposal changed", code="STALE_PROPOSAL")
            return self._stale(conn, row, seen_version)

        return build

    @staticmethod
    def _sign_as(principal: Principal, required: Sequence[str], signed: set[str]) -> str:
        for fn in required:
            if fn in principal.functions and fn not in signed:
                return fn
        for fn in required:
            if fn in principal.functions:
                return fn
        return principal.functions[0] if principal.functions else ""

    def decide(
        self,
        conn: psycopg.Connection[Any],
        *,
        user_id: str,
        proposal_id: str,
        request: ApprovalRequest,
        if_match: str | None = None,
    ) -> Outcome[ApprovalResponse]:
        principal = load_principal(conn, user_id)
        expired = False
        events: list[Contract] = []
        stale = self._stale_now(conn, proposal_id, request.proposal_version)
        with _db_errors(stale), conn.transaction():
            row = repo.lock_proposal(conn, proposal_id)
            if row is None:
                raise NotFoundError(f"proposal {proposal_id} not found", code="PROPOSAL_NOT_FOUND")
            version, current_hash = row["proposal_version"], row["action_hash"]
            if not etag_matches(if_match, version, current_hash):
                raise self._stale(conn, row, min(request.proposal_version, version))
            now = self.scenario_clock()
            if row["state"] in OPEN_STATES and row["expires_at"] is not None and now >= row["expires_at"]:
                repo.set_state(conn, proposal_id, "expired")
                expired = True
            elif row["state"] not in OPEN_STATES:
                raise ConflictError(
                    f"proposal is {row['state']}; it no longer takes decisions",
                    code="PROPOSAL_NOT_OPEN",
                    details={"state": row["state"]},
                )
            elif request.proposal_version != version or request.action_hash != current_hash:
                raise self._stale(conn, row, request.proposal_version)
            else:
                outcome = self._record(conn, row, principal, request, now)
                events.extend(outcome.events)
                self._emit(conn, row, [(_event_key(e), e) for e in outcome.events])
        if not expired:
            self._drain(conn)
        if expired:
            raise ConflictError(
                "the approval window has closed", code="PROPOSAL_EXPIRED", details={"state": "expired"}
            )
        return Outcome(outcome.value, outcome.etag, tuple(events))

    def _record(
        self,
        conn: psycopg.Connection[Any],
        row: dict[str, Any],
        principal: Principal,
        request: ApprovalRequest,
        now: datetime,
    ) -> Outcome[ApprovalResponse]:
        pid = row["proposal_id"]
        current = repo.current_approvals(conn, [pid])
        required = list(row["required_functions"])
        signed = {a["function"] for a in current if a["decision"] == "approve"}
        function = self._sign_as(principal, required, signed)
        payload: PolicyInput = {
            "action": "approve",
            "subject": principal.as_input(),
            "proposal": {
                "action_type": row["action_type"],
                "proposed_by": row["proposed_by"],
                "requested_by": row["proposed_by"] if row["initiator_kind"] == "agent" else None,
                "initiator_kind": row["initiator_kind"],
                "target_ids": list(row["targets"]),
                "tier": row["tier"],
                "required_functions": required,
                "state": row["state"],
                "expires_at_ns": _ns(row["expires_at"]),
            },
            "context": {"degraded_mode": repo.degraded_mode(conn), "now_ns": _ns(now)},
            "approval": {"decision": request.decision, "function": function, "evidence_oldest_age_s": None},
            "approvals": [
                {"approver_id": a["approver_id"], "function": a["function"], "decision": a["decision"]}
                for a in current
            ],
        }
        decision = self.policy.approve(payload)
        if not decision.allow:
            raise ForbiddenError(
                "the approval policy denies this decision",
                code="POLICY_DENIED",
                details={"deny": list(decision.deny)},
            )
        approval_id = _new_id("APR")
        repo.insert_approval(
            conn,
            {
                "approval_id": approval_id,
                "proposal_id": pid,
                "proposal_version": row["proposal_version"],
                "action_hash": row["action_hash"],
                "approver_id": principal.user_id,
                "function": function,
                "decision": request.decision,
                "reason_code": request.reason_code,
                "note": request.note,
                "snapshot_id_seen": row["snapshot_id"],
                "evidence_oldest_age_s": None,
            },
        )
        self._audit(
            conn,
            "approval_recorded",
            actor_id=principal.user_id,
            subject=pid,
            payload={
                "approval_id": approval_id,
                "proposal_version": row["proposal_version"],
                "action_hash": row["action_hash"],
                "function": function,
                "decision": request.decision,
                "reason_code": request.reason_code,
                **({"reason": request.note} if request.decision == "reject" and request.note else {}),
            },
            at=now,
            key=approval_id,
        )
        events: list[Contract] = [
            ApprovalRecorded(
                approval_id=approval_id,
                proposal_id=pid,
                proposal_version=row["proposal_version"],
                action_hash=row["action_hash"],
                approver_id=principal.user_id,
                function=ApprovalFunction(function),
                decision=ApprovalDecision(request.decision),
                reason_code=request.reason_code,
            )
        ]
        if request.decision == "reject":
            state = "rejected"
            repo.drop_unburned_token(conn, pid)
        elif decision.complete:
            state = "approved"
            repo.set_state(conn, pid, state)
            self._issue_token(conn, pid, row["proposal_version"], row["action_hash"])
            approvers = sorted(
                {a["approver_id"] for a in current if a["decision"] == "approve"} | {principal.user_id}
            )
            events.append(
                DecisionApproved(
                    decision_case_id=row["decision_case_id"],
                    proposal_id=pid,
                    proposal_version=row["proposal_version"],
                    action_hash=row["action_hash"],
                    tier=Tier(row["tier"]),
                    approver_ids=approvers,
                )
            )
        else:
            state = "in_review"
        repo.set_state(conn, pid, state)
        remaining = (
            [ApprovalFunction(f) for f in decision.remaining_functions] if state == "in_review" else []
        )
        response = ApprovalResponse(
            approval_id=approval_id, proposal_state=ProposalState(state), remaining_functions=remaining
        )
        return Outcome(response, etag(row["proposal_version"], row["action_hash"]), tuple(events))

    # ---- withdraw --------------------------------------------------------------------------------------

    def withdraw(
        self,
        conn: psycopg.Connection[Any],
        *,
        user_id: str,
        proposal_id: str,
        request: WithdrawRequest,
        if_match: str | None = None,
    ) -> Outcome[ProposalSummary]:
        principal = load_principal(conn, user_id)
        with _db_errors(), conn.transaction():
            row = repo.lock_proposal(conn, proposal_id)
            if row is None:
                raise NotFoundError(f"proposal {proposal_id} not found", code="PROPOSAL_NOT_FOUND")
            if not etag_matches(if_match, row["proposal_version"], row["action_hash"]):
                raise self._stale(conn, row, row["proposal_version"])
            if row["state"] not in WITHDRAWABLE_STATES:
                raise ConflictError(
                    f"proposal is {row['state']} and cannot be withdrawn",
                    code="PROPOSAL_NOT_OPEN",
                    details={"state": row["state"]},
                )
            version = row["proposal_version"]
            if row["state"] == "approved" and row["tier"] == "T3":
                raise ConflictError(
                    "an approved T3 action is rescinded by a new T3 proposal (or IC break-glass)",
                    code="RESCIND_NEEDS_T3",
                    details={"state": "approved"},
                )
            if principal.user_id == row["proposed_by"]:
                repo.drop_unburned_token(conn, proposal_id)
                repo.set_state(conn, proposal_id, "withdrawn")
                change: dict[str, Any] = {"withdrawn_by": principal.user_id, "reason": request.reason}
                fields, key = ["state"], f"{proposal_id}:v{version}:withdrawn"
            else:
                own = [
                    a
                    for a in repo.current_approvals(conn, [proposal_id])
                    if a["approver_id"] == principal.user_id and a["decision"] == "approve"
                ]
                if not own:
                    raise ForbiddenError(
                        "only the proposer, or an approver for their own signature, may withdraw",
                        code="NOT_ENTITLED",
                    )
                if row["state"] != "in_review":
                    raise ConflictError(
                        f"proposal is {row['state']}; a signature can only be withdrawn while in review",
                        code="PROPOSAL_NOT_OPEN",
                        details={"state": row["state"]},
                    )
                approval_id = str(own[0]["approval_id"])
                repo.delete_approval(conn, approval_id, principal.user_id)
                left = repo.current_approvals(conn, [proposal_id])
                repo.set_state(conn, proposal_id, "in_review" if left else "proposed")
                change = {
                    "signature_withdrawn": approval_id,
                    "function": own[0]["function"],
                    "by": principal.user_id,
                    "reason": request.reason,
                }
                fields, key = ["approvals"], f"{proposal_id}:v{version}:unsign:{approval_id}"
            repo.add_delta(conn, proposal_id, version, False, change)
            self._audit(
                conn,
                "proposal_withdrawn" if "withdrawn_by" in change else "approval_withdrawn",
                actor_id=principal.user_id,
                subject=proposal_id,
                payload={"proposal_version": version, "action_hash": row["action_hash"], **change},
            )
            summary = self.summary(conn, proposal_id)
            event = ProposalUpdated(
                proposal_id=proposal_id,
                material=False,
                proposal_version=version,
                action_hash=row["action_hash"],
                changed_fields=fields,
                reason=f"withdrawn: {request.reason}",
            )
            self._emit(conn, row, [(key, event)])
        self._drain(conn)
        return Outcome(summary, etag(row["proposal_version"], row["action_hash"]), (event,))

    def summary(self, conn: psycopg.Connection[Any], proposal_id: str) -> ProposalSummary:
        card = self.card(conn, proposal_id)
        return ProposalSummary(**{k: getattr(card, k) for k in ProposalSummary.model_fields})

    # ---- revise (material change voids approvals) ------------------------------------------------------

    def revise(
        self,
        conn: psycopg.Connection[Any],
        *,
        actor: str,
        proposal_id: str,
        change: Revision,
        reason: str,
        if_match: str | None = None,
    ) -> Outcome[ProposalCard]:
        """Change a proposal. Only its proposer or a system re-planner (`system:*`) may revise, the policy
        must still allow the revised proposal, and `If-Match` (when given) must name the current version."""
        with _db_errors(), conn.transaction():
            row = repo.lock_proposal(conn, proposal_id)
            if row is None:
                raise NotFoundError(f"proposal {proposal_id} not found", code="PROPOSAL_NOT_FOUND")
            if actor != row["proposed_by"] and not actor.startswith("system:"):
                raise ForbiddenError("only the proposer or the re-planner may revise", code="NOT_ENTITLED")
            if not etag_matches(if_match, row["proposal_version"], row["action_hash"]):
                raise self._stale(conn, row, row["proposal_version"])
            if row["state"] not in REVISABLE_STATES:
                raise ConflictError(
                    f"proposal is {row['state']} and cannot change",
                    code="PROPOSAL_NOT_OPEN",
                    details={"state": row["state"]},
                )
            old = material_of({**row, "retracted_evidence_ids": repo.retracted_evidence(conn, proposal_id)})
            params = dict(change.params) if change.params is not None else dict(old.params)
            targets = list(change.target_ids) if change.target_ids is not None else list(old.target_ids)
            payload = self._propose_input(
                conn,
                subject=None,
                action_type=old.action_type.value,
                proposed_by=row["proposed_by"],
                initiator_kind=InitiatorKind(row["initiator_kind"]),
                params=params,
                targets=targets,
            )
            decision = self.policy.propose(payload)
            if not decision.allow:
                raise ForbiddenError(
                    "the approval policy does not allow the revised proposal",
                    code="POLICY_DENIED",
                    details={"deny": list(decision.deny)},
                )
            c = decision.classification
            policy_owned = set(policy_data.ESCALATOR_FLAGS) | set(policy_data.COMPUTED_ESCALATORS)
            try:
                new = ap.MaterialFields(
                    action_type=old.action_type,
                    params=params,
                    target_ids=targets,
                    risk_band=change.risk_band or old.risk_band,
                    preconditions=change.preconditions
                    if change.preconditions is not None
                    else dict(old.preconditions),
                    tier=Tier(c.tier),
                    escalators=sorted(
                        {e for e in old.escalators if e not in policy_owned} | set(c.escalators)
                    ),
                    retracted_evidence_ids=sorted(
                        set(old.retracted_evidence_ids) | set(change.retracted_evidence_ids or [])
                    ),
                )
            except ValueError as error:
                raise UnprocessableError(str(error), code="INVALID_REVISION") from error
            fields = ap.material_diff(old, new)
            rationale = change.rationale if change.rationale is not None else row["rationale"]
            if not fields:
                repo.add_delta(
                    conn,
                    proposal_id,
                    row["proposal_version"],
                    False,
                    {"by": actor, "reason": reason, "rationale_changed": rationale != row["rationale"]},
                )
                if rationale != row["rationale"]:
                    repo.set_rationale(conn, proposal_id, rationale)
                voided: list[str] = []
                version, new_hash = row["proposal_version"], row["action_hash"]
            else:
                version = row["proposal_version"] + 1
                new_hash = ap.action_hash(new, c.policy_version)
                required = list(c.required_functions)
                repo.update_material(
                    conn,
                    {
                        "proposal_id": proposal_id,
                        "action_type": new.action_type.value,
                        "params": new.params,
                        "targets": new.target_ids,
                        "risk_band": new.risk_band.value,
                        "preconditions": new.preconditions,
                        "tier": new.tier.value,
                        "required_functions": required,
                        "escalators": new.escalators,
                        "state": "draft" if new.tier is Tier.T1 else "proposed",
                        "proposal_version": version,
                        "action_hash": new_hash,
                        "policy_version": c.policy_version,
                        "evidence_ids": sorted(set(row["evidence_ids"]) - set(new.retracted_evidence_ids)),
                        "rationale": rationale,
                        "expires_at": self._expires(new.tier, self.scenario_clock()),
                    },
                    row["proposal_version"],
                )
                voided = repo.void_approvals(conn, proposal_id, version)
                repo.drop_unburned_token(conn, proposal_id)
                repo.add_delta(
                    conn,
                    proposal_id,
                    version,
                    True,
                    {
                        "by": actor,
                        "reason": reason,
                        "fields": fields,
                        "from_version": row["proposal_version"],
                        "retracted_evidence_ids": new.retracted_evidence_ids,
                    },
                )
            card = self.card(conn, proposal_id)
            event = ProposalUpdated(
                proposal_id=proposal_id,
                material=bool(fields),
                proposal_version=version,
                action_hash=new_hash,
                changed_fields=fields,
                voided_approval_ids=voided,
                decide_by_utc=card.decide_by_utc,
                reason=reason,
            )
            key = f"{proposal_id}:v{version}:" + ("material" if fields else f"note-{uuid.uuid4().hex}")
            self._audit(
                conn,
                "proposal_revised",
                actor_id=actor,
                subject=proposal_id,
                payload={
                    "from_version": row["proposal_version"],
                    "proposal_version": version,
                    "action_hash": new_hash,
                    "material": bool(fields),
                    "changed_fields": fields,
                    "voided_approval_ids": voided,
                    "reason": reason,
                },
            )
            self._emit(conn, row, [(key, event)])
        self._drain(conn)
        return Outcome(card, etag(version, new_hash), (event,))

    # ---- execution token -------------------------------------------------------------------------------

    def _issue_token(
        self, conn: psycopg.Connection[Any], proposal_id: str, version: int, action_hash: str
    ) -> str:
        repo.drop_unburned_token(conn, proposal_id)
        expires = self.token_clock() + timedelta(seconds=self.token_ttl_s)
        token_id = repo.insert_token(conn, proposal_id, version, action_hash, expires)
        self._audit(
            conn,
            "execution_token_issued",
            actor_id="system:approval",
            subject=proposal_id,
            payload={
                "token_id": token_id,
                "proposal_version": version,
                "action_hash": action_hash,
                "expires_at_utc": utc_iso(expires),
            },
            key=token_id,
        )
        return token_id

    def reissue_token(self, conn: psycopg.Connection[Any], proposal_id: str) -> str:
        """A fresh 60 s token for an approved, not yet executed proposal (the previous one expired)."""
        with _db_errors(), conn.transaction():
            row = repo.lock_proposal(conn, proposal_id)
            if row is None:
                raise NotFoundError(f"proposal {proposal_id} not found", code="PROPOSAL_NOT_FOUND")
            if row["state"] != "approved":
                raise ConflictError(f"proposal is {row['state']}", code="PROPOSAL_NOT_APPROVED")
            return self._issue_token(conn, proposal_id, row["proposal_version"], row["action_hash"])

    def burn(
        self,
        conn: psycopg.Connection[Any],
        *,
        token_id: str,
        proposal_id: str,
        proposal_version: int,
        action_hash: str,
        channel: str = "work_management",
    ) -> str:
        """Burn the token once, atomically, bound to the approved version and hash; returns the effect id.
        The proposal id is the idempotency key of the effect."""
        now = self.token_clock()
        with _db_errors(), conn.transaction():
            row = repo.lock_proposal(conn, proposal_id)
            if row is None:
                raise NotFoundError(f"proposal {proposal_id} not found", code="PROPOSAL_NOT_FOUND")
            ok = repo.burn_token(
                conn,
                {
                    "now": now,
                    "token_id": token_id,
                    "proposal_id": proposal_id,
                    "version": proposal_version,
                    "action_hash": action_hash,
                },
            )
            if not ok:
                raise self._token_refusal(conn, row, token_id, proposal_version, action_hash, now)
            effect_id = f"EFF-{proposal_id}"
            repo.set_state(conn, proposal_id, "executed")
            repo.insert_effect(conn, effect_id, proposal_id, channel, token_id)
            self._audit(
                conn,
                "execution_token_burned",
                actor_id="system:approval",
                subject=proposal_id,
                payload={
                    "token_id": token_id,
                    "proposal_version": proposal_version,
                    "action_hash": action_hash,
                    "effect_id": effect_id,
                    "channel": channel,
                },
                at=self.scenario_clock(),
                key=token_id,
            )
        return effect_id

    def _token_refusal(
        self,
        conn: psycopg.Connection[Any],
        row: dict[str, Any],
        token_id: str,
        version: int,
        action_hash: str,
        now: datetime,
    ) -> ApprovalError:
        token = repo.token_for(conn, row["proposal_id"])
        if token is None or token["token_id"] != token_id:
            return ForbiddenError("no such execution token for this proposal", code="TOKEN_UNKNOWN")
        if token["burned_at"] is not None:
            return ConflictError("the execution token was already used", code="TOKEN_BURNED")
        if (
            version != row["proposal_version"]
            or action_hash != row["action_hash"]
            or token["action_hash"] != row["action_hash"]
            or token["proposal_version"] != row["proposal_version"]
        ):
            return PreconditionFailedError(
                "the token is bound to another proposal version or hash", code="TOKEN_STALE"
            )
        if token["expires_at"] <= now:
            return ConflictError("the execution token expired", code="TOKEN_EXPIRED")
        return ConflictError(f"proposal is {row['state']}; not executable", code="PROPOSAL_NOT_APPROVED")

    def expire_due(self, conn: psycopg.Connection[Any]) -> list[str]:
        with conn.transaction():
            return repo.expire_due(conn, self.scenario_clock())
