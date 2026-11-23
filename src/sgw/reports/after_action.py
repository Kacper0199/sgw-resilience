"""After-action lite (D5, SC-5): what happened, read back from the tamper-evident audit chain.

The review trusts the chain only as far as it verifies: `audit.verify` runs first, and every record at or
after the first bad sequence is left out and the review is marked untrusted from there. From the trusted
records:

- clocks met or missed: a decision case's clock is met when one of its proposals reached authority (an
  execution token issued after the full approval, or a break-glass use) at or before its effective decide-by
  on the scenario clock; missed when that happened later, or when nothing happened and the decide-by has
  passed at the review time (a case that never got a proposal is missed once its deadline passed, the rule
  Decisions > Closed and Ask count with, `missed_unproposed`); open otherwise;
- break-glass uses with their co-sign status (co-signed in time, co-signed late, overdue and unsigned,
  awaiting co-sign), each cross-checked against the `break_glass` table; a disagreement is flagged;
- the ledger timeline of authority-relevant records."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict

from sgw.approval import audit
from sgw.approval.outcome import AUTHORITY_KINDS
from sgw.approval.signer import Keyring

TIMELINE_KINDS = frozenset(
    {
        "proposal_created",
        "proposal_revised",
        "proposal_withdrawn",
        "approval_recorded",
        "approval_withdrawn",
        "execution_token_issued",
        "execution_token_burned",
        "break_glass_used",
        "break_glass_cosigned",
        "break_glass_cosign_overdue",
        "envelope_approved",
        "etr_published",
        "kill_switch_triggered",
        "kill_switch_restored",
        "degraded_mode_changed",
        "security_alert",
    }
)
ClockOutcome = Literal["met", "missed", "open", "unverifiable"]
CosignStatus = Literal[
    "cosigned_on_time", "cosigned_late", "overdue_unsigned", "awaiting_cosign", "unverifiable"
]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ChainCheck(_Model):
    ok: bool
    checked_to_seq: int
    first_bad_seq: int | None
    signed_head_seq: int | None
    trusted_to_seq: int
    problems: list[str]


class TimelineEntry(_Model):
    seq: int
    occurred_at: datetime
    kind: str
    actor_id: str
    subject: str


class ClockResult(_Model):
    decision_case_id: str
    step: str
    title: str
    effective_decide_by: datetime
    decided_at: datetime | None
    decided_by: Literal["approval", "break_glass"] | None
    proposal_id: str | None
    outcome: ClockOutcome
    margin_min: int | None
    proposed: bool = True


class BreakGlassUse(_Model):
    break_glass_id: int
    proposal_id: str
    ic_id: str
    tier: str
    reason: str
    used_at: datetime
    cosign_due: datetime
    cosigned_by: str | None
    cosigned_at: datetime | None
    status: CosignStatus
    table_agrees: bool


class AfterActionReview(_Model):
    as_of: datetime
    chain: ChainCheck
    clocks: list[ClockResult]
    break_glass: list[BreakGlassUse]
    timeline: list[TimelineEntry]

    @property
    def met(self) -> list[ClockResult]:
        return [c for c in self.clocks if c.outcome == "met"]

    @property
    def missed(self) -> list[ClockResult]:
        return [c for c in self.clocks if c.outcome == "missed"]

    @property
    def open(self) -> list[ClockResult]:
        return [c for c in self.clocks if c.outcome == "open"]

    @property
    def unverifiable(self) -> list[ClockResult]:
        return [c for c in self.clocks if c.outcome == "unverifiable"]

    @property
    def usable(self) -> bool:
        """False when the chain did not verify: the drafts carry a "chain broken, not for use" banner."""
        return self.chain.ok


@dataclass(frozen=True)
class _Record:
    seq: int
    occurred_at: datetime
    kind: str
    actor_id: str
    subject: str
    payload: dict[str, Any] = field(default_factory=dict)


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def check_chain(
    conn: psycopg.Connection[Any], keyring: Keyring | None = None, anchors: audit.AnchorStore | None = None
) -> ChainCheck:
    report = audit.verify(conn, keyring=keyring, anchors=anchors)
    trusted = report.checked_to_seq if report.first_bad_seq is None else report.first_bad_seq - 1
    return ChainCheck(
        ok=report.ok,
        checked_to_seq=report.checked_to_seq,
        first_bad_seq=report.first_bad_seq,
        signed_head_seq=report.signed_head_seq,
        trusted_to_seq=max(trusted, 0),
        problems=list(report.problems)[:20],
    )


def _records(conn: psycopg.Connection[Any], to_seq: int | None) -> list[_Record]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT seq, occurred_at, kind, actor_id, subject, payload FROM audit_event"
            " WHERE stream = %s AND (%s::bigint IS NULL OR seq <= %s) ORDER BY seq",
            (audit.STREAM, to_seq, to_seq),
        ).fetchall()
    return [
        _Record(
            seq=int(r["seq"]),
            occurred_at=_utc(r["occurred_at"]),
            kind=str(r["kind"]),
            actor_id=str(r["actor_id"]),
            subject=str(r["subject"]),
            payload=dict(r["payload"] or {}),
        )
        for r in rows
    ]


def clock_outcomes(
    cases: Sequence[dict[str, Any]],
    proposal_case: dict[str, str],
    records: Sequence[_Record],
    as_of: datetime,
    *,
    chain_ok: bool = True,
) -> list[ClockResult]:
    """Only trusted records decide an outcome. With a broken chain, a clock that has no trusted authority
    record is `unverifiable`, never missed: its decision may sit in the untrusted part."""
    first: dict[str, tuple[datetime, int, str, str]] = {}
    for r in records:
        case = proposal_case.get(r.subject)
        if r.kind not in AUTHORITY_KINDS or case is None:
            continue
        how = "break_glass" if r.kind == "break_glass_used" else "approval"
        key = (r.occurred_at, 0 if how == "break_glass" else 1, how, r.subject)
        if case not in first or key[:2] < first[case][:2]:
            first[case] = key
    proposed = set(proposal_case.values())
    out: list[ClockResult] = []
    for c in sorted(cases, key=lambda c: (_utc(c["effective_decide_by_utc"]), c["decision_case_id"])):
        due = _utc(c["effective_decide_by_utc"])
        hit = first.get(c["decision_case_id"])
        outcome: ClockOutcome
        if hit is not None:
            outcome = "met" if hit[0] <= due else "missed"
            margin = round((due - hit[0]).total_seconds() / 60)
        elif not chain_ok:
            outcome, margin = "unverifiable", None
        else:
            outcome = "missed" if as_of > due else "open"
            margin = None
        out.append(
            ClockResult(
                decision_case_id=c["decision_case_id"],
                step=str(c["step"]),
                title=str(c["title"]),
                effective_decide_by=due,
                decided_at=hit[0] if hit else None,
                decided_by=hit[2] if hit else None,  # type: ignore[arg-type]
                proposal_id=hit[3] if hit else None,
                outcome=outcome,
                margin_min=margin,
                proposed=c["decision_case_id"] in proposed,
            )
        )
    return out


def break_glass_uses(
    records: Sequence[_Record],
    table: dict[int, dict[str, Any]],
    as_of: datetime,
    *,
    chain_ok: bool = True,
    untrusted: Sequence[_Record] = (),
) -> list[BreakGlassUse]:
    """Co-sign status from trusted records. With a broken chain, a use without a trusted co-sign record is
    `unverifiable` (never overdue against the named people), and uses recorded only in the untrusted part are
    listed as `unverifiable` too."""
    used = {int(r.payload["break_glass_id"]): r for r in records if r.kind == "break_glass_used"}
    shaky = {
        int(r.payload["break_glass_id"]): r
        for r in untrusted
        if r.kind == "break_glass_used" and str(r.payload.get("break_glass_id", "")).isdigit()
    }
    cosigned = {int(r.payload["break_glass_id"]): r for r in records if r.kind == "break_glass_cosigned"}
    overdue = {int(r.payload["break_glass_id"]) for r in records if r.kind == "break_glass_cosign_overdue"}
    out: list[BreakGlassUse] = []
    for bg_id, r in sorted(used.items()):
        due = _parse(str(r.payload["cosign_due_utc"]))
        sign = cosigned.get(bg_id)
        status: CosignStatus
        if sign is not None:
            status = (
                "cosigned_late" if sign.payload.get("late") or sign.occurred_at > due else "cosigned_on_time"
            )
        elif not chain_ok:
            status = "unverifiable"
        elif bg_id in overdue or as_of > due:
            status = "overdue_unsigned"
        else:
            status = "awaiting_cosign"
        row = table.get(bg_id)
        agrees = (
            row is not None
            and row["proposal_id"] == r.subject
            and row["ic_id"] == r.actor_id
            and (row["cosigned_by"] is None) == (sign is None)
            and (sign is None or row["cosigned_by"] == sign.actor_id)
        )
        out.append(
            BreakGlassUse(
                break_glass_id=bg_id,
                proposal_id=r.subject,
                ic_id=r.actor_id,
                tier=str(r.payload.get("tier", "")),
                reason=str(r.payload.get("reason", "")),
                used_at=r.occurred_at,
                cosign_due=due,
                cosigned_by=sign.actor_id if sign else None,
                cosigned_at=sign.occurred_at if sign else None,
                status=status,
                table_agrees=agrees,
            )
        )
    for bg_id, r in sorted(shaky.items()):
        if bg_id in used:
            continue
        due_raw = r.payload.get("cosign_due_utc")
        out.append(
            BreakGlassUse(
                break_glass_id=bg_id,
                proposal_id=r.subject,
                ic_id=r.actor_id,
                tier=str(r.payload.get("tier", "")),
                reason=str(r.payload.get("reason", "")),
                used_at=r.occurred_at,
                cosign_due=_parse(str(due_raw)) if due_raw else r.occurred_at,
                cosigned_by=None,
                cosigned_at=None,
                status="unverifiable",
                table_agrees=False,
            )
        )
    return out


def review(
    conn: psycopg.Connection[Any],
    as_of: datetime,
    *,
    keyring: Keyring | None = None,
    anchors: audit.AnchorStore | None = None,
) -> AfterActionReview:
    as_of = _utc(as_of)
    chain = check_chain(conn, keyring, anchors)
    every = [r for r in _records(conn, None) if r.occurred_at <= as_of]
    records = [r for r in every if r.seq <= chain.trusted_to_seq]
    untrusted = [r for r in every if r.seq > chain.trusted_to_seq]
    with conn.cursor(row_factory=dict_row) as cur:
        cases = cur.execute(
            "SELECT decision_case_id, step, title, effective_decide_by_utc FROM decision_case"
        ).fetchall()
        proposal_case = {
            str(r["proposal_id"]): str(r["decision_case_id"])
            for r in cur.execute("SELECT proposal_id, decision_case_id FROM proposal").fetchall()
        }
        table = {
            int(r["break_glass_id"]): dict(r)
            for r in cur.execute(
                "SELECT break_glass_id, proposal_id, ic_id, cosigned_by, cosigned_at FROM break_glass"
            ).fetchall()
        }
    return AfterActionReview(
        as_of=as_of,
        chain=chain,
        clocks=clock_outcomes(cases, proposal_case, records, as_of, chain_ok=chain.ok),
        break_glass=break_glass_uses(records, table, as_of, chain_ok=chain.ok, untrusted=untrusted),
        timeline=[
            TimelineEntry(
                seq=r.seq, occurred_at=r.occurred_at, kind=r.kind, actor_id=r.actor_id, subject=r.subject
            )
            for r in records
            if r.kind in TIMELINE_KINDS
        ],
    )


DECISIONS_OPEN = ("draft", "proposed", "in_review", "escalated")


class MissedCase(_Model):
    decision_case_id: str
    step: str
    title: str
    domain: str
    effective_decide_by: datetime


def missed_unproposed(conn: psycopg.Connection[Any], as_of: datetime) -> list[MissedCase]:
    """Decision cases whose deadline passed at `as_of` without any proposal: missed, as the review counts
    them (`clock_outcomes`: no proposal, so no authority record). Decisions > Closed lists them as "No
    proposal before the deadline" and Ask counts them, so every page counts missed deadlines alike."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT c.decision_case_id, c.step::text AS step, c.title, c.domain::text AS domain,"
            " c.effective_decide_by_utc FROM decision_case c"
            " WHERE c.effective_decide_by_utc < %s"
            " AND NOT EXISTS (SELECT 1 FROM proposal p WHERE p.decision_case_id = c.decision_case_id)"
            " ORDER BY c.effective_decide_by_utc, c.decision_case_id",
            (_utc(as_of),),
        ).fetchall()
    return [
        MissedCase(
            decision_case_id=str(r["decision_case_id"]),
            step=str(r["step"]),
            title=str(r["title"]),
            domain=str(r["domain"]),
            effective_decide_by=_utc(r["effective_decide_by_utc"]),
        )
        for r in rows
    ]


def still_open(conn: psycopg.Connection[Any]) -> frozenset[str]:
    rows = conn.execute(
        "SELECT DISTINCT decision_case_id FROM proposal WHERE state::text = ANY(%s)", (list(DECISIONS_OPEN),)
    ).fetchall()
    return frozenset(str(r[0]) for r in rows)


def counted_clocks(clocks: Sequence[ClockResult], open_cases: frozenset[str]) -> list[ClockResult]:
    """Deadlines counted as Decisions and Ask count them (V4-10): a deadline enters the count once it
    has a proposal or its deadline passed, so one not yet proposed and not yet due is not counted at all;
    one that passed with no decision while its decision is still open is open, missed once the decision
    closed without one (or never got a proposal)."""
    out: list[ClockResult] = []
    for c in clocks:
        if c.outcome == "open" and not c.proposed:
            continue
        if c.outcome == "missed" and c.decided_at is None and c.decision_case_id in open_cases:
            c = c.model_copy(update={"outcome": "open"})
        out.append(c)
    return out


def counted_like_decisions(review_: AfterActionReview, open_cases: frozenset[str]) -> AfterActionReview:
    return review_.model_copy(update={"clocks": counted_clocks(review_.clocks, open_cases)})


ALERT_KIND = "security_alert"


def chain_alert(chain: ChainCheck) -> dict[str, Any]:
    """SEC-52 alert payload for a review that met a broken audit chain."""
    return {
        "code": "SEC-52",
        "kind": "audit_chain_broken",
        "first_bad_seq": chain.first_bad_seq,
        "trusted_to_seq": chain.trusted_to_seq,
        "detail": "after-action review: records after the first bad sequence are unverifiable",
    }


def record_chain_alert(conn: psycopg.Connection[Any], chain: ChainCheck, at: datetime) -> bool:
    """Append one `security_alert` record per first bad sequence (idempotent by event key). The record goes at
    the head of the chain; it does not repair it."""
    if chain.ok:
        return False
    key = f"{ALERT_KIND}:audit_chain_broken:{chain.first_bad_seq}"
    with conn.transaction():
        if conn.execute("SELECT 1 FROM audit_event WHERE event_key = %s", (key,)).fetchone():
            return False
        audit.append(
            conn,
            kind=ALERT_KIND,
            actor_type="system",
            actor_id="system:after_action",
            subject=f"audit_chain:{audit.STREAM}",
            payload=chain_alert(chain),
            occurred_at=at,
            event_key=key,
        )
    return True
