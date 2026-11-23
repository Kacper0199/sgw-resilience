"""Commitment watch: an approved decision becomes a commitment; drift reopens the decision.

`DecisionApproved` creates a commitment for the approved proposal with milestones from its case's clock
basis (`plan.build_plan`). Ledger events mark milestones met; every event time and every watch tick
re-assesses the open commitments (`watch.assess`). A transition to `at_risk`, `drifted` or `missed` writes a
`commitment_drift` row, an audit record and a K2 `CommitmentDrifted` event through the transactional
outbox. `drifted` reopens the decision: the approval service revises the proposal with the precondition
`commitment_on_track = false`, a material change that voids the signatures and puts the proposal back to
`proposed`. A material input change (the case's decide-by moving earlier than the promise can absorb)
drifts the commitment the same way.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg import pq
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sgw.approval import audit
from sgw.approval.errors import ApprovalError
from sgw.approval.ledger import LedgerSink
from sgw.approval.service import ApprovalService, Revision
from sgw.contracts.base import Contract
from sgw.contracts.events import EVENT_MODELS, CommitmentCreated, CommitmentDrifted, EnvelopeBase
from sgw.contracts.vocab import ActionType, Classification, CommitmentState, FeedMode, RunMode, Trust
from sgw.models.commitments import plan as plans
from sgw.models.commitments import watch
from sgw.models.commitments.plan import Milestone

log = logging.getLogger("sgw.commitments")
NO_COMMITMENT_ACTIONS = frozenset({ActionType.POLICY_CHANGE.value})
ACTOR = "system:commitment-watch"
ORIGIN = "commitments"
SOURCE_ID = "sgw-platform"
NAMESPACE = uuid.UUID("3c8e0d52-38a1-4b7e-9f0c-ceda0fa11038")
OPEN = frozenset({CommitmentState.ON_TRACK.value, CommitmentState.AT_RISK.value})
ALERT = frozenset({CommitmentState.AT_RISK, CommitmentState.DRIFTED, CommitmentState.MISSED})
PRECONDITION = "commitment_on_track"
APPROVED = frozenset({"approved", "executed"})


def envelope(payload: Contract, *, at: datetime, key: str, region_id: str, domain: str) -> EnvelopeBase:
    type_name = type(payload).__name__
    dedup = f"{ORIGIN}:{type_name}:{key}"
    return EVENT_MODELS[type_name].model_validate(
        {
            "type": type_name,
            "event_id": uuid.uuid5(NAMESPACE, dedup),
            "source_id": SOURCE_ID,
            "feed_mode": FeedMode.SYNTHETIC,
            "run_mode": RunMode.REPLAY,
            "event_time": at,
            "received_at": at,
            "known_at": at,
            "scenario_known_at": at,
            "dedup_key": dedup,
            "classification": Classification.C2 if domain == "water" else Classification.C1,
            "trust": Trust.SYSTEM,
            "region_id": region_id,
            "domain": domain,
            "payload": payload,
        }
    )


class OutboxSink:
    """WP-07 outbox and relay under the `commitments` origin."""

    def enqueue(self, conn: psycopg.Connection[Any], events: Sequence[EnvelopeBase]) -> int:
        from sgw.ingest import outbox

        return int(outbox.enqueue(conn, list(events), origin=ORIGIN))

    def drain(self, conn: psycopg.Connection[Any]) -> None:
        from sgw.ingest import relay

        relay.drain(conn)


def commitment_id_for(proposal_id: str, version: int) -> str:
    return f"CMT-{proposal_id}-V{version}"


@dataclass
class Result:
    created: list[str] = field(default_factory=list)
    drifted: list[dict[str, Any]] = field(default_factory=list)
    reopened: list[str] = field(default_factory=list)
    events: list[Contract] = field(default_factory=list)


class CommitmentWatch:
    def __init__(
        self,
        approvals: ApprovalService | None,
        *,
        ledger: LedgerSink | None = None,
        tolerance_min: int | None = None,
    ) -> None:
        self.approvals = approvals
        self.ledger = ledger
        self.tolerance_min = plans.drift_tolerance_min() if tolerance_min is None else tolerance_min
        self._seen: dict[str, dict[int, set[str]]] = {}

    # ---- plumbing --------------------------------------------------------------------------------------

    def _emit(
        self, conn: psycopg.Connection[Any], row: Mapping[str, Any], key: str, event: Contract, at: datetime
    ) -> None:
        if self.ledger is None:
            return
        self.ledger.enqueue(
            conn, [envelope(event, at=at, key=key, region_id=row["region_id"], domain=row["domain"])]
        )

    def drain(self, conn: psycopg.Connection[Any]) -> None:
        idle = conn.info.transaction_status == pq.TransactionStatus.IDLE
        if self.ledger is not None and conn.autocommit and idle:
            try:
                self.ledger.drain(conn)
            except Exception:
                log.warning("ledger drain after commit failed; the relay will retry", exc_info=True)

    @staticmethod
    def _audit(
        conn: psycopg.Connection[Any],
        kind: str,
        subject: str,
        payload: dict[str, Any],
        at: datetime,
        key: str,
    ) -> None:
        audit.append(
            conn,
            kind=kind,
            actor_type="system",
            actor_id=ACTOR,
            subject=subject,
            payload=payload,
            occurred_at=at,
            event_key=f"{kind}:{key}",
        )

    # ---- create ----------------------------------------------------------------------------------------

    def on_decision_approved(
        self, conn: psycopg.Connection[Any], *, proposal_id: str, proposal_version: int, at: datetime
    ) -> str | None:
        """Create the commitment for an approved proposal version; idempotent. None when the case's lead time
        has no milestone plan (the commitment watch covers the field actions with observable steps)."""
        cid = commitment_id_for(proposal_id, proposal_version)
        with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            if cur.execute("SELECT 1 FROM commitment WHERE commitment_id = %s", (cid,)).fetchone():
                return None
            row = cur.execute(
                "SELECT p.proposal_id, p.action_type, p.decision_case_id, p.params, p.targets, p.region_id,"
                " p.domain,"
                " p.state, p.proposal_version, c.consequence_utc, c.lead_time_basis, c.action_lead_time_min"
                " FROM proposal p JOIN decision_case c USING (decision_case_id) WHERE p.proposal_id = %s",
                (proposal_id,),
            ).fetchone()
            if row is None or row["state"] not in APPROVED or row["proposal_version"] != proposal_version:
                return None
            if row["action_type"] in NO_COMMITMENT_ACTIONS or not row["targets"]:
                log.info("%s (%s) promises no field action; no commitment", proposal_id, row["action_type"])
                return None
            lead_key = plans.lead_key_of(row["lead_time_basis"])
            if lead_key is None or not plans.supported(lead_key):
                log.info("no milestone plan for %s (lead %s); no commitment", proposal_id, lead_key)
                return None
            params = dict(row["params"])
            targets = list(row["targets"])
            bindings = {
                "$station": str(params.get("station_id") or targets[0]),
                "$generator": str(
                    params.get("generator_id") or params.get("portable_generator_id") or targets[0]
                ),
                "$targets": targets,
            }
            schedule = plans.build_plan(lead_key, row["consequence_utc"], bindings)
            cur.execute(
                "INSERT INTO commitment (commitment_id, decision_case_id, proposal_id, promised_by_utc,"
                " projected_utc, state, created_at) VALUES (%s, %s, %s, %s, %s, 'on_track', %s)",
                (
                    cid,
                    row["decision_case_id"],
                    proposal_id,
                    schedule.promised_by_utc,
                    schedule.promised_by_utc,
                    at,
                ),
            )
            for m in schedule.milestones:
                cur.execute(
                    "INSERT INTO commitment_milestone (commitment_id, seq, name, due_utc)"
                    " VALUES (%s, %s, %s, %s)",
                    (cid, m.seq, m.name, m.due_utc),
                )
                cur.execute(
                    "INSERT INTO commitment_milestone_plan"
                    " (commitment_id, seq, lead_key, remaining_min, signal)"
                    " VALUES (%s, %s, %s, %s, %s)",
                    (cid, m.seq, m.lead_key, m.remaining_min, Jsonb(dict(m.signal))),
                )
            self._audit(
                conn,
                "commitment_created",
                cid,
                {
                    "proposal_id": proposal_id,
                    "proposal_version": proposal_version,
                    "decision_case_id": row["decision_case_id"],
                    "promised_by_utc": schedule.promised_by_utc.isoformat(),
                    "lead_key": lead_key,
                    "milestones": [
                        {"seq": m.seq, "name": m.name, "due_utc": m.due_utc.isoformat()}
                        for m in schedule.milestones
                    ],
                    "policy_version": plans.policy_version(),
                },
                at,
                cid,
            )
            event = CommitmentCreated(
                commitment_id=cid,
                decision_case_id=row["decision_case_id"],
                proposal_id=proposal_id,
                promised_by_utc=schedule.promised_by_utc,
                milestones=[m.name for m in schedule.milestones],
            )
            self._emit(conn, row, f"{cid}:created", event, at)
        self.drain(conn)
        return cid

    # ---- observe and assess ----------------------------------------------------------------------------

    @staticmethod
    def _open(conn: psycopg.Connection[Any], case_id: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT m.commitment_id, m.decision_case_id, m.proposal_id, m.promised_by_utc, m.state,"
            " p.region_id, p.domain, p.proposal_version, p.preconditions, p.state AS proposal_state"
            " FROM commitment m JOIN proposal p USING (proposal_id)"
            " WHERE m.state = ANY(%s)"
        )
        args: list[Any] = [list(OPEN)]
        if case_id is not None:
            sql += " AND m.decision_case_id = %s"
            args.append(case_id)
        with conn.cursor(row_factory=dict_row) as cur:
            return list(cur.execute(sql + " ORDER BY m.commitment_id", args).fetchall())

    @staticmethod
    def milestones(conn: psycopg.Connection[Any], commitment_id: str) -> list[Milestone]:
        with conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(
                "SELECT m.seq, m.name, m.due_utc, m.met_utc, p.lead_key, p.remaining_min, p.signal,"
                " p.met_event_id"
                " FROM commitment_milestone m JOIN commitment_milestone_plan p USING (commitment_id, seq)"
                " WHERE m.commitment_id = %s ORDER BY m.seq",
                (commitment_id,),
            ).fetchall()
        return [
            Milestone(
                seq=r["seq"],
                name=r["name"],
                due_utc=r["due_utc"],
                remaining_min=r["remaining_min"],
                signal=r["signal"],
                lead_key=r["lead_key"],
                met_utc=r["met_utc"],
                met_event_id=str(r["met_event_id"]) if r["met_event_id"] else None,
            )
            for r in rows
        ]

    def on_event(self, conn: psycopg.Connection[Any], event: Mapping[str, Any]) -> Result:
        """Apply one ledger event (a dict in K2 envelope shape) to the open commitments, then assess them."""
        at = watch.event_time(event)
        result = Result()
        etype = event.get("type")
        if etype == "DecisionApproved":
            p = event["payload"]
            cid = self.on_decision_approved(
                conn, proposal_id=p["proposal_id"], proposal_version=int(p["proposal_version"]), at=at
            )
            if cid:
                result.created.append(cid)
            return result
        if etype == "DecisionClockUpdated":
            self._input_change(conn, event, at, result)
        for row in self._open(conn):
            before = self.milestones(conn, row["commitment_id"])
            after = watch.observe(before, event, self._seen.setdefault(row["commitment_id"], {}))
            changed = [m for m, b in zip(after, before, strict=True) if m.met_utc != b.met_utc]
            for m in changed:
                conn.execute(
                    "UPDATE commitment_milestone SET met_utc = %s WHERE commitment_id = %s AND seq = %s",
                    (m.met_utc, row["commitment_id"], m.seq),
                )
                conn.execute(
                    "UPDATE commitment_milestone_plan SET met_event_id = %s"
                    " WHERE commitment_id = %s AND seq = %s",
                    (m.met_event_id, row["commitment_id"], m.seq),
                )
        self._assess_all(conn, at, result)
        return result

    def tick(self, conn: psycopg.Connection[Any], now: datetime) -> Result:
        result = Result()
        self._assess_all(conn, now, result)
        return result

    def _assess_all(self, conn: psycopg.Connection[Any], now: datetime, result: Result) -> None:
        for row in self._open(conn):
            ms = self.milestones(conn, row["commitment_id"])
            a = watch.assess(ms, row["promised_by_utc"], now, self.tolerance_min)
            if a.state.value == row["state"]:
                conn.execute(
                    "UPDATE commitment SET projected_utc = %s WHERE commitment_id = %s",
                    (a.projected_utc, row["commitment_id"]),
                )
                continue
            self._transition(
                conn,
                row,
                a.state,
                a.projected_utc,
                a.drift_min,
                a.milestone_seq,
                "milestone_late",
                now,
                result,
            )
        self.drain(conn)

    def _input_change(
        self, conn: psycopg.Connection[Any], event: Mapping[str, Any], at: datetime, result: Result
    ) -> None:
        p = event["payload"]
        case = conn.execute(
            "SELECT action_lead_time_min FROM decision_case WHERE decision_case_id = %s",
            (p["decision_case_id"],),
        ).fetchone()
        if case is None:
            return
        decide_by = datetime.fromisoformat(str(p["decide_by_utc"]).replace("Z", "+00:00"))
        consequence = decide_by + timedelta(minutes=int(case[0]))
        for row in self._open(conn, p["decision_case_id"]):
            overshoot = watch.ceil_min(row["promised_by_utc"] - consequence)
            if overshoot > self.tolerance_min:
                self._transition(
                    conn,
                    row,
                    CommitmentState.DRIFTED,
                    row["promised_by_utc"],
                    overshoot,
                    None,
                    "input_changed",
                    at,
                    result,
                    note=f"decide-by moved to {decide_by.isoformat()};"
                    f" consequence now {consequence.isoformat()}",
                )

    # ---- transition and reopen -------------------------------------------------------------------------

    def _transition(
        self,
        conn: psycopg.Connection[Any],
        row: Mapping[str, Any],
        state: CommitmentState,
        projected: datetime,
        drift_min: int,
        milestone_seq: int | None,
        reason: str,
        at: datetime,
        result: Result,
        note: str = "",
    ) -> None:
        cid = row["commitment_id"]
        with conn.transaction():
            conn.execute(
                "UPDATE commitment SET state = %s, projected_utc = %s WHERE commitment_id = %s",
                (state.value, projected, cid),
            )
            if state not in ALERT:
                return
            seq_row = conn.execute(
                "SELECT coalesce(max(seq), 0) + 1 FROM commitment_drift WHERE commitment_id = %s", (cid,)
            ).fetchone()
            seq = int(seq_row[0]) if seq_row else 1
            reopened, version, reopen_note = False, None, ""
            if state is CommitmentState.DRIFTED:
                reopened, version, reopen_note = self._reopen(conn, row, drift_min, reason)
            conn.execute(
                "INSERT INTO commitment_drift (commitment_id, seq, detected_at, state, reason, milestone_seq,"
                " promised_by_utc, projected_utc, drift_min, tolerance_min, reopened, proposal_version, note)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    cid,
                    seq,
                    at,
                    state.value,
                    reason,
                    milestone_seq,
                    row["promised_by_utc"],
                    projected,
                    drift_min,
                    self.tolerance_min,
                    reopened,
                    version,
                    "; ".join(x for x in (note, reopen_note) if x),
                ),
            )
            self._audit(
                conn,
                "commitment_drifted",
                cid,
                {
                    "state": state.value,
                    "reason": reason,
                    "milestone_seq": milestone_seq,
                    "promised_by_utc": row["promised_by_utc"].isoformat(),
                    "projected_utc": projected.isoformat(),
                    "drift_min": drift_min,
                    "tolerance_min": self.tolerance_min,
                    "reopened": reopened,
                    "proposal_id": row["proposal_id"],
                    "proposal_version_after": version,
                },
                at,
                f"{cid}:{seq}",
            )
            event = CommitmentDrifted(
                commitment_id=cid,
                state=state,
                promised_by_utc=row["promised_by_utc"],
                projected_utc=projected,
                drift_min=drift_min,
            )
            self._emit(conn, row, f"{cid}:drift:{seq}", event, at)
        result.events.append(event)
        result.drifted.append(
            {"commitment_id": cid, "state": state.value, "drift_min": drift_min, "reason": reason}
        )
        if reopened:
            result.reopened.append(row["proposal_id"])

    def _reopen(
        self, conn: psycopg.Connection[Any], row: Mapping[str, Any], drift_min: int, reason: str
    ) -> tuple[bool, int | None, str]:
        if self.approvals is None:
            return False, None, "no approval service: decision not reopened"
        preconditions = {str(k): bool(v) for k, v in dict(row["preconditions"]).items()}
        preconditions[PRECONDITION] = False
        why = f"commitment {row['commitment_id']} drifted {drift_min} min ({reason}); decision reopened"
        try:
            outcome = self.approvals.revise(
                conn,
                actor=ACTOR,
                proposal_id=row["proposal_id"],
                change=Revision(preconditions=preconditions),
                reason=why,
            )
        except ApprovalError as error:
            log.warning("reopen of %s refused: %s", row["proposal_id"], error)
            return False, None, f"reopen refused: {error}"
        return True, outcome.value.proposal_version, ""


def replay(
    conn: psycopg.Connection[Any],
    watcher: CommitmentWatch,
    events: Iterable[Mapping[str, Any]],
    *,
    tick_min: int | None = None,
    until: datetime | None = None,
    set_time: Callable[[datetime], None] | None = None,
) -> Result:
    """Feed ledger events in event-time order and assess the open commitments on a tick grid between events.
    `set_time` moves the scenario clock the approval service reads (a reopen is stamped at replay time)."""
    step = timedelta(minutes=tick_min or watcher.tolerance_min)
    total = Result()
    ordered = sorted(events, key=lambda e: (watch.event_time(e), str(e.get("dedup_key", ""))))
    last: datetime | None = None
    for event in ordered:
        at = watch.event_time(event)
        if until is not None and at > until:
            break
        if last is not None:
            t = last + step
            while t < at:
                if set_time is not None:
                    set_time(t)
                _merge(total, watcher.tick(conn, t))
                t += step
        if set_time is not None:
            set_time(at)
        _merge(total, watcher.on_event(conn, event))
        last = at
    return total


def _merge(total: Result, part: Result) -> None:
    total.created.extend(part.created)
    total.drifted.extend(part.drifted)
    total.reopened.extend(part.reopened)
    total.events.extend(part.events)
