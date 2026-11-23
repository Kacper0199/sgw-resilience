"""Break-glass on a T3 action (PLAN section 2, O-04): the IC alone, with a mandatory reason, approves the
current version; a co-sign task for the second function is opened, due in 24 h; the use is flagged for
the after-action review. Composes the WP-09a approval service (same CAS, ETag, clocks, ledger outbox and
token) and adds its own policy decision (`policy/breakglass.rego`) in front of the 4750 database triggers.

Everything one request changes is written in one transaction: the break_glass row, the proposal state,
the execution token, the co-sign task (`job` kind `break_glass_cosign`), the material-free delta, the
envelope of a crew plan, an audit record and the K2 events in the outbox. After commit the relay drains
and the audit head is checkpointed (signed), so the use is notarised at once.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sgw.approval import audit
from sgw.approval import repository as repo
from sgw.approval.breakglass_policy import GovernancePolicy
from sgw.approval.envelope import EnvelopeService
from sgw.approval.errors import (
    ApprovalError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnprocessableError,
)
from sgw.approval.service import (
    ApprovalService,
    Outcome,
    Principal,
    _db_errors,
    etag,
    etag_matches,
    load_principal,
)
from sgw.approval.signer import Ed25519Signer
from sgw.contracts import approval as ap
from sgw.contracts.api_models import BreakGlassRequest, CosignTaskOut, ProposalCard
from sgw.contracts.base import Contract, utc_iso
from sgw.contracts.events import ApprovalRecorded, BreakGlassUsed, DecisionApproved
from sgw.contracts.vocab import ActionType, ApprovalDecision, ApprovalFunction, Tier

log = logging.getLogger("sgw.approval.breakglass")
COSIGN_JOB_KIND = "break_glass_cosign"
ENVELOPE_ACTIONS = frozenset({ActionType.PREPOSITION_CREWS.value})
CONFLICT_DENIALS = {
    "not_open": "PROPOSAL_NOT_OPEN",
    "already_used": "BREAK_GLASS_USED",
    "expired": "PROPOSAL_EXPIRED",
}
SignerSource = Callable[[], tuple[Ed25519Signer, audit.AnchorStore | None] | None]


@dataclass(frozen=True)
class CosignTask:
    break_glass_id: int
    proposal_id: str
    proposal_version: int
    ic_id: str
    reason: str
    used_at: datetime
    cosign_due: datetime
    functions: tuple[str, ...]
    cosigned_by: str | None
    cosigned_at: datetime | None
    overdue: bool

    def out(self) -> CosignTaskOut:
        return CosignTaskOut(
            break_glass_id=self.break_glass_id,
            proposal_id=self.proposal_id,
            proposal_version=self.proposal_version,
            ic_id=self.ic_id,
            reason=self.reason,
            used_at_utc=self.used_at,
            cosign_due_utc=self.cosign_due,
            functions=[ApprovalFunction(f) for f in self.functions],
            cosigned_by=self.cosigned_by,
            cosigned_at_utc=self.cosigned_at,
            overdue=self.overdue,
        )


def _ns(value: datetime | None) -> int | None:
    return None if value is None else int(value.timestamp() * 1_000_000_000)


def _subject(p: Principal) -> dict[str, Any]:
    return {**p.as_input(), "break_glass_eligible": p.break_glass_eligible}


def _refusal(deny: tuple[str, ...]) -> ConflictError | ForbiddenError | UnprocessableError:
    details = {"deny": list(deny)}
    if deny == ("reason_too_short",):
        return UnprocessableError(
            "break-glass needs a reason of at least 10 characters", code="REASON_REQUIRED"
        )
    conflicts = [CONFLICT_DENIALS[d] for d in deny if d in CONFLICT_DENIALS]
    if conflicts and len(conflicts) == len(deny):
        return ConflictError("break-glass is not possible in this state", code=conflicts[0], details=details)
    return ForbiddenError("the break-glass policy denies this request", code="POLICY_DENIED", details=details)


class BreakGlassService:
    def __init__(
        self,
        approvals: ApprovalService,
        policy: GovernancePolicy,
        *,
        envelopes: EnvelopeService | None = None,
        signer: SignerSource | None = None,
    ) -> None:
        self.approvals = approvals
        self.policy = policy
        self.envelopes = envelopes
        self.signer = signer

    @property
    def clock(self) -> Callable[[], datetime]:
        return self.approvals.scenario_clock

    def _checkpoint(self, conn: psycopg.Connection[Any]) -> None:
        """Notarise the new audit head after commit; a failure leaves it for the periodic checkpoint."""
        if self.signer is None:
            return
        try:
            source = self.signer()
            if source is not None:
                audit.checkpoint(conn, source[0], source[1])
        except Exception:
            log.warning(
                "audit checkpoint after break-glass failed; the periodic run will sign", exc_info=True
            )

    # ---- break-glass -----------------------------------------------------------------------------------

    def invoke(
        self,
        conn: psycopg.Connection[Any],
        *,
        user_id: str,
        proposal_id: str,
        request: BreakGlassRequest,
        if_match: str | None = None,
    ) -> Outcome[ProposalCard]:
        principal = load_principal(conn, user_id)
        stale = self.approvals._stale_now(conn, proposal_id, request.proposal_version)
        with _db_errors(stale), conn.transaction():
            row = repo.lock_proposal(conn, proposal_id)
            if row is None:
                raise NotFoundError(f"proposal {proposal_id} not found", code="PROPOSAL_NOT_FOUND")
            version, current_hash = row["proposal_version"], row["action_hash"]
            if not etag_matches(if_match, version, current_hash):
                raise self.approvals._stale(conn, row, min(request.proposal_version, version))
            if request.proposal_version != version or request.action_hash != current_hash:
                raise self.approvals._stale(conn, row, request.proposal_version)
            now = self.clock()
            existing = conn.execute(
                "SELECT 1 FROM break_glass WHERE proposal_id = %s AND proposal_version = %s",
                (proposal_id, version),
            ).fetchone()
            decision = self.policy.break_glass(
                {
                    "subject": _subject(principal),
                    "proposal": {
                        "tier": row["tier"],
                        "state": row["state"],
                        "proposed_by": row["proposed_by"],
                        "required_functions": list(row["required_functions"]),
                        "expires_at_ns": _ns(row["expires_at"]),
                    },
                    "break_glass": {"reason": request.reason, "existing": existing is not None},
                    "context": {"now_ns": _ns(now)},
                }
            )
            if not decision.allow:
                raise _refusal(decision.deny)
            reason = request.reason.strip()
            due = now + timedelta(hours=ap.BREAK_GLASS_COSIGN_HOURS)
            found = conn.execute(
                "INSERT INTO break_glass (proposal_id, ic_id, proposal_version, action_hash, reason, used_at,"
                " cosign_due) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING break_glass_id",
                (proposal_id, user_id, version, current_hash, reason, now, due),
            ).fetchone()
            assert found is not None
            bg_id = int(found[0])
            repo.set_state(conn, proposal_id, "approved")
            self.approvals._issue_token(conn, proposal_id, version, current_hash)
            second = [f for f in row["required_functions"] if f != ApprovalFunction.COMMAND.value]
            task = {
                "break_glass_id": bg_id,
                "proposal_id": proposal_id,
                "proposal_version": version,
                "ic_id": user_id,
                "functions": second,
                "due_utc": utc_iso(due),
            }
            conn.execute(
                "INSERT INTO job (kind, payload, state) VALUES (%s, %s, 'queued')",
                (COSIGN_JOB_KIND, Jsonb(task)),
            )
            repo.add_delta(
                conn,
                proposal_id,
                version,
                False,
                {"break_glass": bg_id, "by": user_id, "reason": reason, "cosign_due": task["due_utc"]},
            )
            if self.envelopes is not None and row["action_type"] in ENVELOPE_ACTIONS:
                self._record_envelope(conn, proposal_id, user_id, now)
            audit.append(
                conn,
                kind="break_glass_used",
                actor_type="user",
                actor_id=user_id,
                subject=proposal_id,
                payload={
                    "break_glass_id": bg_id,
                    "proposal_version": version,
                    "action_hash": current_hash,
                    "tier": row["tier"],
                    "reason": reason,
                    "cosign_due_utc": task["due_utc"],
                    "cosign_functions": second,
                    "flagged_for_after_action": True,
                },
                occurred_at=now,
                event_key=f"break_glass_used:{proposal_id}:v{version}",
            )
            events: list[Contract] = [
                BreakGlassUsed(proposal_id=proposal_id, ic_id=user_id, reason=reason, cosign_due_utc=due),
                DecisionApproved(
                    decision_case_id=row["decision_case_id"],
                    proposal_id=proposal_id,
                    proposal_version=version,
                    action_hash=current_hash,
                    tier=Tier(row["tier"]),
                    approver_ids=[user_id],
                    break_glass=True,
                ),
            ]
            self.approvals._emit(
                conn,
                row,
                [
                    (f"{proposal_id}:v{version}:break_glass", events[0]),
                    (f"{proposal_id}:v{version}:approved", events[1]),
                ],
            )
            card = self.approvals.card(conn, proposal_id)
        self.approvals._drain(conn)
        self._checkpoint(conn)
        return Outcome(card, etag(version, current_hash), tuple(events))

    def _record_envelope(
        self, conn: psycopg.Connection[Any], proposal_id: str, user_id: str, now: datetime
    ) -> None:
        """In a savepoint: an envelope failure never undoes the break-glass; it is audited instead, and every
        re-optimisation of the plan stays T3 because no envelope exists."""
        assert self.envelopes is not None
        try:
            with conn.transaction():
                self.envelopes.record(conn, proposal_id, actor_id=user_id)
        except (ApprovalError, psycopg.Error) as error:
            log.warning("envelope for %s not recorded: %s", proposal_id, error)
            audit.append(
                conn,
                kind="envelope_failed",
                actor_type="system",
                actor_id="system:breakglass",
                subject=proposal_id,
                payload={"error": type(error).__name__, "message": str(error)[:500]},
                occurred_at=now,
            )

    # ---- co-sign ---------------------------------------------------------------------------------------

    def cosign(
        self, conn: psycopg.Connection[Any], *, user_id: str, proposal_id: str, if_match: str | None = None
    ) -> Outcome[CosignTask]:
        """The second function co-signs the break-glass of the current version. A late co-signature is
        recorded (and stays flagged) rather than refused: the review needs it either way."""
        principal = load_principal(conn, user_id)
        with _db_errors(), conn.transaction():
            row = repo.lock_proposal(conn, proposal_id)
            if row is None:
                raise NotFoundError(f"proposal {proposal_id} not found", code="PROPOSAL_NOT_FOUND")
            if not etag_matches(if_match, row["proposal_version"], row["action_hash"]):
                raise self.approvals._stale(conn, row, row["proposal_version"])
            with conn.cursor(row_factory=dict_row) as cur:
                bg = cur.execute(
                    "SELECT * FROM break_glass WHERE proposal_id = %s AND proposal_version = %s",
                    (proposal_id, row["proposal_version"]),
                ).fetchone()
            if bg is None:
                raise NotFoundError("no break-glass on the current version", code="NO_BREAK_GLASS")
            now = self.clock()
            decision = self.policy.cosign(
                {
                    "subject": principal.as_input(),
                    "proposal": {
                        "state": row["state"],
                        "proposed_by": row["proposed_by"],
                        "required_functions": list(row["required_functions"]),
                    },
                    "break_glass": {"ic_id": bg["ic_id"], "cosigned": bg["cosigned_by"] is not None},
                    "context": {"now_ns": _ns(now)},
                }
            )
            if not decision.allow:
                if "already_cosigned" in decision.deny:
                    raise ConflictError("already co-signed", code="ALREADY_COSIGNED")
                raise ForbiddenError(
                    "the co-sign policy denies this request",
                    code="POLICY_DENIED",
                    details={"deny": list(decision.deny)},
                )
            late = now > bg["cosign_due"]
            conn.execute(
                "SELECT authority_cosign_break_glass(%s, %s, %s)",
                (bg["break_glass_id"], user_id, now),
            )
            conn.execute(
                "UPDATE job SET state = 'done' WHERE kind = %s AND state = 'queued'"
                " AND (payload->>'break_glass_id')::bigint = %s",
                (COSIGN_JOB_KIND, bg["break_glass_id"]),
            )
            audit.append(
                conn,
                kind="break_glass_cosigned",
                actor_type="user",
                actor_id=user_id,
                subject=proposal_id,
                payload={
                    "break_glass_id": bg["break_glass_id"],
                    "proposal_version": row["proposal_version"],
                    "function": decision.function,
                    "late": late,
                    "cosign_due_utc": utc_iso(bg["cosign_due"]),
                },
                occurred_at=now,
                event_key=f"break_glass_cosigned:{bg['break_glass_id']}",
            )
            event = ApprovalRecorded(
                approval_id=f"BGC-{bg['break_glass_id']}",
                proposal_id=proposal_id,
                proposal_version=row["proposal_version"],
                action_hash=row["action_hash"],
                approver_id=user_id,
                function=ApprovalFunction(decision.function or ""),
                decision=ApprovalDecision.COSIGN,
                reason_code="late_cosign" if late else None,
            )
            self.approvals._emit(conn, row, [(event.approval_id, event)])
            task = self._task(conn, int(bg["break_glass_id"]), now)
        self.approvals._drain(conn)
        self._checkpoint(conn)
        return Outcome(task, etag(row["proposal_version"], row["action_hash"]), (event,))

    # ---- tasks and after-action ------------------------------------------------------------------------

    def _task(self, conn: psycopg.Connection[Any], bg_id: int, now: datetime) -> CosignTask:
        tasks = self.tasks(conn, include_done=True, now=now, break_glass_id=bg_id)
        return tasks[0]

    def tasks(
        self,
        conn: psycopg.Connection[Any],
        *,
        include_done: bool = False,
        now: datetime | None = None,
        break_glass_id: int | None = None,
    ) -> list[CosignTask]:
        """Co-sign tasks (open by default) with their due time; every row is an after-action flag."""
        at = now or self.clock()
        clauses, params = [], []
        if not include_done:
            clauses.append("b.cosigned_by IS NULL")
        if break_glass_id is not None:
            clauses.append("b.break_glass_id = %s")
            params.append(break_glass_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(
                "SELECT b.*, p.required_functions::text[] AS required_functions"  # noqa: S608
                " FROM break_glass b JOIN proposal p USING (proposal_id)"
                f" {where} ORDER BY b.cosign_due, b.break_glass_id",
                params,
            ).fetchall()
        return [
            CosignTask(
                break_glass_id=int(r["break_glass_id"]),
                proposal_id=r["proposal_id"],
                proposal_version=int(r["proposal_version"]),
                ic_id=r["ic_id"],
                reason=r["reason"],
                used_at=r["used_at"],
                cosign_due=r["cosign_due"],
                functions=tuple(f for f in r["required_functions"] if f != ApprovalFunction.COMMAND.value),
                cosigned_by=r["cosigned_by"],
                cosigned_at=r["cosigned_at"],
                overdue=(r["cosigned_at"] or at) > r["cosign_due"],
            )
            for r in rows
        ]

    def flag_overdue(self, conn: psycopg.Connection[Any]) -> list[int]:
        """Write one audit record per overdue, unsigned break-glass (idempotent by event key)."""
        now = self.clock()
        flagged: list[int] = []
        with conn.transaction():
            for task in self.tasks(conn, now=now):
                if not task.overdue:
                    continue
                key = f"break_glass_cosign_overdue:{task.break_glass_id}"
                if conn.execute("SELECT 1 FROM audit_event WHERE event_key = %s", (key,)).fetchone():
                    continue
                audit.append(
                    conn,
                    kind="break_glass_cosign_overdue",
                    actor_type="system",
                    actor_id="system:breakglass",
                    subject=task.proposal_id,
                    payload={
                        "break_glass_id": task.break_glass_id,
                        "cosign_due_utc": utc_iso(task.cosign_due),
                        "functions": list(task.functions),
                    },
                    occurred_at=now,
                    event_key=key,
                )
                flagged.append(task.break_glass_id)
        if flagged:
            self._checkpoint(conn)
        return flagged
