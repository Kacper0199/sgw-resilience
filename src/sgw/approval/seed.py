"""`sgw seed`: K18 users, the D4 global-ETR reference rows and the Helene T3 crew pre-positioning
proposal (golden `PRP-CREW-AIK-0926A`, advisory N, 14 crews at Sandhill Yard and 9 at Millpond Yard;
synthetic data). Idempotent."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from argon2 import PasswordHasher
from psycopg.types.json import Jsonb

from sgw.approval import audit
from sgw.approval.ledger import LedgerSink, default_sink, envelope
from sgw.approval.policy import PolicyEngine, ReferencePolicy
from sgw.approval.service import etag
from sgw.contracts import approval as ap
from sgw.contracts import golden
from sgw.contracts.clocks import propagate
from sgw.contracts.events import ProposalCreated
from sgw.contracts.identities import PASSWORD_ENV, SeedUsers, demo_password_for, load_users
from sgw.contracts.vocab import ActionType, DecisionStep, Domain, InitiatorKind
from sgw.reports.seed import seed_etr_reference

log = logging.getLogger("sgw.approval.seed")
REPO_ROOT = Path(__file__).resolve().parents[3]
USERS_PATH = REPO_ROOT / "data" / "seed" / "users.yaml"
INCIDENT_ID = "INC-HELENE-2024"
CREW_SANDHILL = 14
CREW_MILLPOND = 9
CREW_PROPOSER = "ops_dm_01"
CASE_TITLE = "Pre-position crews at Sandhill and Millpond yards before tropical-storm winds"


class SeedError(RuntimeError):
    pass


@dataclass(frozen=True)
class SeedReport:
    users: int
    proposal_id: str
    proposal_created: bool
    etag: str


def seed_users(
    conn: psycopg.Connection[Any],
    users: SeedUsers,
    password: str | None,
    env: Mapping[str, str] | None = None,
) -> int:
    """With `env`, each persona's DEMO_PASSWORD_<USER_ID> wins over the shared `password`."""
    hasher = PasswordHasher()
    for u in users.users:
        chosen = (demo_password_for(u.user_id, env) if env is not None else None) or password
        conn.execute(
            "INSERT INTO app_user (user_id, display_name, persona, function, roles, functions, regions,"
            " domains, can_approve, break_glass_eligible, password_hash) VALUES (%s, %s, %s, %s, %s,"
            " %s::sgw_approval_function[], %s, %s::sgw_domain[], %s, %s, %s)"
            " ON CONFLICT (user_id) DO UPDATE SET display_name = EXCLUDED.display_name,"
            " persona = EXCLUDED.persona, function = EXCLUDED.function, roles = EXCLUDED.roles,"
            " functions = EXCLUDED.functions, regions = EXCLUDED.regions, domains = EXCLUDED.domains,"
            " can_approve = EXCLUDED.can_approve, break_glass_eligible = EXCLUDED.break_glass_eligible,"
            " password_hash = coalesce(EXCLUDED.password_hash, app_user.password_hash)",
            (
                u.user_id,
                u.display_name,
                u.persona,
                u.function.value,
                u.roles,
                [u.function.value],
                u.regions,
                [d.value for d in u.domains],
                u.can_approve,
                u.break_glass_eligible,
                hasher.hash(chosen) if chosen else None,
            ),
        )
    return len(users.users)


def _seed_case(conn: psycopg.Connection[Any]) -> None:
    adv = golden.ADVISORY_N
    clock = golden.crews_clock(adv)
    prop = propagate(golden.clock_nodes(adv))[golden.CASE_CREWS]
    conn.execute(
        "INSERT INTO decision_case (decision_case_id, step, title, region_id, domain, clock_kind,"
        " consequence_utc, consequence_p10_utc, consequence_p90_utc, consequence_basis,"
        " action_lead_time_min, lead_time_basis,"
        " decide_by_utc, decide_by_p10_utc, decide_by_p90_utc, effective_decide_by_utc, on_critical_path,"
        " next_advisory_utc, if_late) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
        " %s, %s, %s) ON CONFLICT (decision_case_id) DO NOTHING",
        (
            golden.CASE_CREWS,
            DecisionStep.D2.value,
            CASE_TITLE,
            golden.REGION_AIKEN,
            Domain.ELECTRIC.value,
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


REGIONS = (
    (golden.REGION_AIKEN, "SC", "45003", "Aiken County"),
    (golden.REGION_RICHMOND, "GA", "13245", "Richmond County"),
)
WATER_ASSETS = (
    (golden.PS17, "water", "pump_station", "PS-17 Cedarfall booster (synthetic)", True),
    (golden.FEEDER_PS17, "electric", "feeder", "Feeder FDR-AIK-2207 (synthetic)", False),
    (golden.ZONE, "water", "pressure_zone", "Cedarfall water zone (synthetic)", False),
    (golden.HOSPITAL, "water", "critical_customer", "Tallowbranch hospital (synthetic)", True),
)
YARDS = (
    (golden.YARD_SANDHILL, golden.REGION_AIKEN, "Sandhill Yard (synthetic)"),
    (golden.YARD_MILLPOND, golden.REGION_RICHMOND, "Millpond Yard (synthetic)"),
)


def seed_reference(conn: psycopg.Connection[Any]) -> None:
    """Regions, the two staging yards the crew proposal targets and the PS-17 cascade assets the water
    rules target (feeder, station, zone, hospital). A yard serves no customers
    (`customers_source` set). No hazard-zone attribute yet, so staging there escalates (fail closed)."""
    for region_id, state, fips, name in REGIONS:
        conn.execute(
            "INSERT INTO region (region_id, state, county_fips, name) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (region_id) DO NOTHING",
            (region_id, state, fips, name),
        )
    for asset_id, region_id, name in YARDS:
        conn.execute(
            "INSERT INTO asset (asset_id, domain, kind, region_id, name, customers_served, attributes)"
            " VALUES (%s, 'electric', 'staging_yard', %s, %s, 0, %s) ON CONFLICT (asset_id) DO NOTHING",
            (asset_id, region_id, name, Jsonb({"customers_source": "synthetic", "synthetic": True})),
        )
    for asset_id, domain, kind, name, critical in WATER_ASSETS:
        conn.execute(
            "INSERT INTO asset (asset_id, domain, kind, region_id, name, critical_facility, attributes)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (asset_id) DO NOTHING",
            (asset_id, domain, kind, golden.REGION_AIKEN, name, critical, Jsonb({"synthetic": True})),
        )


def seed_helene_crew_proposal(
    conn: psycopg.Connection[Any],
    policy: PolicyEngine,
    *,
    proposed_at: datetime | None = None,
    ledger: LedgerSink | None = None,
) -> tuple[bool, str]:
    """Insert the golden crew proposal; tier and approver functions must agree with the policy decision."""
    material = golden.crew_material(CREW_SANDHILL, CREW_MILLPOND)
    decision = policy.propose(
        {
            "action": "propose",
            "subject": {"user_id": CREW_PROPOSER},
            "proposal": {
                "action_type": ActionType.PREPOSITION_CREWS.value,
                "proposed_by": CREW_PROPOSER,
                "requested_by": None,
                "initiator_kind": InitiatorKind.PERSON.value,
                "target_ids": material.target_ids,
            },
            "facts": {"customers_affected": 0},
            "context": {"degraded_mode": "M0", "now_ns": 0},
        }
    )
    c = decision.classification
    if not decision.allow or c.tier != material.tier.value or c.policy_version != golden.POLICY_VERSION:
        raise SeedError(f"policy disagrees with the golden crew proposal: {decision}")
    at = proposed_at or golden.ADVISORY_N.issued
    expires = ap.expires_at(
        now=at,
        tier=material.tier,
        earliest_evidence_expiry=None,
        next_forecast_issue=golden.ADVISORY_N.next_advisory,
        approver_shift_end=None,
    )
    hash_ = ap.action_hash(material, golden.POLICY_VERSION)
    with conn.transaction():
        seed_reference(conn)
        _seed_case(conn)
        cur = conn.execute(
            "INSERT INTO proposal (proposal_id, decision_case_id, incident_id, action_type, params, targets,"
            " risk_band, preconditions, tier, required_functions, escalators, state, proposal_version,"
            " action_hash, policy_version, evidence_ids, initiator_kind, proposed_by, region_id, domain,"
            " rationale, expires_at, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,"
            " %s::sgw_approval_function[], %s, 'proposed', 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (proposal_id) DO NOTHING",
            (
                golden.PROPOSAL_CREWS,
                golden.CASE_CREWS,
                INCIDENT_ID,
                material.action_type.value,
                Jsonb(material.params),
                material.target_ids,
                material.risk_band.value,
                Jsonb(material.preconditions),
                material.tier.value,
                list(c.required_functions),
                material.escalators,
                hash_,
                golden.POLICY_VERSION,
                [],
                InitiatorKind.PERSON.value,
                CREW_PROPOSER,
                golden.REGION_AIKEN,
                Domain.ELECTRIC.value,
                "Synthetic data. Advisory N puts tropical-storm wind onset at the Millpond yard at "
                "27 Sep 06:10 UTC; crews need five hours to mobilise and stage.",
                expires,
                at,
                at,
            ),
        )
        created = cur.rowcount == 1
        if created:
            conn.execute(
                "INSERT INTO proposal_delta (proposal_id, version, seq, material, change)"
                " VALUES (%s, 1, 1, true, %s)",
                (golden.PROPOSAL_CREWS, Jsonb({"created": True, "fields": [], "by": "sgw seed"})),
            )
            audit.append(
                conn,
                kind="proposal_created",
                actor_type="user",
                actor_id=CREW_PROPOSER,
                subject=golden.PROPOSAL_CREWS,
                payload={
                    "proposal_version": 1,
                    "action_hash": hash_,
                    "action_type": material.action_type.value,
                    "tier": material.tier.value,
                    "required_functions": [str(getattr(f, "value", f)) for f in c.required_functions],
                    "escalators": list(material.escalators),
                    "policy_version": golden.POLICY_VERSION,
                    "initiator_kind": InitiatorKind.PERSON.value,
                    "seeded_by": "sgw seed",
                },
                occurred_at=at,
                event_key=f"proposal_created:{golden.PROPOSAL_CREWS}",
            )
            if ledger is not None:
                event = ProposalCreated(
                    proposal_id=golden.PROPOSAL_CREWS,
                    decision_case_id=golden.CASE_CREWS,
                    action_type=material.action_type,
                    tier=material.tier,
                    proposal_version=1,
                    action_hash=hash_,
                    proposed_by=CREW_PROPOSER,
                    decide_by_utc=golden.crews_clock(golden.ADVISORY_N).decide_by_utc,
                    clock_kind=golden.crews_clock(golden.ADVISORY_N).clock_kind,
                )
                ledger.enqueue(
                    conn,
                    [
                        envelope(
                            event,
                            at=at,
                            key=f"{golden.PROPOSAL_CREWS}:v1:created",
                            region_id=golden.REGION_AIKEN,
                            domain=Domain.ELECTRIC.value,
                        )
                    ],
                )
    if created and ledger is not None:
        try:
            ledger.drain(conn)
        except Exception:
            log.warning("ledger drain after seed failed; the relay will pick the event up", exc_info=True)
    return created, hash_


def run_seed(
    dsn: str,
    *,
    users_path: Path = USERS_PATH,
    policy: PolicyEngine | None = None,
    ledger: LedgerSink | None = None,
    use_default_ledger: bool = True,
) -> SeedReport:
    users = load_users(users_path)
    password = os.environ.get(PASSWORD_ENV) or None
    sink = ledger if ledger is not None else (default_sink() if use_default_ledger else None)
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.transaction():
            count = seed_users(conn, users, password, env=os.environ)
        created, hash_ = seed_helene_crew_proposal(conn, policy or ReferencePolicy(), ledger=sink)
        with conn.transaction():
            seed_etr_reference(conn)
    return SeedReport(
        users=count, proposal_id=golden.PROPOSAL_CREWS, proposal_created=created, etag=etag(1, hash_)
    )
