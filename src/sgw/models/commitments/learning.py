"""Learning loop: after the event, compare actual with assumed lead times and propose new values (T2).

Observed lead time per work order: the first `start` status to the first `end` status after it (the K16
definition of the lead time, e.g. generator crew dispatched to generator running). Per lead-time key the
evidence row carries n, median, min and max, every observation with its work order and ledger event ids, and
the source. The proposed value is a credibility-weighted mean, `z * median + (1 - z) * assumed` with
`z = n / (n + k)` (k = `credibility_prior_n`, the assumed value's weight in observations), rounded up to the
policy step: one storm moves a lead time part of the way, and repeated evidence moves it the rest. A change
smaller than `min_change_min` is not proposed.

The loop only proposes: it writes a `policy_change_proposal` row (tier T2, state `proposed`) and an audit
record. It never writes `lead_times.yaml` or any registry value; a person approves, and the change lands by a
commit to the policy file.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg.types.json import Jsonb

from sgw.approval import audit
from sgw.contracts.api_models import ProposalCreate
from sgw.contracts.approval import tier_rule
from sgw.contracts.base import utc_iso
from sgw.contracts.vocab import ActionType, ApprovalFunction, InitiatorKind
from sgw.models.clocks import lead_times
from sgw.models.commitments import plan as plans
from sgw.models.commitments.watch import event_time

if TYPE_CHECKING:
    from sgw.approval.service import ApprovalService

ACTOR = "system:learning-loop"
POLICY_KEY = "lead_times"
LEAD_PARAM_PREFIX = "proposed_min."


@dataclass(frozen=True)
class Definition:
    key: str
    work_type: str
    start: tuple[str, ...]
    end: tuple[str, ...]
    text: str


DEFINITIONS: tuple[Definition, ...] = (
    Definition(
        "portable_generator_hookup",
        "portable_generator_hookup",
        ("open",),
        ("in_progress", "closed"),
        "work order open (generator crew dispatched) to in_progress (generator running)",
    ),
    Definition(
        "fuel_truck_dispatch",
        "fuel_delivery",
        ("open",),
        ("closed",),
        "work order open (fuel truck called) to closed (fuel delivered at the generator)",
    ),
)


@dataclass(frozen=True)
class Observation:
    key: str
    work_order_id: str
    asset_id: str
    start_utc: str
    end_utc: str
    minutes: int
    event_ids: tuple[str, str]


@dataclass
class EvidenceRow:
    key: str
    definition: str
    assumed_min: int
    sop: str
    n: int
    median_min: float | None
    min_min: int | None
    max_min: int | None
    credibility_z: float
    proposed_min: int | None
    change_min: int
    verdict: str
    source: str
    observations: list[dict[str, Any]] = field(default_factory=list)


def observe(events: Iterable[Mapping[str, Any]]) -> list[Observation]:
    by_type = {d.work_type: d for d in DEFINITIONS}
    starts: dict[str, tuple[datetime, str, str]] = {}
    done: dict[str, Observation] = {}
    for e in sorted(events, key=event_time):
        if e.get("type") != "WorkOrder":
            continue
        p = e["payload"]
        d = by_type.get(str(p.get("work_type")))
        wo = str(p.get("work_order_id"))
        if d is None or wo in done:
            continue
        at = event_time(e)
        if p.get("status") in d.start and wo not in starts:
            starts[wo] = (at, str(e.get("event_id")), str(p.get("asset_id")))
        elif p.get("status") in d.end and wo in starts:
            t0, eid0, asset = starts[wo]
            done[wo] = Observation(
                key=d.key,
                work_order_id=wo,
                asset_id=asset,
                start_utc=utc_iso(t0),
                end_utc=utc_iso(at),
                minutes=round((at - t0).total_seconds() / 60.0),
                event_ids=(eid0, str(e.get("event_id"))),
            )
    return sorted(done.values(), key=lambda o: (o.key, o.start_utc))


def _round_up(value: float, step: int) -> int:
    return int(math.ceil(value / step) * step)


def evidence(observations: Sequence[Observation], source: str) -> list[EvidenceRow]:
    k = float(plans.policy_value("credibility_prior_n"))
    step = int(plans.policy_value("rounding_min"))
    threshold = int(plans.policy_value("min_change_min"))
    rows = []
    for d in DEFINITIONS:
        assumed = lead_times.lead_time(d.key)
        obs = [o for o in observations if o.key == d.key]
        n = len(obs)
        z = n / (n + k) if n else 0.0
        median = statistics.median(o.minutes for o in obs) if obs else None
        proposed: int | None = None
        change = 0
        if median is None:
            verdict = "keep: no observations"
        else:
            candidate = _round_up(z * median + (1.0 - z) * assumed.minutes, step)
            change = candidate - assumed.minutes
            if abs(change) < threshold:
                verdict = f"keep: change {change} min is below the {threshold} min threshold"
                change = 0
            else:
                proposed = candidate
                verdict = "propose"
        rows.append(
            EvidenceRow(
                key=d.key,
                definition=d.text,
                assumed_min=assumed.minutes,
                sop=assumed.sop,
                n=n,
                median_min=median,
                min_min=min((o.minutes for o in obs), default=None),
                max_min=max((o.minutes for o in obs), default=None),
                credibility_z=round(z, 4),
                proposed_min=proposed,
                change_min=change,
                verdict=verdict,
                source=source,
                observations=[asdict(o) for o in obs],
            )
        )
    return rows


def method() -> dict[str, Any]:
    return {
        "estimator": "credibility-weighted mean: z * median(actual) + (1 - z) * assumed, z = n / (n + k)",
        "credibility_prior_n": plans.policy_value("credibility_prior_n"),
        "rounding_min": plans.policy_value("rounding_min"),
        "min_change_min": plans.policy_value("min_change_min"),
        "policy_version": plans.policy_version(),
        "label": "synthetic data; SGW policy, assumed",
    }


def _hash(rows: Sequence[EvidenceRow]) -> str:
    body = json.dumps([asdict(r) for r in rows], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def write_proposal(
    conn: psycopg.Connection[Any], rows: Sequence[EvidenceRow], *, incident_id: str, at: datetime
) -> str | None:
    """Insert the T2 policy-change proposal when at least one key changes; idempotent per evidence."""
    changes = [r for r in rows if r.proposed_min is not None]
    if not changes:
        return None
    digest = _hash(rows)
    change_id = f"PCH-LEADTIME-{incident_id}-{digest[:10]}"
    functions = [f.value for f in approver_functions()]
    with conn.transaction():
        found = conn.execute(
            "SELECT change_id FROM policy_change_proposal WHERE policy_key = %s AND incident_id = %s"
            " AND evidence_hash = %s",
            (POLICY_KEY, incident_id, digest),
        ).fetchone()
        if found:
            return str(found[0])
        current = {r.key: r.assumed_min for r in rows}
        proposed = {r.key: r.proposed_min for r in changes}
        conn.execute(
            "INSERT INTO policy_change_proposal (change_id, policy_key, tier, required_functions, state,"
            " proposed_by, incident_id, policy_version, method, evidence, current_values, proposed_values,"
            " evidence_hash, created_at)"
            " VALUES (%s, %s, 'T2', %s::sgw_approval_function[], 'proposed',"
            " %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                change_id,
                POLICY_KEY,
                functions,
                ACTOR,
                incident_id,
                lead_times.load()[changes[0].key].version,
                Jsonb(method()),
                Jsonb([asdict(r) for r in rows]),
                Jsonb(current),
                Jsonb(proposed),
                digest,
                at,
            ),
        )
        audit.append(
            conn,
            kind="policy_change_proposed",
            actor_type="system",
            actor_id=ACTOR,
            subject=change_id,
            payload={
                "policy_key": POLICY_KEY,
                "tier": "T2",
                "required_functions": functions,
                "current_values": current,
                "proposed_values": proposed,
                "evidence_hash": digest,
                "n_by_key": {r.key: r.n for r in rows},
                "applied": False,
            },
            occurred_at=at,
            event_key=f"policy_change_proposed:{change_id}",
        )
    return change_id


def approver_functions() -> tuple[ApprovalFunction, ...]:
    """The K8 tier-table functions that sign a policy change (`policy_change`, T2)."""
    return tier_rule(ActionType.POLICY_CHANGE).approver_functions


def route_for_approval(
    conn: psycopg.Connection[Any], approvals: ApprovalService, change_id: str, *, decision_case_id: str
) -> str:
    """Route a policy-change row through the approval service as a K1 `policy_change` proposal (T2, signed by
    the tier-table functions) and link it via `approval_proposal_id`; idempotent. Approval never applies the
    values: lead_times.yaml changes only by a reviewed commit."""
    row = conn.execute(
        "SELECT approval_proposal_id, proposed_values, evidence_hash, incident_id FROM policy_change_proposal"
        " WHERE change_id = %s",
        (change_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"no policy change {change_id}")
    linked, proposed, digest, incident_id = row
    if linked:
        return str(linked)
    params: dict[str, int | str | bool | list[str]] = {
        "policy_key": POLICY_KEY,
        "change_id": change_id,
        "evidence_hash": digest,
        **{f"{LEAD_PARAM_PREFIX}{k}": int(v) for k, v in sorted(proposed.items())},
    }
    outcome = approvals.create(
        conn,
        proposed_by=ACTOR,
        initiator_kind=InitiatorKind.SYSTEM_RULE,
        incident_id=incident_id,
        request=ProposalCreate(
            decision_case_id=decision_case_id,
            action_type=ActionType.POLICY_CHANGE,
            params=params,
            target_ids=[],
            evidence_ids=[],
        ),
        rationale=f"after-action lead-time change {change_id}; approval records consent, never applies",
    )
    proposal_id = str(outcome.value.proposal_id)
    conn.execute(
        "UPDATE policy_change_proposal SET approval_proposal_id = %s WHERE change_id = %s"
        " AND approval_proposal_id IS NULL",
        (proposal_id, change_id),
    )
    return proposal_id
