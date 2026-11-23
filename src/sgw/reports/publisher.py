"""ETR publication after the D4 T3 approval: one K2 `EtrPublished` per estimate (global and operating areas).

The approved action binds the exact publication: the global estimate id, its P25/P50/P75 and a digest of every
estimate (`estimates_digest`: ids and quantiles of the global estimate and all operating areas) are proposal
params, so they are inside the action hash the two functions approved.

`OutboxEtrPublisher` publishes in one transaction: lock the proposal, check that the stored version and hash
are the ones the run showed and that the estimates to publish match the approved params, burn the execution
token through the approval service (proposal -> executed, effect row, `execution_token_burned` audit record),
queue the events through WP-07's outbox and append `etr_published` to the audit chain; it drains after commit.
A second execution meets a burned token and raises `AlreadyPublished` (409), never a database error.
`MemoryEtrPublisher` applies the same estimate checks for replay and tests.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sgw.approval import audit
from sgw.approval import repository as repo
from sgw.approval.errors import ApprovalError
from sgw.approval.ledger import LedgerSink, envelope
from sgw.approval.service import ApprovalService
from sgw.contracts.events import EnvelopeBase, EtrPublished
from sgw.models.restoration.publish import EtrEstimate

ETR_CHANNEL = "etr_publication"


class NotApproved(RuntimeError):
    """The store does not hold an approved publication for exactly these estimates (version, hash, params)."""


class AlreadyPublished(RuntimeError):
    status = 409
    code = "ETR_ALREADY_PUBLISHED"


def estimates_digest(estimates: Sequence[EtrEstimate]) -> str:
    rows = sorted(
        [
            e.estimate_id,
            e.p10_utc.isoformat(),
            e.p25_utc.isoformat(),
            e.p50_utc.isoformat(),
            e.p75_utc.isoformat(),
            e.p90_utc.isoformat(),
        ]
        for e in estimates
    )
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def global_of(estimates: Sequence[EtrEstimate]) -> EtrEstimate:
    found = [e for e in estimates if e.scope == "global"]
    if len(found) != 1:
        raise NotApproved(f"expected one global estimate, found {len(found)}")
    return found[0]


def approved_params(estimates: Sequence[EtrEstimate]) -> dict[str, int | str | bool | list[str]]:
    g = global_of(estimates)
    return {
        "estimate_id": g.estimate_id,
        "as_of_utc": g.as_of_utc.isoformat(),
        "p25_utc": g.p25_utc.isoformat(),
        "p50_utc": g.p50_utc.isoformat(),
        "p75_utc": g.p75_utc.isoformat(),
        "model_version": g.model_version,
        "replay_overlay_allowed": g.replay_overlay_allowed,
        "estimates_digest": estimates_digest(estimates),
    }


def check_matches(params: Mapping[str, Any], estimates: Sequence[EtrEstimate]) -> None:
    """The estimates match the approved params, and the global event to publish carries the stored estimate
    id and P50."""
    want = approved_params(estimates)
    for key in ("estimate_id", "p50_utc", "estimates_digest"):
        if params.get(key) != want[key]:
            raise NotApproved(f"{key} differs from the approved publication")
    first = events_for(estimates)[0]
    if first.estimate_id != params["estimate_id"] or first.p50_utc.isoformat() != params["p50_utc"]:
        raise NotApproved("the global event differs from the approved estimate")


def store_revision(conn: psycopg.Connection[Any], estimates: Sequence[EtrEstimate]) -> bool:
    """A published revision (estimates re-issued at the scenario time, not a stored WP-17 issue) is kept as
    the ETR snapshot of its issue time, so the estimate shown from then on is the published one."""
    g = global_of(estimates)
    stored = conn.execute(
        "SELECT 1 FROM snapshot WHERE kind = 'etr' AND output @> %s LIMIT 1",
        (Jsonb([{"estimate_id": g.estimate_id}]),),
    ).fetchone()
    if stored is not None:
        return False
    output = [e.model_dump(mode="json") for e in estimates]
    digest = hashlib.sha256(json.dumps(output, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    conn.execute(
        "INSERT INTO snapshot (snapshot_id, kind, as_of, engine_version, hash, output)"
        " VALUES (%s, 'etr', %s, %s, %s, %s) ON CONFLICT (snapshot_id) DO NOTHING",
        (
            f"ETR-SNAP-REV-{g.as_of_utc.strftime('%Y%m%dT%H%MZ')}",
            g.as_of_utc,
            f"{g.model_version} revised",
            digest,
            Jsonb(output),
        ),
    )
    return True


def events_for(estimates: Sequence[EtrEstimate]) -> list[EtrPublished]:
    return [
        EtrPublished(
            estimate_id=e.estimate_id,
            scope=e.scope,
            region_id=e.region_id,
            as_of_utc=e.as_of_utc,
            p10_utc=e.p10_utc,
            p25_utc=e.p25_utc,
            p50_utc=e.p50_utc,
            p75_utc=e.p75_utc,
            p90_utc=e.p90_utc,
            peak_customers_out=e.peak_customers_out,
            model_version=e.model_version,
        )
        for e in sorted(estimates, key=lambda e: (e.scope != "global", e.region_id))
    ]


def envelopes_for(events: Sequence[EtrPublished], at: datetime) -> list[EnvelopeBase]:
    return [
        envelope(
            e,
            at=at,
            key=e.estimate_id,
            region_id=None if e.scope == "global" else e.region_id,
            domain="electric",
        )
        for e in events
    ]


@dataclass(frozen=True)
class Publication:
    events: list[EtrPublished]
    effect_id: str


class EtrPublisher(Protocol):
    def publish(
        self,
        proposal_id: str,
        estimates: Sequence[EtrEstimate],
        *,
        proposal_version: int,
        action_hash: str,
        params: Mapping[str, Any],
        published_by: str,
        at: datetime,
    ) -> Publication: ...


@dataclass
class MemoryEtrPublisher:
    published: list[EnvelopeBase] = field(default_factory=list)
    executed: set[str] = field(default_factory=set)

    def publish(
        self,
        proposal_id: str,
        estimates: Sequence[EtrEstimate],
        *,
        proposal_version: int,
        action_hash: str,
        params: Mapping[str, Any],
        published_by: str,
        at: datetime,
    ) -> Publication:
        check_matches(params, estimates)
        if proposal_id in self.executed:
            raise AlreadyPublished(f"proposal {proposal_id} was already published")
        self.executed.add(proposal_id)
        events = events_for(estimates)
        self.published.extend(envelopes_for(events, at))
        return Publication(events, f"EFF-{proposal_id}")


@dataclass
class OutboxEtrPublisher:
    connect: Callable[[], psycopg.Connection[Any]]
    sink: LedgerSink
    approvals: ApprovalService

    def publish(
        self,
        proposal_id: str,
        estimates: Sequence[EtrEstimate],
        *,
        proposal_version: int,
        action_hash: str,
        params: Mapping[str, Any],
        published_by: str,
        at: datetime,
    ) -> Publication:
        events = events_for(estimates)
        with self.connect() as conn:
            with conn.transaction():
                with conn.cursor(row_factory=dict_row) as cur:
                    row = cur.execute(
                        "SELECT state, action_type, proposal_version, action_hash, params FROM proposal"
                        " WHERE proposal_id = %s FOR UPDATE",
                        (proposal_id,),
                    ).fetchone()
                if row is None or row["action_type"] != "publish_global_etr":
                    raise NotApproved(f"proposal {proposal_id} is not a global ETR publication")
                if row["state"] == "executed":
                    raise AlreadyPublished(f"proposal {proposal_id} was already published")
                if row["state"] != "approved":
                    raise NotApproved(f"proposal {proposal_id} is {row['state']}, not approved")
                if row["proposal_version"] != proposal_version or row["action_hash"] != action_hash:
                    raise NotApproved("the stored version or hash differs from the one the run showed")
                check_matches(row["params"], estimates)
                token = repo.token_for(conn, proposal_id)
                if token is None:
                    raise NotApproved(f"proposal {proposal_id} has no execution token")
                try:
                    effect_id = self.approvals.burn(
                        conn,
                        token_id=str(token["token_id"]),
                        proposal_id=proposal_id,
                        proposal_version=proposal_version,
                        action_hash=action_hash,
                        channel=ETR_CHANNEL,
                    )
                except ApprovalError as exc:
                    if getattr(exc, "code", "") == "TOKEN_BURNED":
                        raise AlreadyPublished(str(exc)) from exc
                    raise NotApproved(f"execution token refused: {getattr(exc, 'code', exc)}") from exc
                self.sink.enqueue(conn, envelopes_for(events, at))
                audit.append(
                    conn,
                    kind="etr_published",
                    actor_type="agent",
                    actor_id=f"agent:{published_by}",
                    subject=proposal_id,
                    payload={
                        "estimate_ids": [e.estimate_id for e in events],
                        "estimates_digest": estimates_digest(estimates),
                        "global_p50_utc": events[0].p50_utc.isoformat(),
                        "model_version": events[0].model_version,
                        "effect_id": effect_id,
                    },
                    occurred_at=at,
                    event_key=f"etr_published:{proposal_id}",
                )
                store_revision(conn, estimates)
            self.sink.drain(conn)
        return Publication(events, effect_id)
