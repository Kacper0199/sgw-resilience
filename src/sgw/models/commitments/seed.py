"""The seeded PS-17 commitment (helene_micro story of the contracts' golden material, synthetic).

PS-17's generator and feeder priority (D3, T3 `command` + `water_operations`) is proposed against the
advisory N+1 clock and approved by ic_01 at 15:52Z and wtr_lead_01 at 15:58Z, through the approval service.
The approval's `DecisionApproved` creates the commitment; the helene_micro replay then shows the generator
work order stuck in `draft`, so the commitment drifts and the decision reopens.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from sgw.approval.service import ApprovalService
from sgw.contracts import golden
from sgw.contracts.api_models import ApprovalRequest, ProposalCreate
from sgw.contracts.clocks import propagate
from sgw.contracts.vocab import DecisionStep, Domain

REPO_ROOT = Path(__file__).resolve().parents[4]
MICRO_EVENTS = REPO_ROOT / "data" / "fixtures" / "helene_micro" / "all.jsonl"
PS17_TITLE = "Generator and feeder priority for PS-17 (Tallowbranch hospital zone)"
PROPOSER = "ops_dm_01"
APPROVALS = (
    (golden.t(26, 15, 52), "ic_01"),
    (golden.t(26, 15, 58), "wtr_lead_01"),
)
ASSETS = (
    (golden.PS17, "water", "pump_station", "PS-17 Cedarfall booster (synthetic)", True),
    (golden.FEEDER_PS17, "electric", "feeder", "Feeder FDR-AIK-2207 (synthetic)", False),
)


@dataclass(frozen=True)
class SeededPs17:
    proposal_id: str
    proposal_version: int
    approved_at: datetime


def seed_ps17_case(conn: psycopg.Connection[Any]) -> None:
    adv = golden.ADVISORY_N1
    clock = golden.ps17_clock(adv)
    prop = propagate(golden.clock_nodes(adv))[golden.CASE_PS17]
    for asset_id, domain, kind, name, critical in ASSETS:
        conn.execute(
            "INSERT INTO asset (asset_id, domain, kind, region_id, name, critical_facility, attributes)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (asset_id) DO NOTHING",
            (asset_id, domain, kind, golden.REGION_AIKEN, name, critical, Jsonb({"synthetic": True})),
        )
    conn.execute(
        "INSERT INTO decision_case (decision_case_id, step, title, region_id, domain, clock_kind,"
        " consequence_utc, consequence_p10_utc, consequence_p90_utc, consequence_basis,"
        " action_lead_time_min, lead_time_basis, decide_by_utc, decide_by_p10_utc, decide_by_p90_utc,"
        " effective_decide_by_utc, on_critical_path, next_advisory_utc, if_late)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (decision_case_id) DO NOTHING",
        (
            golden.CASE_PS17,
            DecisionStep.D3.value,
            PS17_TITLE,
            golden.REGION_AIKEN,
            Domain.WATER.value,
            clock.clock_kind.value,
            clock.consequence_utc,
            clock.consequence_p10_utc,
            clock.consequence_p90_utc,
            Jsonb(clock.consequence_basis.model_dump(mode="json")),
            clock.action_lead_time_min,
            Jsonb(clock.lead_time_basis.model_dump(mode="json")),
            clock.decide_by_utc,
            clock.decide_by_p10_utc,
            clock.decide_by_p90_utc,
            prop.effective_decide_by_utc,
            prop.on_critical_path,
            adv.next_advisory,
            clock.if_late,
        ),
    )


def seed_ps17_approved(
    conn: psycopg.Connection[Any], approvals: ApprovalService, set_time: Callable[[datetime], None]
) -> SeededPs17:
    """Case, proposal and both T3 signatures through the approval service (OPA or reference policy, audit,
    outbox). Idempotent on the proposal id."""
    seed_ps17_case(conn)
    existing = conn.execute(
        "SELECT proposal_version, state FROM proposal WHERE proposal_id = %s", (golden.PROPOSAL_PS17,)
    ).fetchone()
    if existing is not None:
        return SeededPs17(golden.PROPOSAL_PS17, int(existing[0]), APPROVALS[-1][0])
    material = golden.ps17_material()
    kw = material.params["portable_generator_kw"]
    if not isinstance(kw, int):
        raise TypeError("golden PS-17 generator size must be an integer kW")
    set_time(golden.ADVISORY_N1.issued)
    card = approvals.create(
        conn,
        proposed_by=PROPOSER,
        request=ProposalCreate(
            decision_case_id=golden.CASE_PS17,
            action_type=material.action_type,
            params={
                "restore_first": golden.FEEDER_PS17,
                "restore_after": golden.FEEDER_LARGER,
                "portable_generator_kw": kw,
                "station_id": golden.PS17,
            },
            target_ids=list(material.target_ids),
            evidence_ids=["EV-ADV-HELENE-NP1"],
        ),
        proposal_id=golden.PROPOSAL_PS17,
        rationale="PS-17 feeds the Tallowbranch hospital zone; the N+1 clock moves its decide-by earlier.",
    ).value
    for at, user in APPROVALS:
        set_time(at)
        approvals.decide(
            conn,
            user_id=user,
            proposal_id=card.proposal_id,
            request=ApprovalRequest(
                decision="approve", proposal_version=card.proposal_version, action_hash=card.action_hash
            ),
        )
    return SeededPs17(card.proposal_id, card.proposal_version, APPROVALS[-1][0])


def micro_events(path: Path = MICRO_EVENTS) -> list[dict[str, Any]]:
    """The helene_micro replay stream (K2 envelopes, header line skipped)."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if "type" in row and "payload" in row:
            out.append(row)
    return out
