"""Notification feed (K3 `listNotifications`): derived on every read from what the platform already records,
so nothing is written twice and nothing can drift.

- open decisions (approval service summaries): a decision or boil-water notice waiting on the person's
  function, and a deadline within two hours of the scenario clock;
- the audit chain (latest `AUDIT_WINDOW` records): signatures recorded or voided by a re-plan, withdrawn
  decisions, crew assignments waiting for the person's function or signed for their proposal, stop-level and
  mode changes, published ETRs;
- the surge detector at the scenario clock: one item for the counties with an active outage surge.

Only the read marks are stored (`notification_read`, one row per person and item id). Item ids are stable:
an item that changes (a new proposal version, another set of surging counties) gets a new id and is unread.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from sgw.api.sessions import AuthUser
from sgw.contracts.api_models import Notification, NotificationFeed, ProposalSummary, SurgeReport
from sgw.contracts.vocab import ApprovalFunction
from sgw.ops.levels import MODE_LADDER

OPEN_STATES = frozenset({"proposed", "in_review", "escalated"})
DEADLINE_WINDOW = timedelta(hours=2)
AUDIT_WINDOW = 400
MAX_ITEMS = 50
EASTERN = ZoneInfo("America/New_York")
SURGE_FUNCTIONS = frozenset(
    {
        ApprovalFunction.COMMAND,
        ApprovalFunction.OPERATIONS,
        ApprovalFunction.PLANNING,
        ApprovalFunction.LOGISTICS,
        ApprovalFunction.EXECUTIVE,
    }
)
ETR_FUNCTIONS = frozenset(
    {
        ApprovalFunction.COMMAND,
        ApprovalFunction.OPERATIONS,
        ApprovalFunction.PLANNING,
        ApprovalFunction.EXECUTIVE,
    }
)
AUDIT_KINDS = (
    "proposal_created",
    "proposal_revised",
    "approval_recorded",
    "approval_withdrawn",
    "break_glass_used",
    "break_glass_cosigned",
    "proposal_withdrawn",
    "crew_assignment_proposed",
    "crew_assignment_signed",
    "crew_assignment_rejected",
    "crew_assignment_withdrawn",
    "kill_switch_triggered",
    "kill_restore_requested",
    "kill_restore_expired",
    "kill_switch_restored",
    "degraded_mode_set",
    "etr_published",
)
CREW_CLOSED = frozenset({"crew_assignment_signed", "crew_assignment_rejected", "crew_assignment_withdrawn"})
KILL_LABEL = {
    "K0": "Normal",
    "K1": "Signing paused",
    "K2": "AI stopped",
    "K3": "New data and decisions stopped",
    "K4": "Platform off",
}
MODE_LABEL = {rule.mode.value: rule.name for rule in MODE_LADDER}
FUNCTION_LABEL = {
    "command": "Command",
    "operations": "Operations",
    "planning": "Planning",
    "logistics": "Logistics",
    "water_operations": "Water operations",
    "compliance": "Compliance",
    "executive": "Executive",
    "audit": "Audit",
    "platform": "Platform",
    "data": "Data",
}


@dataclass(frozen=True)
class AuditRow:
    seq: int
    at: datetime
    actor_id: str
    kind: str
    subject: str
    payload: dict[str, Any]


def audit_rows(conn: psycopg.Connection[Any], limit: int = AUDIT_WINDOW) -> list[AuditRow]:
    """The latest records of the kinds the feed reads, oldest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT seq, occurred_at, actor_id, kind, subject, payload FROM audit_event"
            " WHERE stream = 'global' AND kind = ANY(%s) ORDER BY seq DESC LIMIT %s",
            (list(AUDIT_KINDS), limit),
        )
        rows = cur.fetchall()
    return [
        AuditRow(
            int(r["seq"]),
            r["occurred_at"],
            str(r["actor_id"]),
            str(r["kind"]),
            str(r["subject"]),
            r["payload"] or {},
        )
        for r in reversed(rows)
    ]


def read_ids(conn: psycopg.Connection[Any], user_id: str, ids: Sequence[str]) -> set[str]:
    rows = conn.execute(
        "SELECT notification_id FROM notification_read WHERE user_id = %s AND notification_id = ANY(%s)",
        (user_id, list(ids)),
    ).fetchall()
    return {str(r[0]) for r in rows}


def mark_read(conn: psycopg.Connection[Any], user_id: str, ids: Iterable[str]) -> None:
    unique = sorted(set(ids))
    if not unique:
        return
    with conn.transaction():
        conn.cursor().executemany(
            "INSERT INTO notification_read (user_id, notification_id) VALUES (%s, %s)"
            " ON CONFLICT (user_id, notification_id) DO NOTHING",
            [(user_id, i) for i in unique],
        )


@dataclass(frozen=True)
class Item:
    rank: int
    order: float
    notification: Notification


def _item(rank: int, order: float, **fields: Any) -> Item:
    return Item(rank, order, Notification(read=False, **fields))


def _decision_href(proposal_id: str) -> str:
    return f"/decisions/{proposal_id}"


def _distinct_titles(open_proposals: Sequence[ProposalSummary]) -> dict[str, str]:
    """A title shared by several open proposals (two proposals on one case) names the decide-by time too, so
    the feed never shows two identical lines."""
    shared = {t for t, n in Counter(p.title for p in open_proposals).items() if n > 1}
    return {
        p.proposal_id: (
            f"{p.title}, decide by {p.effective_decide_by_utc.astimezone(EASTERN):%H:%M} ET"
            if p.title in shared
            else p.title
        )
        for p in open_proposals
    }


WATER_FUNCTIONS = frozenset({ApprovalFunction.WATER_OPERATIONS, ApprovalFunction.COMPLIANCE})


def water_case_ids(conn: psycopg.Connection[Any]) -> frozenset[str]:
    rows = conn.execute("SELECT decision_case_id FROM decision_case WHERE domain = 'water'").fetchall()
    return frozenset(str(r[0]) for r in rows)


def _open_items(
    user: AuthUser,
    proposals: Sequence[ProposalSummary],
    now: datetime,
    touched: dict[str, datetime],
    water_cases: frozenset[str] = frozenset(),
) -> list[Item]:
    items: list[Item] = []
    open_proposals = [p for p in proposals if p.state in OPEN_STATES]
    titles = _distinct_titles(open_proposals)
    for p in open_proposals:
        signed = {a.function for a in p.approvals if a.decision == "approve"}
        mine = any(a.approver_id == user.user_id for a in p.approvals)
        waiting = [f for f in p.functions_required if f not in signed]
        if user.function in waiting and not mine and p.proposed_by.user_id != user.user_id:
            bwn = p.action_type == "boil_water_notice"
            items.append(
                _item(
                    0,
                    p.effective_decide_by_utc.timestamp(),
                    notification_id=f"waiting:{p.proposal_id}:v{p.proposal_version}",
                    kind="boil_water_due" if bwn else "decision_waiting",
                    title="Boil-water notice waiting on you" if bwn else "Decision waiting on you",
                    detail=titles[p.proposal_id],
                    at=touched.get(p.proposal_id, now),
                    href=_decision_href(p.proposal_id),
                )
            )
        if (
            user.function in WATER_FUNCTIONS
            and user.function not in p.functions_required
            and p.decision_case_id in water_cases
        ):
            items.append(
                _item(
                    1,
                    p.effective_decide_by_utc.timestamp(),
                    notification_id=f"water:{p.proposal_id}",
                    kind="water_decision_open",
                    title="Water decision open",
                    detail=titles[p.proposal_id],
                    at=touched.get(p.proposal_id, now),
                    href=_decision_href(p.proposal_id),
                )
            )
        left = p.effective_decide_by_utc - now
        concerned = (
            user.function in p.functions_required
            or user.function is ApprovalFunction.COMMAND
            or p.proposed_by.user_id == user.user_id
        )
        if concerned and timedelta(0) < left <= DEADLINE_WINDOW:
            items.append(
                _item(
                    0,
                    p.effective_decide_by_utc.timestamp() - 1,
                    notification_id=f"deadline:{p.proposal_id}:{p.effective_decide_by_utc:%Y%m%dT%H%M}",
                    kind="deadline_soon",
                    title="Deadline in under 2 hours",
                    detail=titles[p.proposal_id],
                    at=p.effective_decide_by_utc - DEADLINE_WINDOW,
                    href=_decision_href(p.proposal_id),
                )
            )
    return items


def _shown_at(r: AuditRow) -> datetime:
    """Stop-level records run on the wall clock and carry the scenario time beside it; the feed shows that."""
    raw = r.payload.get("scenario_at")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return r.at
    return r.at


def _audit_items(
    user: AuthUser,
    rows: Sequence[AuditRow],
    proposals: dict[str, ProposalSummary],
    wall_now: datetime | None = None,
) -> list[Item]:
    approvers: dict[str, str] = {}
    withdrawn: set[str] = set()
    cosigned: set[str] = set()
    restore_closed: set[str] = set()
    crew_proposer: dict[str, str] = {}
    crew_closed: set[str] = set()
    signer_function: dict[str, str] = {}
    voided: dict[str, set[str]] = {}
    last_void: dict[str, int] = {}
    for r in rows:
        if r.kind == "approval_recorded" and "approval_id" in r.payload:
            approvers[str(r.payload["approval_id"])] = r.actor_id
            signer_function[str(r.payload["approval_id"])] = str(r.payload.get("function"))
        if r.kind == "proposal_revised" and r.payload.get("voided_approval_ids"):
            voided.setdefault(r.subject, set()).update(str(a) for a in r.payload["voided_approval_ids"])
            last_void[r.subject] = r.seq
        if r.kind == "crew_assignment_proposed":
            crew_proposer[r.subject] = r.actor_id
        if r.kind in CREW_CLOSED:
            crew_closed.add(r.subject)
        if r.kind == "approval_withdrawn" and r.payload.get("signature_withdrawn"):
            withdrawn.add(str(r.payload["signature_withdrawn"]))
        if r.kind == "break_glass_cosigned":
            cosigned.add(str(r.payload.get("break_glass_id")))
        if r.kind in ("kill_switch_restored", "kill_restore_expired") and r.payload.get("restore_id"):
            restore_closed.add(str(r.payload["restore_id"]))
    voided_ids = set().union(*voided.values()) if voided else set()
    me, function = user.user_id, user.function.value
    items: list[Item] = []

    def add(r: AuditRow, kind: str, title: str, detail: str | None, href: str, rank: int = 1) -> None:
        items.append(
            _item(
                rank,
                -r.seq,
                notification_id=f"audit:{r.seq}",
                kind=kind,
                title=title,
                detail=detail,
                at=_shown_at(r),
                href=href,
            )
        )

    for r in rows:
        if r.actor_id == me:
            continue
        p = proposals.get(r.subject)
        involved = p is not None and (
            p.proposed_by.user_id == me
            or function in [f.value for f in p.functions_required]
            or any(a.approver_id == me for a in p.approvals)
        )
        if r.kind == "approval_recorded" and p is not None and involved:
            if str(r.payload.get("approval_id")) in voided_ids | withdrawn:
                continue
            approved = r.payload.get("decision") == "approve"
            who = FUNCTION_LABEL.get(str(r.payload.get("function")), "Someone")
            notice = p.action_type == "boil_water_notice" and "boil" not in p.title.lower()
            add(
                r,
                "signature_recorded",
                f"{who} signed" if approved else f"{who} sent it back",
                f"Boil-water notice: {p.title}" if notice else p.title,
                _decision_href(p.proposal_id),
            )
        elif r.kind == "proposal_revised" and p is not None and last_void.get(r.subject) == r.seq:
            ids = voided[r.subject]
            if any(approvers.get(a) == me for a in ids):
                add(
                    r,
                    "signature_voided",
                    "Your signature was voided by a re-plan",
                    p.title,
                    _decision_href(p.proposal_id),
                )
            elif involved:
                teams = sorted(
                    {FUNCTION_LABEL.get(signer_function[a], "A") for a in ids & signer_function.keys()}
                )
                if teams:
                    noun = "signatures were" if len(teams) > 1 else "signature was"
                    add(
                        r,
                        "signature_voided",
                        f"{' and '.join(teams)} {noun} voided by a re-plan",
                        p.title,
                        _decision_href(p.proposal_id),
                    )
        elif r.kind == "approval_withdrawn" and p is not None and involved:
            who = FUNCTION_LABEL.get(str(r.payload.get("function")), "Someone")
            add(
                r,
                "signature_withdrawn",
                f"{who} withdrew its signature",
                p.title,
                _decision_href(p.proposal_id),
            )
        elif r.kind == "break_glass_used" and p is not None and involved:
            pending = str(r.payload.get("break_glass_id")) not in cosigned
            if pending and function in [str(f) for f in r.payload.get("cosign_functions") or []]:
                add(
                    r,
                    "cosign_waiting",
                    "Emergency approval needs your co-sign",
                    p.title,
                    _decision_href(p.proposal_id),
                    rank=0,
                )
            else:
                add(r, "emergency_approval", "Command approved alone", p.title, _decision_href(p.proposal_id))
        elif r.kind == "break_glass_cosigned" and p is not None and involved:
            who = FUNCTION_LABEL.get(str(r.payload.get("function")), "Someone")
            add(
                r,
                "emergency_approval",
                f"{who} co-signed the emergency approval",
                p.title,
                _decision_href(p.proposal_id),
            )
        elif r.kind == "proposal_withdrawn" and p is not None and involved:
            add(r, "proposal_withdrawn", "Decision withdrawn", p.title, _decision_href(p.proposal_id))
        elif r.kind == "crew_assignment_proposed":
            if r.payload.get("required_function") == function and r.subject not in crew_closed:
                crew = str(r.payload.get("crew_id", ""))
                add(
                    r,
                    "crew_signature_waiting",
                    "Crew assignment waiting for your signature",
                    crew,
                    f"/crews?crew={crew}",
                )
        elif (
            r.kind in ("crew_assignment_signed", "crew_assignment_rejected")
            and crew_proposer.get(r.subject) == me
        ):
            crew = str(r.payload.get("crew_id", ""))
            approved = r.kind == "crew_assignment_signed" and r.payload.get("decision") == "approve"
            add(
                r,
                "crew_assignment_signed" if approved else "crew_assignment_rejected",
                "Crew assignment signed" if approved else "Crew assignment rejected",
                crew if approved or not r.payload.get("reason") else f"{crew}: {r.payload['reason']}",
                f"/crews?crew={crew}",
            )
        elif r.kind == "kill_restore_requested" and r.payload.get("awaiting_function") == function:
            ttl = timedelta(seconds=int(r.payload.get("expires_in_s") or 0))
            live = wall_now is None or r.at + ttl > wall_now
            if str(r.payload.get("restore_id")) not in restore_closed and live:
                who = FUNCTION_LABEL.get(str(r.payload.get("function")), "Someone")
                level = KILL_LABEL.get(str(r.payload.get("to", "")), "Normal")
                minutes = int(ttl.total_seconds() // 60)
                add(
                    r,
                    "restore_waiting",
                    "Resume waiting for your signature",
                    f"{who} asked to return to {level}. Sign within {minutes} minutes.",
                    "/health?tab=safety",
                    rank=0,
                )
        elif r.kind in ("kill_switch_triggered", "kill_switch_restored"):
            level = str(r.payload.get("to", ""))
            add(
                r,
                "stop_level_changed",
                f"Stop level: {KILL_LABEL.get(level, level)}",
                r.payload.get("reason"),
                "/health?tab=safety",
            )
        elif r.kind == "degraded_mode_set":
            mode = str((r.payload.get("degraded_mode") or {}).get("to", ""))
            add(
                r,
                "mode_changed",
                f"Operating mode: {MODE_LABEL.get(mode, mode)}",
                r.payload.get("reason"),
                "/health?tab=safety",
            )
        elif r.kind == "etr_published" and user.function in ETR_FUNCTIONS:
            add(r, "etr_published", "Restoration estimate published", None, "/after-action")
    return items


def _surge_items(user: AuthUser, report: SurgeReport | None) -> list[Item]:
    if report is None or user.function not in SURGE_FUNCTIONS:
        return []
    active = sorted((s for s in report.surges if s.status == "active"), key=lambda s: s.detected_at)
    if not active:
        return []
    names = [f"{s.county}, {s.state}" for s in active]
    more = len(names) - 3
    detail = "; ".join(names[:3]) + (f" and {more} more" if more > 0 else "")
    digest = hashlib.sha256(",".join(sorted(s.surge_id for s in active)).encode()).hexdigest()[:16]
    count = len(active)
    return [
        _item(
            0,
            float("inf"),
            notification_id=f"surge:{digest}",
            kind="surge_detected",
            title=f"Outage surge in {count} {'county' if count == 1 else 'counties'}",
            detail=detail,
            at=active[-1].detected_at,
            href="/map",
        )
    ]


def build(
    user: AuthUser,
    proposals: Sequence[ProposalSummary],
    rows: Sequence[AuditRow],
    report: SurgeReport | None,
    now: datetime,
    wall_now: datetime | None = None,
    water_cases: frozenset[str] = frozenset(),
) -> list[Notification]:
    """The person's items, newest first. What needs them now is kept first when the feed is cut to size."""
    touched = {r.subject: r.at for r in rows if r.kind in ("proposal_created", "proposal_revised")}
    by_id = {p.proposal_id: p for p in proposals}
    items = (
        _open_items(user, proposals, now, touched, water_cases)
        + _surge_items(user, report)
        + _audit_items(user, rows, by_id, wall_now or datetime.now(UTC))
    )
    items.sort(key=lambda i: (i.rank, i.order))
    kept = items[:MAX_ITEMS]
    kept.sort(key=lambda i: (-i.notification.at.timestamp(), i.rank, i.order))
    return [i.notification for i in kept]


def with_read_marks(
    conn: psycopg.Connection[Any], user_id: str, items: Sequence[Notification]
) -> NotificationFeed:
    seen = read_ids(conn, user_id, [i.notification_id for i in items])
    marked = [i.model_copy(update={"read": i.notification_id in seen}) for i in items]
    return NotificationFeed(items=marked, unread=sum(1 for i in marked if not i.read))
