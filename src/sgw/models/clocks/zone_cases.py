"""Zone rule cases on the scenario clock: every zone rule hit active at the scenario time
(`sgw.rules.zones`) gets its decision case (K16 clock from the hit's anchor, terms and lead time, stored like
the advisory queue) and one proposal drafted through the approval service by the rule's principal
(`system:rule:<id>`, initiator kind `system_rule`), so OPA decides tier and signers and the database
re-derives them. Idempotent and forward-only: a rule key has at most one undecided proposal; it is raised
again (`-2`, `-3`, ...) only after the earlier one expired, while the hit is still active; nothing is
removed on a jump back (proposals carry `known_at_utc` and the queue hides those not yet known).

Off unless `SGW_ZONE_RULES` is truthy, so the golden path and the demo bookmarks are unchanged by default.

The exercise injects (`sgw.rules.injects`) are raised the same way under their own flag
`SGW_SCENARIO_INJECTS`, with their own proposal prefix `PRP-EX-` and their own map assets."""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from sgw.approval import repository as repo
from sgw.approval.errors import ApprovalError
from sgw.approval.service import ApprovalService
from sgw.contracts.api_models import ApprovalRequest, ProposalCreate
from sgw.contracts.vocab import InitiatorKind
from sgw.models.clocks.service import CaseSpec, compute_queue
from sgw.models.clocks.store import save_queue
from sgw.models.clocks.waterfall import ConsequenceSpec
from sgw.rules import injects, zones

log = logging.getLogger(__name__)
FLAG_ENV = "SGW_ZONE_RULES"
INJECTS_FLAG_ENV = "SGW_SCENARIO_INJECTS"
LOCK_KEY = 2300_0002
PROPOSAL_PREFIX = "PRP-ZR-"
INJECT_PREFIX = "PRP-EX-"
RERAISE_STATES = frozenset({"expired"})
HOSPITAL_NAME = "Tallowbranch hospital (synthetic)"
TRUTHY = frozenset({"1", "true", "yes", "on"})
USERS_PATH = Path(__file__).resolve().parents[4] / "data" / "seed" / "users.yaml"
SCRIPTED_AFTER_KNOWN = timedelta(minutes=5)
SCRIPTED_BEFORE_DUE = timedelta(minutes=30)
SCRIPTED_NOTE = "Signed in the exercise script (synthetic)"


def enabled() -> bool:
    return os.environ.get(FLAG_ENV, "").strip().lower() in TRUTHY


def injects_enabled() -> bool:
    return os.environ.get(INJECTS_FLAG_ENV, "").strip().lower() in TRUTHY


@dataclass
class ZoneSync:
    active: list[str] = field(default_factory=list)
    cases_saved: list[str] = field(default_factory=list)
    raised: dict[str, str] = field(default_factory=dict)
    refused: dict[str, str] = field(default_factory=dict)


def proposal_base(key: str, prefix: str = PROPOSAL_PREFIX) -> str:
    return prefix + hashlib.sha256(key.encode()).hexdigest()[:12].upper()


def case_spec(hit: zones.ZoneHit, region_id: str) -> CaseSpec:
    clock = hit.clock
    if clock is None:
        raise ValueError(f"{hit.key} joins a stored case and has no clock of its own")
    return CaseSpec(
        case_id=hit.case_id,
        step=clock.step,
        title=clock.title,
        domain=clock.domain,
        region_id=region_id,
        consequence=ConsequenceSpec(
            consequence_basis=clock.consequence_basis,
            anchor_label=clock.anchor_label,
            anchor_basis=clock.anchor_basis,
            anchor_utc=[clock.anchor_utc],
            terms=clock.terms,
        ),
        lead_key=clock.lead_key,
        if_late=clock.if_late,
    )


def ensure_assets(conn: psycopg.Connection[Any], w: zones.World) -> None:
    """The named Helene assets the rules target, when reference data has not loaded them, and the mobile
    resources with their no-customer, outside-the-hazard-zone facts (existing attribute keys win)."""
    named = w.network["named"]
    region = str(w.rules["region_id"])
    rows: list[tuple[str, str, str, str, bool]] = []
    for sid, st in named["pump_stations"].items():
        zone_name = w.rules["zones"].get(st["zone"], {}).get("name", st["zone"])
        rows.append((sid, "water", "pump_station", f"{sid} booster (synthetic)", sid == "PS-17"))
        rows.append((str(st["zone"]), "water", "pressure_zone", f"{zone_name} water zone (synthetic)", False))
    for fid in named["feeders"]:
        rows.append((fid, "electric", "feeder", f"Feeder {fid} (synthetic)", False))
    hospital = named["hospital"]
    rows.append((str(hospital["id"]), "water", "critical_customer", HOSPITAL_NAME, True))
    with conn.transaction():
        for asset_id, domain, kind, name, critical in rows:
            conn.execute(
                "INSERT INTO asset (asset_id, domain, kind, region_id, name, critical_facility, attributes)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (asset_id) DO NOTHING",
                (asset_id, domain, kind, region, name, critical, Jsonb({"synthetic": True})),
            )
        facts = {
            "synthetic": True,
            "customers_source": "none",
            "in_hazard_zone": False,
            "zone_basis": str(w.rules["resource_basis"]),
        }
        for asset_id, r in w.rules["resources"].items():
            conn.execute(
                "INSERT INTO asset (asset_id, domain, kind, region_id, name, customers_served, attributes)"
                " VALUES (%s, %s, %s, %s, %s, 0, %s) ON CONFLICT (asset_id) DO UPDATE"
                " SET attributes = EXCLUDED.attributes || asset.attributes"
                " WHERE NOT (asset.attributes ?& ARRAY['customers_source', 'in_hazard_zone'])",
                (asset_id, r["domain"], r["kind"], region, r["name"], Jsonb(facts)),
            )


def _existing_cases(conn: psycopg.Connection[Any], ids: Sequence[str]) -> set[str]:
    rows = conn.execute(
        "SELECT decision_case_id FROM decision_case WHERE decision_case_id = ANY(%s)", (list(ids),)
    ).fetchall()
    return {str(r[0]) for r in rows}


def next_proposal_id(conn: psycopg.Connection[Any], key: str, prefix: str = PROPOSAL_PREFIX) -> str | None:
    """The id of the next proposal for a rule key, or None while an earlier one is undecided, decided or
    withdrawn (only an expired proposal is raised again)."""
    base = proposal_base(key, prefix)
    rows = conn.execute(
        "SELECT state::text FROM proposal WHERE proposal_id = %s OR proposal_id LIKE %s",
        (base, base + "-%"),
    ).fetchall()
    states = [str(r[0]) for r in rows]
    if not states:
        return base
    if all(s in RERAISE_STATES for s in states):
        return f"{base}-{len(states) + 1}"
    return None


def _raise(
    conn: psycopg.Connection[Any],
    now: datetime,
    service: ApprovalService,
    found: Sequence[zones.ZoneHit],
    *,
    region: str,
    incident_id: str,
    prefix: str,
    out: ZoneSync,
    regions: Mapping[str, str] | None = None,
) -> ZoneSync:
    stored = _existing_cases(conn, [h.case_id for h in found])
    fresh = [h for h in found if h.clock is not None and h.case_id not in stored]
    if fresh:
        result = compute_queue([case_spec(h, (regions or {}).get(h.case_id, region)) for h in fresh], now=now)
        save_queue(conn, result)
        out.cases_saved = sorted(result.cases)
        stored |= set(result.cases)
    for hit in found:
        if hit.case_id not in stored:
            out.refused[hit.key] = f"decision case {hit.case_id} is not stored"
            continue
        pid = next_proposal_id(conn, hit.key, prefix)
        if pid is None:
            continue
        try:
            card = service.create(
                conn,
                proposed_by=hit.proposer,
                request=ProposalCreate(
                    decision_case_id=hit.case_id,
                    action_type=hit.action_type,
                    params={**hit.params, "rule_key": hit.key, "evidence_refs": list(hit.evidence)},
                    target_ids=list(hit.target_ids),
                    evidence_ids=[],
                ),
                initiator_kind=InitiatorKind.SYSTEM_RULE,
                incident_id=incident_id,
                rationale=hit.rationale,
                proposal_id=pid,
            ).value
            out.raised[hit.key] = card.proposal_id
        except (ApprovalError, psycopg.Error) as error:
            out.refused[hit.key] = f"{type(error).__name__}: {error}"
    return out


def sync(
    conn: psycopg.Connection[Any],
    now: datetime,
    service: ApprovalService,
    hits: Sequence[zones.ZoneHit] | None = None,
) -> ZoneSync:
    """Store the cases and draft the proposals of the zone rule hits active at `now`. `conn` is autocommit;
    serialised by an advisory lock."""
    w = zones.world()
    found = zones.active(now, hits)
    out = ZoneSync(active=[h.key for h in found])
    if not found:
        return out
    region = str(w.rules["region_id"])
    conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
    try:
        ensure_assets(conn, w)
        return _raise(
            conn,
            now,
            service,
            found,
            region=region,
            incident_id=str(w.rules["incident_id"]),
            prefix=PROPOSAL_PREFIX,
            out=out,
        )
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))


def ensure_inject_assets(
    conn: psycopg.Connection[Any],
    found: injects.Injects,
    source: str = "data/synthetic/helene_injects.yaml",
) -> None:
    """The invented facilities and resources the injects target, with a map position and the escalation facts
    the approval policy reads (customers, critical facility, hazard zone); existing attribute keys win. An
    asset in a county the reference data has not loaded is left out (its injects are refused as unknown
    targets)."""
    rows = conn.execute(
        "SELECT region_id FROM region WHERE region_id = ANY(%s)", (list({a.region_id for a in found.assets}),)
    ).fetchall()
    regions = {str(r[0]) for r in rows}
    with conn.transaction():
        for a in found.assets:
            if a.region_id not in regions:
                continue
            facts = {
                "synthetic": True,
                "customers_source": "none" if a.mobile else "exercise_inject",
                "in_hazard_zone": a.in_hazard_zone,
                "location_source": f"{source} (synthetic exercise inject)",
            }
            conn.execute(
                "INSERT INTO asset (asset_id, domain, kind, region_id, name, geom, critical_facility,"
                " customers_served, attributes)"
                " VALUES (%s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s)"
                " ON CONFLICT (asset_id) DO UPDATE SET attributes = EXCLUDED.attributes || asset.attributes"
                " WHERE NOT (asset.attributes ?& ARRAY['customers_source', 'in_hazard_zone'])",
                (
                    a.asset_id,
                    a.domain.value,
                    a.kind,
                    a.region_id,
                    a.name,
                    a.lon,
                    a.lat,
                    a.critical,
                    a.customers,
                    Jsonb(facts),
                ),
            )


def _passed(
    conn: psycopg.Connection[Any], now: datetime, pool: Sequence[zones.ZoneHit], prefix: str
) -> list[zones.ZoneHit]:
    """Injects whose whole window lies before `now` and that this database never raised: a demo moment loaded
    past them (the templates are built without injects)."""
    return [
        h
        for h in pool
        if h.resolved_at is not None
        and h.resolved_at <= now
        and next_proposal_id(conn, h.key, prefix) == proposal_base(h.key, prefix)
    ]


@cache
def _signer_of() -> dict[str, str]:
    """The first seeded person of each approval function (`data/seed/users.yaml`)."""
    from sgw.contracts.identities import load_users

    out: dict[str, str] = {}
    for user in load_users(USERS_PATH).users:
        out.setdefault(user.function.value, user.user_id)
    return out


def _sign_on_time(
    conn: psycopg.Connection[Any], service: ApprovalService, proposal_id: str, raised: datetime
) -> bool:
    """Sign one passed inject the way the exercise script assumes its teams did: every required function signs
    30 minutes before the decide-by, inside the approval window and never before the decision was raised, then
    the go-ahead is used. False when a signature is refused; the caller then lets it expire."""
    card = service.card(conn, proposal_id)
    latest = card.effective_decide_by_utc - SCRIPTED_BEFORE_DUE
    row = conn.execute("SELECT expires_at FROM proposal WHERE proposal_id = %s", (proposal_id,)).fetchone()
    if row is not None and row[0] is not None:
        latest = min(latest, row[0] - SCRIPTED_AFTER_KNOWN)
    when = max(raised + SCRIPTED_AFTER_KNOWN, latest)
    clocked = _at(service, when)
    signers = _signer_of()
    remaining = [f.value for f in card.functions_required]
    while remaining:
        user_id = signers.get(remaining[0])
        if user_id is None:
            return False
        current = service.card(conn, proposal_id)
        try:
            response = clocked.decide(
                conn,
                user_id=user_id,
                proposal_id=proposal_id,
                request=ApprovalRequest(
                    decision="approve",
                    proposal_version=current.proposal_version,
                    action_hash=current.action_hash,
                    note=SCRIPTED_NOTE,
                ),
            ).value
        except (ApprovalError, psycopg.Error) as error:
            log.warning("scripted signature of %s by %s at %s refused: %s", proposal_id, user_id, when, error)
            return False
        remaining = [f.value for f in response.remaining_functions]
    token = repo.token_for(conn, proposal_id)
    done = service.card(conn, proposal_id)
    if token is None or done.state.value != "approved":
        return done.state.value in {"approved", "executed"}
    try:
        clocked.burn(
            conn,
            token_id=str(token["token_id"]),
            proposal_id=proposal_id,
            proposal_version=done.proposal_version,
            action_hash=done.action_hash,
        )
    except (ApprovalError, psycopg.Error):
        return True
    return True


def _helene_moments() -> list[datetime]:
    from sgw.demo.bookmarks import BOOKMARKS

    return [zones.utc(b.scenario_time) for b in BOOKMARKS]


def _at(service: ApprovalService, moment: datetime) -> ApprovalService:
    return ApprovalService(
        service.policy, scenario_clock=lambda: moment, token_clock=service.token_clock, ledger=service.ledger
    )


def _settle_passed(
    conn: psycopg.Connection[Any],
    service: ApprovalService,
    passed: Sequence[zones.ZoneHit],
    *,
    region: str,
    incident_id: str,
    prefix: str,
    out: ZoneSync,
    regions: Mapping[str, str] | None,
    moments: Sequence[datetime] = (),
) -> None:
    """Each inject a loaded moment skipped is raised at its own `known_at` and signed on time by the seeded
    team members, as the exercise script assumes (the later injects build on it: a second mutual-aid wave,
    a refuel of the staged generator). It is closed with the times of the script instead of vanishing
    between moments; if a signature is refused it expires at `resolved_at`. It is raised at the
    last demo moment inside its window, where a presenter loading that moment saw it raised, else at
    `known_at`."""
    for hit in passed:
        inside = [
            m for m in moments if hit.known_at <= m and (hit.resolved_at is None or m < hit.resolved_at)
        ]
        raised = max(inside, default=hit.known_at)
        _raise(
            conn,
            raised,
            _at(service, raised),
            [hit],
            region=region,
            incident_id=incident_id,
            prefix=prefix,
            out=out,
            regions=regions,
        )
        pid = out.raised.get(hit.key)
        if pid is not None and _sign_on_time(conn, service, pid, raised):
            continue
        if hit.resolved_at is not None:
            _at(service, hit.resolved_at).expire_due(conn)


def sync_injects(
    conn: psycopg.Connection[Any],
    now: datetime,
    service: ApprovalService,
    hits: Sequence[zones.ZoneHit] | None = None,
) -> ZoneSync:
    """Store the cases and draft the proposals of the exercise injects active at `now`, and close the ones a
    loaded moment skipped (same lock and rules as `sync`)."""
    found_injects = injects.load()
    pool = found_injects.hits if hits is None else tuple(hits)
    found = injects.active(now, pool)
    out = ZoneSync(active=[h.key for h in found])
    passed = _passed(conn, now, pool, INJECT_PREFIX)
    if not found and not passed:
        return out
    region = str(zones.world().rules["region_id"])
    conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
    try:
        ensure_inject_assets(conn, found_injects)
        common: dict[str, Any] = {
            "region": region,
            "incident_id": found_injects.incident_id,
            "prefix": INJECT_PREFIX,
            "out": out,
            "regions": found_injects.regions,
        }
        _settle_passed(
            conn, service, _passed(conn, now, pool, INJECT_PREFIX), **common, moments=_helene_moments()
        )
        return _raise(conn, now, service, found, **common)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))


def sync_pack(
    conn: psycopg.Connection[Any], now: datetime, service: ApprovalService, scenario: str
) -> ZoneSync:
    """The exercise injects of a scenario pack (`sgw.scenarios.packs`) active at `now`, under the pack's own
    proposal prefix, incident and regions, and the ones a loaded moment skipped (same lock and rules as
    `sync_injects`)."""
    from sgw.scenarios import packs

    pack = packs.load(scenario)
    found = injects.active(now, pack.msel.hits)
    out = ZoneSync(active=[h.key for h in found])
    passed = _passed(conn, now, pack.msel.hits, pack.proposal_prefix)
    if not found and not passed:
        return out
    conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
    try:
        ensure_inject_assets(conn, pack.msel, f"{pack.source_dir}/msel.yaml")
        common: dict[str, Any] = {
            "region": next(iter(pack.msel.regions.values())),
            "incident_id": pack.incident_id,
            "prefix": pack.proposal_prefix,
            "out": out,
            "regions": pack.msel.regions,
        }
        _settle_passed(
            conn,
            service,
            _passed(conn, now, pack.msel.hits, pack.proposal_prefix),
            **common,
            moments=[m.at for m in pack.moments],
        )
        return _raise(conn, now, service, found, **common)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
