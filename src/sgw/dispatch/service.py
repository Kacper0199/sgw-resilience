"""Crew dispatch writes. A dispatcher proposes an assignment of a crew to an open decision or
a staging yard; one person of the function the policy names signs or rejects it; then the crew moves
(on the way, on site or staged, blocked with a reason, released). Every change is one transaction: the
`crew_assignment` row, a hash-chained audit record and, for a status change, a K2 `CrewStatus` event queued
through the outbox (drained into the ledger after commit), so the crews read model, the map and the copilot
tools all see the same status."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg import pq
from psycopg.rows import dict_row

from sgw.approval import audit
from sgw.approval.errors import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from sgw.approval.ledger import LedgerSink
from sgw.contracts.api_models import CrewMove
from sgw.contracts.events import EVENT_MODELS, CrewStatusEvent, EnvelopeBase
from sgw.contracts.vocab import (
    ApprovalDecision,
    BlockReason,
    Classification,
    CrewStatus,
    FeedMode,
    RunMode,
    Trust,
)
from sgw.dispatch import read, rules
from sgw.dispatch.policy import DispatchPolicy

log = logging.getLogger(__name__)

SOURCE_ID = "sgw-dispatch"
NAMESPACE = uuid.UUID("5d0b8f3e-2a41-4c7e-9a7b-6f1c0e2d9a51")
PUBLIC_CLASSES = ("C0", "C1")
LOCK_PREFIX = "crew_dispatch:"

_CREW = """
SELECT payload, region_id, domain::text AS domain FROM event
WHERE type = 'CrewStatus' AND payload->>'crew_id' = %(crew)s AND scenario_known_at <= %(at)s
  AND classification::text = ANY(%(classes)s)
ORDER BY ledger_seq DESC LIMIT 1
"""

_BEFORE_BLOCK = """
SELECT payload FROM event
WHERE type = 'CrewStatus' AND payload->>'crew_id' = %(crew)s AND scenario_known_at <= %(at)s
  AND classification::text = ANY(%(classes)s) AND payload->>'status' <> 'blocked'
ORDER BY ledger_seq DESC LIMIT 1
"""

_ACTIVE = """
SELECT assignment_id, crew_id, target_kind, target_id, state, required_function::text AS required_function,
       proposed_by, proposed_at, decided_by, decided_at
FROM crew_assignment WHERE crew_id = %s AND state IN ('proposed', 'assigned') FOR UPDATE
"""

_SITE = """
SELECT p.targets[1] AS site FROM proposal p WHERE p.decision_case_id = %s
ORDER BY p.created_at DESC, p.proposal_id DESC LIMIT 1
"""


@dataclass(frozen=True)
class Crew:
    crew_id: str
    status: CrewStatus
    location_id: str | None
    headcount: int
    region_id: str | None
    domain: str | None


def crew_status_envelope(
    crew: Crew,
    status: CrewStatus,
    *,
    at: datetime,
    location_id: str | None,
    block_reason: BlockReason | None = None,
    run_mode: RunMode = RunMode.REPLAY,
) -> EnvelopeBase:
    """The K2 `CrewStatus` event of a dispatch change, in the shape the crew-tracking feed uses."""
    payload = CrewStatusEvent(
        crew_id=crew.crew_id,
        status=status,
        location_id=location_id,
        headcount=crew.headcount,
        block_reason=block_reason.value if block_reason else None,
    )
    dedup = f"{SOURCE_ID}:CrewStatus:{crew.crew_id}:{uuid.uuid4().hex}"
    return EVENT_MODELS["CrewStatus"].model_validate(
        {
            "type": "CrewStatus",
            "event_id": uuid.uuid5(NAMESPACE, dedup),
            "source_id": SOURCE_ID,
            "feed_mode": FeedMode.SYNTHETIC,
            "run_mode": run_mode,
            "event_time": at,
            "received_at": at,
            "known_at": at,
            "scenario_known_at": at,
            "dedup_key": dedup,
            "classification": Classification.C1,
            "trust": Trust.VERIFIED_INTERNAL,
            "region_id": crew.region_id,
            "domain": crew.domain or "electric",
            "payload": payload,
        }
    )


def _new_id() -> str:
    return f"ASG-{uuid.uuid4().hex[:16].upper()}"


def _actor_type(user_id: str) -> audit.ActorType:
    return "system" if user_id.startswith("system:") else "user"


class DispatchService:
    def __init__(
        self,
        policy: DispatchPolicy,
        *,
        scenario_clock: Callable[[], datetime],
        ledger: LedgerSink | None = None,
        run_mode: RunMode = RunMode.REPLAY,
    ) -> None:
        self.policy = policy
        self.scenario_clock = scenario_clock
        self.ledger = ledger
        self.run_mode = run_mode

    # ---- reads inside a write -------------------------------------------------------------------------

    def _crew(self, conn: psycopg.Connection[Any], crew_id: str, at: datetime) -> Crew:
        args = {"crew": crew_id, "at": at, "classes": list(PUBLIC_CLASSES)}
        with conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(_CREW, args).fetchone()
        if row is None:
            raise NotFoundError(f"crew {crew_id} has not reported yet", code="CREW_NOT_FOUND")
        p = row["payload"]
        return Crew(
            crew_id=crew_id,
            status=CrewStatus(p["status"]),
            location_id=p.get("location_id"),
            headcount=int(p.get("headcount") or 0),
            region_id=row["region_id"],
            domain=row["domain"],
        )

    def _active(self, conn: psycopg.Connection[Any], crew_id: str) -> dict[str, Any] | None:
        with conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(_ACTIVE, (crew_id,)).fetchone()

    @staticmethod
    def _state(crew: Crew, active: dict[str, Any] | None) -> rules.CrewState:
        return rules.CrewState(
            status=crew.status,
            assignment_state=active["state"] if active else None,
            target_kind=active["target_kind"] if active else None,
            proposed_by=active["proposed_by"] if active else None,
            required_function=active["required_function"] if active else None,
        )

    def _lock(self, conn: psycopg.Connection[Any], crew_id: str) -> None:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK_PREFIX + crew_id,))

    def _require_actor(self, subject: dict[str, Any]) -> None:
        verdict = self.policy.act({"subject": subject})
        if not verdict.allow:
            raise ForbiddenError(
                "this role can't dispatch crews", code="DISPATCH_DENIED", details={"deny": list(verdict.deny)}
            )

    # ---- side effects in the caller's transaction -----------------------------------------------------

    def _audit(
        self, conn: psycopg.Connection[Any], kind: str, *, actor: str, subject: str, payload: dict[str, Any]
    ) -> None:
        audit.append(
            conn,
            kind=kind,
            actor_type=_actor_type(actor),
            actor_id=actor,
            subject=subject,
            payload=payload,
            occurred_at=self.scenario_clock(),
        )

    def _status_event(
        self,
        conn: psycopg.Connection[Any],
        crew: Crew,
        status: CrewStatus,
        *,
        location_id: str | None,
        block_reason: BlockReason | None = None,
    ) -> None:
        if self.ledger is None:
            return
        envelope = crew_status_envelope(
            crew,
            status,
            at=self.scenario_clock(),
            location_id=location_id,
            block_reason=block_reason,
            run_mode=self.run_mode,
        )
        self.ledger.enqueue(conn, [envelope])

    def _drain(self, conn: psycopg.Connection[Any]) -> None:
        idle = conn.info.transaction_status == pq.TransactionStatus.IDLE
        if self.ledger is not None and conn.autocommit and idle:
            try:
                self.ledger.drain(conn)
            except Exception:
                log.warning(
                    "ledger drain after a dispatch change failed; the relay will retry", exc_info=True
                )

    # ---- commands ---------------------------------------------------------------------------------------

    def propose(
        self, conn: psycopg.Connection[Any], *, user_id: str, crew_id: str, target_kind: str, target_id: str
    ) -> str:
        subject = read.subject_sync(conn, user_id)
        verdict = self.policy.propose({"subject": subject})
        if not verdict.allow or verdict.required_function is None:
            raise ForbiddenError(
                "this role can't assign crews", code="DISPATCH_DENIED", details={"deny": list(verdict.deny)}
            )
        known = {(t.kind, t.target_id) for t in read.targets_sync(conn)}
        if (target_kind, target_id) not in known:
            raise UnprocessableError(
                "assign to an open decision or a staging yard",
                code="UNKNOWN_DISPATCH_TARGET",
                details={"target_kind": target_kind, "target_id": target_id},
            )
        now = self.scenario_clock()
        assignment_id = _new_id()
        with conn.transaction():
            self._lock(conn, crew_id)
            crew = self._crew(conn, crew_id, now)
            if not rules.assign_allowed(self._state(crew, self._active(conn, crew_id))):
                raise ConflictError(
                    f"crew {crew_id} already has an assignment or can't take one now",
                    code="CREW_NOT_ASSIGNABLE",
                )
            conn.execute(
                "INSERT INTO crew_assignment (assignment_id, crew_id, target_kind, target_id, state,"
                " required_function, proposed_by, proposed_at, policy_version)"
                " VALUES (%s, %s, %s, %s, 'proposed', %s, %s, %s, %s)",
                (
                    assignment_id,
                    crew_id,
                    target_kind,
                    target_id,
                    verdict.required_function,
                    user_id,
                    now,
                    verdict.policy_version,
                ),
            )
            self._audit(
                conn,
                "crew_assignment_proposed",
                actor=user_id,
                subject=assignment_id,
                payload={
                    "crew_id": crew_id,
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "required_function": verdict.required_function,
                    "policy_version": verdict.policy_version,
                },
            )
        return assignment_id

    def sign(
        self,
        conn: psycopg.Connection[Any],
        *,
        user_id: str,
        crew_id: str,
        decision: ApprovalDecision,
        reason: str | None = None,
    ) -> None:
        subject = read.subject_sync(conn, user_id)
        now = self.scenario_clock()
        with conn.transaction():
            self._lock(conn, crew_id)
            active = self._active(conn, crew_id)
            if active is None or active["state"] != "proposed":
                raise ConflictError(
                    f"crew {crew_id} has no assignment waiting for a signature", code="NOT_PENDING"
                )
            verdict = self.policy.sign(
                {
                    "subject": subject,
                    "assignment": {
                        "state": active["state"],
                        "proposed_by": active["proposed_by"],
                        "required_function": active["required_function"],
                    },
                }
            )
            if not verdict.allow:
                raise ForbiddenError(
                    "you can't sign this assignment", code="SIGN_DENIED", details={"deny": list(verdict.deny)}
                )
            approve = decision is ApprovalDecision.APPROVE
            conn.execute(
                "UPDATE crew_assignment SET state = %s, decided_by = %s, decided_at = %s, updated_at = now()"
                " WHERE assignment_id = %s",
                ("assigned" if approve else "rejected", user_id, now, active["assignment_id"]),
            )
            self._audit(
                conn,
                "crew_assignment_signed" if approve else "crew_assignment_rejected",
                actor=user_id,
                subject=active["assignment_id"],
                payload={
                    "crew_id": crew_id,
                    "target_kind": active["target_kind"],
                    "target_id": active["target_id"],
                    "function": active["required_function"],
                    "decision": decision.value,
                    **({"reason": reason.strip()} if reason and reason.strip() and not approve else {}),
                },
            )

    def withdraw(self, conn: psycopg.Connection[Any], *, user_id: str, crew_id: str) -> None:
        self._require_actor(read.subject_sync(conn, user_id))
        now = self.scenario_clock()
        with conn.transaction():
            self._lock(conn, crew_id)
            active = self._active(conn, crew_id)
            if active is None or active["state"] != "proposed":
                raise ConflictError(
                    f"crew {crew_id} has no assignment waiting for a signature", code="NOT_PENDING"
                )
            conn.execute(
                "UPDATE crew_assignment SET state = 'withdrawn', closed_by = %s, closed_at = %s,"
                " updated_at = now() WHERE assignment_id = %s",
                (user_id, now, active["assignment_id"]),
            )
            self._audit(
                conn,
                "crew_assignment_withdrawn",
                actor=user_id,
                subject=active["assignment_id"],
                payload={"crew_id": crew_id, "target_id": active["target_id"]},
            )

    def _target_location(self, conn: psycopg.Connection[Any], active: dict[str, Any]) -> str | None:
        if active["target_kind"] == "yard":
            return str(active["target_id"])
        row = conn.execute(_SITE, (active["target_id"],)).fetchone()
        return str(row[0]) if row and row[0] else None

    def move(
        self,
        conn: psycopg.Connection[Any],
        *,
        user_id: str,
        crew_id: str,
        move: CrewMove,
        block_reason: BlockReason | None = None,
    ) -> None:
        self._require_actor(read.subject_sync(conn, user_id))
        if move == "blocked" and block_reason is None:
            raise UnprocessableError("say why the crew is blocked", code="BLOCK_REASON_REQUIRED")
        now = self.scenario_clock()
        with conn.transaction():
            self._lock(conn, crew_id)
            crew = self._crew(conn, crew_id, now)
            active = self._active(conn, crew_id)
            if not rules.move_allowed(move, self._state(crew, active)):
                raise ConflictError(
                    f"crew {crew_id} can't do that from {crew.status.value}",
                    code="CREW_MOVE_NOT_ALLOWED",
                    details={"move": move, "status": crew.status.value},
                )
            status, location = self._next(conn, crew, active, move, now)
            if move == "release" and active is not None:
                conn.execute(
                    "UPDATE crew_assignment SET state = 'released', closed_by = %s, closed_at = %s,"
                    " updated_at = now() WHERE assignment_id = %s",
                    (user_id, now, active["assignment_id"]),
                )
            self._status_event(conn, crew, status, location_id=location, block_reason=block_reason)
            self._audit(
                conn,
                "crew_released" if move == "release" else "crew_status_changed",
                actor=user_id,
                subject=crew_id,
                payload={
                    "crew_id": crew_id,
                    "from": crew.status.value,
                    "to": status.value,
                    "location_id": location,
                    "block_reason": block_reason.value if block_reason else None,
                    "assignment_id": active["assignment_id"] if active else None,
                },
            )
        self._drain(conn)

    def _next(
        self,
        conn: psycopg.Connection[Any],
        crew: Crew,
        active: dict[str, Any] | None,
        move: CrewMove,
        now: datetime,
    ) -> tuple[CrewStatus, str | None]:
        if move == "blocked":
            return CrewStatus.BLOCKED, crew.location_id
        if move == "release":
            return CrewStatus.AVAILABLE, crew.location_id
        if move == "unblock":
            args = {"crew": crew.crew_id, "at": now, "classes": list(PUBLIC_CLASSES)}
            with conn.cursor(row_factory=dict_row) as cur:
                row = cur.execute(_BEFORE_BLOCK, args).fetchone()
            before = row["payload"] if row else {}
            return CrewStatus(before.get("status", CrewStatus.AVAILABLE.value)), before.get("location_id")
        assert active is not None
        return CrewStatus(move), self._target_location(conn, active)
