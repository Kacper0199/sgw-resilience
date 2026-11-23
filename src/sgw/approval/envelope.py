"""Approved envelopes (O-04, K8): the one bounds function, and the service that records and applies them.

`assess` is the single pure bounds function: inside every bound of an approved, unexpired envelope a
re-optimisation is T1; a value outside, an unknown parameter or an expired envelope makes it T3 again. It
agrees with `sgw.contracts.approval.tier_for_reoptimisation` and with `policy/envelope.rego`
(`data.sgw.envelope.assessment`); parity tests pin all three. Bounds come from the approved plan with
`policy_envelope_pct` (numbers.yaml, kind=policy) around each integer quantity.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import psycopg
from psycopg.types.json import Jsonb

from sgw.approval import audit
from sgw.approval.errors import ApprovalError, ConflictError, NotFoundError, UnprocessableError
from sgw.approval.ledger import LedgerSink
from sgw.approval.ledger import envelope as k2_envelope
from sgw.common import numbers
from sgw.contracts import approval as ap
from sgw.contracts.events import EnvelopeApproved
from sgw.contracts.vocab import Classification, Tier

ENVELOPE_STATES = frozenset({"approved", "executed"})


def envelope_pct() -> int:
    return int(numbers.value("policy_envelope_pct"))


@dataclass(frozen=True)
class EnvelopeAssessment:
    tier: Tier
    outside: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    expired: bool = False

    def as_json(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "outside": list(self.outside),
            "unknown": list(self.unknown),
            "expired": self.expired,
        }


def assess_bounds(
    bounds: Mapping[str, ap.EnvelopeBound], params: Mapping[str, Any], *, expired: bool
) -> EnvelopeAssessment:
    unknown = tuple(sorted(k for k in params if k not in bounds))
    outside = tuple(sorted(k for k, v in params.items() if k in bounds and not ap.within_bound(bounds[k], v)))
    inside = not (expired or unknown or outside)
    return EnvelopeAssessment(Tier.T1 if inside else Tier.T3, outside, unknown, expired)


def assess(
    bounds: Mapping[str, ap.EnvelopeBound], params: Mapping[str, Any], *, at: datetime, valid_until: datetime
) -> EnvelopeAssessment:
    return assess_bounds(bounds, params, expired=at > valid_until)


def bounds_from_params(params: Mapping[str, Any], pct: int) -> dict[str, ap.EnvelopeBound]:
    plan = {k: int(v) for k, v in params.items() if isinstance(v, int) and not isinstance(v, bool)}
    return ap.envelope_from_plan(plan, pct=pct)


def _ns(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def policy_input(env: ap.Envelope, params: Mapping[str, Any], at: datetime) -> dict[str, Any]:
    return {
        "envelope": {
            "bounds": {k: b.model_dump() for k, b in env.bounds.items()},
            "valid_until_ns": _ns(env.valid_until_utc),
        },
        "params": dict(params),
        "context": {"now_ns": _ns(at)},
    }


class EnvelopePolicy(Protocol):
    def envelope(self, payload: dict[str, Any]) -> EnvelopeAssessment: ...


def parse_assessment(raw: Any) -> EnvelopeAssessment:
    return EnvelopeAssessment(
        tier=Tier(raw["tier"]),
        outside=tuple(raw["outside"]),
        unknown=tuple(raw["unknown"]),
        expired=raw["expired"] is True,
    )


def _envelope_row(conn: psycopg.Connection[Any], proposal_id: str) -> ap.Envelope | None:
    row = conn.execute(
        "SELECT envelope_id, proposal_id, bounds, valid_until FROM envelope WHERE proposal_id = %s",
        (proposal_id,),
    ).fetchone()
    if row is None:
        return None
    return ap.Envelope(envelope_id=row[0], proposal_id=row[1], bounds=row[2], valid_until_utc=row[3])


class EnvelopeService:
    """Records the envelope of an approved T3 plan and classifies re-optimisations against it. When the
    policy decision point fails or disagrees with the pure function, the answer is T3 (fail closed)."""

    def __init__(
        self,
        policy: EnvelopePolicy | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        ledger: LedgerSink | None = None,
        pct: int | None = None,
    ) -> None:
        self.policy = policy
        self.clock = clock
        self.ledger = ledger
        self.pct = pct if pct is not None else envelope_pct()

    def record(self, conn: psycopg.Connection[Any], proposal_id: str, *, actor_id: str) -> ap.Envelope:
        """In the caller's transaction. Idempotent: an existing envelope is returned unchanged."""
        existing = _envelope_row(conn, proposal_id)
        if existing is not None:
            return existing
        row = conn.execute(
            "SELECT p.params, p.tier, p.state, p.region_id, p.domain, c.consequence_utc, c.next_advisory_utc"
            " FROM proposal p JOIN decision_case c USING (decision_case_id) WHERE p.proposal_id = %s",
            (proposal_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"proposal {proposal_id} not found", code="PROPOSAL_NOT_FOUND")
        params, tier, state, region_id, domain, consequence, next_advisory = row
        if tier != Tier.T3.value or state not in ENVELOPE_STATES:
            raise ConflictError("an envelope needs an approved T3 proposal", code="ENVELOPE_NOT_ALLOWED")
        bounds = bounds_from_params(params, self.pct)
        if not bounds:
            raise UnprocessableError("the plan has no integer quantities to bound", code="NO_ENVELOPE_PARAMS")
        valid_until = min(t for t in (consequence, next_advisory) if t is not None)
        env = ap.Envelope(
            envelope_id=f"ENV-{proposal_id}",
            proposal_id=proposal_id,
            bounds=bounds,
            valid_until_utc=valid_until,
        )
        conn.execute(
            "INSERT INTO envelope (envelope_id, proposal_id, bounds, valid_until) VALUES (%s, %s, %s, %s)",
            (
                env.envelope_id,
                proposal_id,
                Jsonb({k: b.model_dump() for k, b in bounds.items()}),
                valid_until,
            ),
        )
        now = self.clock()
        payload = EnvelopeApproved(
            envelope_id=env.envelope_id,
            proposal_id=proposal_id,
            bounds=bounds,
            valid_until_utc=valid_until,
        )
        audit.append(
            conn,
            kind="envelope_approved",
            actor_type="system" if actor_id.startswith("system:") else "user",
            actor_id=actor_id,
            subject=proposal_id,
            payload={**payload.model_dump(mode="json"), "pct": self.pct},
            occurred_at=now,
            event_key=f"envelope_approved:{env.envelope_id}",
        )
        if self.ledger is not None:
            classification = Classification.C2 if domain == "water" else Classification.C1
            self.ledger.enqueue(
                conn,
                [
                    k2_envelope(
                        payload,
                        at=now,
                        key=env.envelope_id,
                        region_id=region_id,
                        domain=domain,
                        classification=classification,
                    )
                ],
            )
        return env

    def classify(
        self, conn: psycopg.Connection[Any], proposal_id: str, params: Mapping[str, Any]
    ) -> EnvelopeAssessment:
        """Tier of a re-optimisation of `proposal_id`'s plan: T1 inside its envelope, else T3."""
        env = _envelope_row(conn, proposal_id)
        at = self.clock()
        if env is None:
            return EnvelopeAssessment(Tier.T3, unknown=tuple(sorted(params)), expired=False)
        pure = assess(env.bounds, params, at=at, valid_until=env.valid_until_utc)
        if self.policy is None:
            return pure
        try:
            decided = self.policy.envelope(policy_input(env, params, at))
        except ApprovalError:
            return EnvelopeAssessment(Tier.T3, pure.outside, pure.unknown, pure.expired)
        if decided.tier is not pure.tier:
            return EnvelopeAssessment(Tier.T3, pure.outside, pure.unknown, pure.expired)
        return decided
