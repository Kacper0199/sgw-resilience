"""Zone rules: the decisions the Helene world raises after the PS-17 hinge, by code rules on
the scenario clock, never by a model. Each rule turns facts of the world (water twin member table, WP-06 truth
water events and seeded cases, LIMS samples, named assets) into one `ZoneHit`: a proposal request, the clock
spec of its decision case (or the stored advisory case it joins) and a template rationale whose numbers come
from the same facts. A hit is active from the moment its facts are known (`known_at`) until the world settles
it (`resolved_at`); the timeline is static, so a scenario time selects the active hits and a jump back hides
what is not yet known.

Rules: the PS-17 act-now orders (fuel truck, hospital tanker) once an advisory puts the PS-17 power-loss share
past the act-now level; boil-water advisories for zones whose pressure falls below the state floor (WP-24
`pressure_hits`); the D7 restoration order by CE expected impact once Cedarfall is below the floor; a patrol
work order for an AMI section dark without last gasps (W9); the PS-38 fuel reroute when the fuel truck is
requested on a flooded route; the PS-52 mobile generator after its onsite generator fails; and the lift of a
notice once the required clean total coliform sets are reported (WP-24 `lift_check`, all clauses met but the
SCDES concurrence the compliance signature attests)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from sgw.common import numbers
from sgw.contracts.clocks import ClockBasis
from sgw.contracts.vocab import ActionType, ClockKind, DecisionStep, Domain
from sgw.models.clocks import advisory
from sgw.models.clocks.ps17 import CASE_POWER, ps17_specs
from sgw.models.clocks.service import share_ppm
from sgw.models.clocks.waterfall import AddOnTerm
from sgw.models.ranking.ce import ImpactInput, RankPolicy, expected_impact
from sgw.models.water.floors import State
from sgw.rules import bwa

RULES_PATH = Path(__file__).with_name("zones.yaml")
REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "data" / "fixtures" / "helene"
TRUTH_FILE = FIXTURE / "truth_table.json"
NETWORK_FILE = FIXTURE / "network.json"
LIMS_FILE = FIXTURE / "lims.jsonl"
BASIS_VERSION = "1.0-synthetic"
EASTERN = ZoneInfo("America/New_York")
COLIFORM = "total_coliform"


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def iso(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def reader(at: datetime) -> str:
    local = at.astimezone(EASTERN)
    return f"{local:%b} {local.day}, {local:%H:%M} ET"


def basis(
    basis_id: str, citation: str | None = None, kind: ClockKind = ClockKind.MODEL_ESTIMATE
) -> ClockBasis:
    return ClockBasis(kind=kind, basis_id=basis_id, basis_version=BASIS_VERSION, citation=citation)


@dataclass(frozen=True)
class Sample:
    sample_id: str
    zone_id: str
    taken_utc: datetime
    known_utc: datetime
    absent: bool


@dataclass(frozen=True)
class World:
    rules: Mapping[str, Any]
    truth: Mapping[str, Any]
    network: Mapping[str, Any]
    members: Mapping[str, Any]
    samples: tuple[Sample, ...]

    def water(self, station: str) -> Mapping[str, Any]:
        found: Mapping[str, Any] = self.truth["water"][station]
        return found

    def seeded(self, case_id: str) -> Mapping[str, Any]:
        for case in self.truth["seeded_cases"]:
            if case["id"] == case_id:
                found: Mapping[str, Any] = case
                return found
        raise KeyError(f"no seeded case {case_id}")

    def event(self, station: str, device: str, status: str) -> datetime | None:
        times = [
            utc(t)
            for t, dev, what in self.water(station)["generator_events"]
            if dev == device and what == status
        ]
        return min(times) if times else None

    def policy(self, key: str) -> float:
        return float(self.rules["policy"][key]["value"])


def _samples(path: Path) -> tuple[Sample, ...]:
    out: list[Sample] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        payload = row.get("payload") or {}
        if payload.get("analyte") != COLIFORM:
            continue
        out.append(
            Sample(
                sample_id=str(payload["sample_id"]),
                zone_id=str(payload["zone_id"]),
                taken_utc=utc(row["event_time"]),
                known_utc=utc(row["known_at"]),
                absent=payload.get("result") == "absent",
            )
        )
    return tuple(sorted(out, key=lambda s: (s.known_utc, s.sample_id)))


@cache
def world() -> World:
    return World(
        rules=yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")),
        truth=json.loads(TRUTH_FILE.read_text(encoding="utf-8")),
        network=json.loads(NETWORK_FILE.read_text(encoding="utf-8")),
        members=advisory.member_table(),
        samples=_samples(LIMS_FILE),
    )


@dataclass(frozen=True)
class CaseClock:
    """The clock of a new decision case: anchor event plus add-on terms, then the action lead time."""

    step: DecisionStep
    title: str
    domain: Domain
    consequence_basis: ClockBasis
    anchor_label: str
    anchor_basis: ClockBasis
    anchor_utc: datetime
    lead_key: str
    if_late: str
    terms: tuple[AddOnTerm, ...] = ()


@dataclass(frozen=True)
class ZoneHit:
    key: str
    rule: str
    proposer: str
    case_id: str
    action_type: ActionType
    known_at: datetime
    resolved_at: datetime | None
    target_ids: tuple[str, ...]
    params: dict[str, int | str | bool | list[str]]
    rationale: str
    clock: CaseClock | None = None
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def active(self, now: datetime) -> bool:
        return self.known_at <= now and (self.resolved_at is None or now < self.resolved_at)


def _rule(w: World, name: str) -> Mapping[str, Any]:
    found: Mapping[str, Any] = w.rules["rules"][name]
    return found


def _params(w: World, name: str, known_at: datetime, **extra: int | str | bool | list[str]) -> dict[str, Any]:
    rule_id = "rule." + str(_rule(w, name)["proposer"]).removeprefix("system:rule:")
    return {"rule_id": rule_id, "known_at_utc": iso(known_at), **extra}


# ---- PS-17 act-now orders --------------------------------------------------------------------------------


@dataclass(frozen=True)
class ActNow:
    advisory: str
    issued_utc: datetime
    share_ppm: int
    threshold_ppm: int


def ps17_act_now(w: World) -> ActNow | None:
    """The first advisory whose PS-17 power-loss share reaches the act-now level (the Forecast plan diff's
    "now past the act-now level" for the generator, fuel truck, pressure and hospital actions)."""
    threshold = int(numbers.value("policy_no_regret_act_now_ppm"))
    advisories = w.members["advisories"]
    for label in sorted(advisories, key=lambda k: advisories[k]["issued_utc"]):
        spec = next(s for s in ps17_specs(advisories[label], w.members) if s.case_id == CASE_POWER)
        share = share_ppm(spec.member_needed or [])
        if share >= threshold:
            return ActNow(label, utc(advisories[label]["issued_utc"]), share, threshold)
    return None


def _share_text(a: ActNow) -> str:
    return (
        f"Advisory {a.advisory} ({reader(a.issued_utc)}) puts {a.share_ppm / 10_000:.1f}% of ensemble members"
        f" past the PS-17 power-loss level, above the act-now level of {a.threshold_ppm / 10_000:.0f}%."
    )


def ps17_orders(w: World) -> list[ZoneHit]:
    a = ps17_act_now(w)
    if a is None:
        return []
    named = w.network["named"]
    ps17 = w.water("PS-17")
    truck = _rule(w, "ps17_fuel_dispatch")
    depot = str(named["fuel_truck"]["depot"])
    generator = str(named["portable_generator"]["id"])
    fuel = ZoneHit(
        key="ps17_fuel_dispatch",
        rule="ps17_fuel_dispatch",
        proposer=str(truck["proposer"]),
        case_id=str(truck["case_id"]),
        action_type=ActionType.FIELD_RESOURCE_ORDER,
        known_at=a.issued_utc,
        resolved_at=utc(ps17["grid_loss_utc"]),
        target_ids=(str(truck["resource"]),),
        params=_params(
            w,
            "ps17_fuel_dispatch",
            a.issued_utc,
            resource_kind="fuel",
            resource_id=str(truck["resource"]),
            from_id=depot,
            destination_id="PS-17",
            serves_id=generator,
            advisory=a.advisory,
            share_ppm=a.share_ppm,
            act_now_ppm=a.threshold_ppm,
        ),
        rationale=(
            f"{_share_text(a)} PS-17 has no onsite generator; the portable generator {generator} needs"
            " fuel on"
            f" site before it starts. Send fuel truck {truck['resource']} from {depot} to PS-17."
        ),
        evidence=(f"advisory:{a.advisory}", "water_twin:ps17_clock_members"),
    )
    tanker = _rule(w, "hospital_tanker")
    hospital = str(named["hospital"]["id"])
    storage_h = float(w.members["hospital_storage_h"])
    water = ZoneHit(
        key="hospital_tanker",
        rule="hospital_tanker",
        proposer=str(tanker["proposer"]),
        case_id=str(tanker["case_id"]),
        action_type=ActionType.FIELD_RESOURCE_ORDER,
        known_at=a.issued_utc,
        resolved_at=utc(ps17["below_floor_utc"]),
        target_ids=(str(tanker["resource"]),),
        params=_params(
            w,
            "hospital_tanker",
            a.issued_utc,
            resource_kind="potable_water_tanker",
            resource_id=str(tanker["resource"]),
            from_id=depot,
            destination_id=hospital,
            zone_id=str(named["hospital"]["zone"]),
            tanker_gal=int(tanker["tanker_gal"]),
            hospital_storage_h=round(storage_h),
            advisory=a.advisory,
            share_ppm=a.share_ppm,
            act_now_ppm=a.threshold_ppm,
        ),
        rationale=(
            f"{_share_text(a)} Tallowbranch hospital ({hospital}) holds {storage_h:.0f} h of water on"
            " site once"
            " the Cedarfall zone drops below the 25 psi floor. Send potable water tanker"
            f" {tanker['resource']}"
            f" ({int(tanker['tanker_gal']):,} gal) from {depot} to the hospital."
        ),
        evidence=(f"advisory:{a.advisory}", "water_twin:hospital_storage"),
    )
    return [fuel, water]


def hospital_tanker_observed(w: World) -> list[ZoneHit]:
    """Once the Cedarfall zone is observed below the floor, the tanker clock runs from that observation:
    hospital onsite storage after the floor crossing, minus the tanker lead time (the forecast case's
    proposal stops there)."""
    rule = _rule(w, "hospital_tanker_observed")
    named = w.network["named"]
    ps17 = w.water("PS-17")
    hospital = str(named["hospital"]["id"])
    zone_id = str(named["hospital"]["zone"])
    below = utc(ps17["below_floor_utc"])
    storage_h = float(w.members["hospital_storage_h"])
    depot = str(named["fuel_truck"]["depot"])
    gal = int(rule["tanker_gal"])
    return [
        ZoneHit(
            key="hospital_tanker_observed",
            rule="hospital_tanker_observed",
            proposer=str(rule["proposer"]),
            case_id=str(rule["case_id"]),
            action_type=ActionType.FIELD_RESOURCE_ORDER,
            known_at=below,
            resolved_at=utc(ps17["back_above_floor_utc"]),
            target_ids=(str(rule["resource"]),),
            params=_params(
                w,
                "hospital_tanker_observed",
                below,
                resource_kind="potable_water_tanker",
                resource_id=str(rule["resource"]),
                from_id=depot,
                destination_id=hospital,
                zone_id=zone_id,
                tanker_gal=gal,
                hospital_storage_h=round(storage_h),
                min_psi=round(float(ps17["min_pressure_psi"])),
            ),
            rationale=(
                f"The Cedarfall zone fell below the 25 psi floor at {reader(below)}; Tallowbranch hospital"
                f" ({hospital}) now runs on {storage_h:.0f} h of stored water. Send potable water tanker"
                f" {rule['resource']} ({gal:,} gal) from {depot} to the hospital."
            ),
            clock=CaseClock(
                step=DecisionStep.D3,
                title="Send a potable water tanker to Tallowbranch hospital",
                domain=Domain.WATER,
                consequence_basis=basis("water_twin.hospital_storage"),
                anchor_label="Cedarfall zone below the 25 psi floor at the hospital connection",
                anchor_basis=basis("rule.sc_service_pressure_normal", "S.C. Code Regs. R.61-58.7.E(7)"),
                anchor_utc=below,
                terms=(
                    AddOnTerm(
                        "hospital onsite storage after the zone floor",
                        basis("water_twin.hospital_storage"),
                        60.0 * storage_h,
                    ),
                ),
                lead_key=str(rule["lead_key"]),
                if_late="Tallowbranch hospital exhausts onsite water storage before a tanker arrives.",
            ),
            evidence=("scada:PT-HSP-TALLOWBRANCH", "water_twin:hospital_storage"),
        )
    ]


# ---- boil-water advisories and their lifts ---------------------------------------------------------------


def _zones(w: World) -> Mapping[str, Mapping[str, Any]]:
    found: Mapping[str, Mapping[str, Any]] = w.rules["zones"]
    return found


def zone_case_id(zone_id: str, suffix: str) -> str:
    station, name = zone_id.removeprefix("WZ-").split("-", 1)
    return f"DC-D3-{station}-{name}-{suffix}"


def _floor_hit(w: World, zone_id: str) -> bwa.RuleHit | None:
    z = _zones(w)[zone_id]
    water = w.water(str(z["station"]))
    if water.get("below_floor_utc") is None:
        return None
    reading = bwa.PressureReading(
        node_id=f"{z['station']}-ZONE-SERVICE",
        at_utc=utc(water["below_floor_utc"]),
        psi=float(water["min_pressure_psi"]),
        service_connection=True,
    )
    hits = bwa.pressure_hits(State.SC, zone_id, [reading])
    return hits[0] if hits else None


@dataclass(frozen=True)
class Lift:
    zone_id: str
    known_at: datetime
    samples: tuple[Sample, ...]
    check: bwa.LiftCheck


def lift_of(w: World, zone_id: str, now: datetime | None = None) -> Lift | None:
    """The lift the LIMS feed allows for a zone (first time all clauses but SCDES concurrence are met)."""
    z = _zones(w)[zone_id]
    water = w.water(str(z["station"]))
    if water.get("back_above_floor_utc") is None:
        return None
    restored = utc(water["back_above_floor_utc"])
    needed = int(numbers.value("sc_bwn_lift_sample_sets"))
    cause = bwa.Cause.PRE_HURRICANE if z.get("issue_case") else bwa.Cause.PRESSURE_LOSS
    seen: list[Sample] = []
    for s in (x for x in w.samples if x.zone_id == zone_id):
        if now is not None and s.known_utc > now:
            break
        seen.append(s)
        if len(seen) < needed:
            continue
        sets = [bwa.SampleSet(x.taken_utc, 1, (x.sample_id,), 0 if x.absent else 1) for x in seen]
        check = bwa.lift_check(
            State.SC,
            cause,
            bwa.LiftEvidence(
                pressure_restored=True,
                flushed_utc=restored,
                sample_sets=sets,
                lost_pressure=True,
                quality_maintained=all(x.absent for x in seen),
            ),
        )
        pending = {clause for clause, _ in check.unmet}
        if pending == {"SC-L4"} and all(x.absent for x in seen):
            return Lift(zone_id, s.known_utc, tuple(seen), check)
    return None


def bwa_issues(w: World) -> list[ZoneHit]:
    rule = _rule(w, "bwa_issue")
    window_h = float(numbers.value("sc_bwa_written_notice_h"))
    book = bwa.rulebook()
    release = book.clause("SC-I1")
    out: list[ZoneHit] = []
    for zone_id, z in _zones(w).items():
        if z.get("issue_case"):
            continue
        hit = _floor_hit(w, zone_id)
        if hit is None or hit.due_utc is None:
            continue
        floor_clause = book.clause(str(hit.detail["floor_clause"]))
        lift = lift_of(w, zone_id)
        name = str(z["name"])
        out.append(
            ZoneHit(
                key=f"bwa_issue:{zone_id}",
                rule="bwa_issue",
                proposer=str(rule["proposer"]),
                case_id=zone_case_id(zone_id, "BWA"),
                action_type=ActionType.BOIL_WATER_NOTICE,
                known_at=hit.due_utc,
                resolved_at=lift.known_at if lift else None,
                target_ids=(zone_id,),
                params=_params(
                    w,
                    "bwa_issue",
                    hit.due_utc,
                    zone_id=zone_id,
                    zone_name=name,
                    station_id=str(z["station"]),
                    notice_kind=hit.kind.value,
                    cause=hit.cause.value,
                    clause=hit.clause.clause_id,
                    floor_clause=floor_clause.clause_id,
                    min_psi=round(float(hit.detail["psi"])),
                    floor_psi=round(float(hit.detail["floor_psi"])),
                ),
                rationale=(
                    f"Pressure in the {name} zone fell to {hit.detail['psi']:.0f} psi at"
                    f" {reader(hit.due_utc)},"
                    f" below the {hit.detail['floor_psi']:.0f} psi floor at service connections"
                    f" ({floor_clause.citation}). {hit.clause.summary.capitalize()} ({hit.clause.clause_id});"
                    f" the written notice is due within {window_h:.0f} h ({release.clause_id})."
                ),
                clock=CaseClock(
                    step=DecisionStep.D3,
                    title=f"Issue a boil water advisory for the {name} zone",
                    domain=Domain.WATER,
                    consequence_basis=basis(release.rule_id, release.citation, ClockKind.RULE_DEADLINE),
                    anchor_label=f"{name} zone pressure below the {hit.detail['floor_psi']:.0f} psi floor",
                    anchor_basis=basis(str(hit.detail["floor_rule_id"]), floor_clause.citation),
                    anchor_utc=hit.due_utc,
                    terms=(
                        AddOnTerm(
                            "written notice window after the pressure loss",
                            basis(release.rule_id, release.citation, ClockKind.RULE_DEADLINE),
                            60.0 * window_h,
                        ),
                    ),
                    lead_key=str(rule["lead_key"]),
                    if_late=f"Customers in the {name} zone drink unsafe water without a written notice.",
                ),
                evidence=(f"scada:{z['station']}", f"rule:{hit.clause.rule_id}"),
            )
        )
    return out


def bwa_lifts(w: World) -> list[ZoneHit]:
    rule = _rule(w, "bwa_lift")
    release_h = w.policy("lift_release_h")
    concurrence = bwa.rulebook().clause("SC-L4")
    out: list[ZoneHit] = []
    for zone_id, z in _zones(w).items():
        lift = lift_of(w, zone_id)
        if lift is None:
            continue
        name = str(z["name"])
        notice_case = str(z.get("issue_case") or zone_case_id(zone_id, "BWA"))
        ids = [s.sample_id for s in lift.samples]
        out.append(
            ZoneHit(
                key=f"bwa_lift:{zone_id}",
                rule="bwa_lift",
                proposer=str(rule["proposer"]),
                case_id=zone_case_id(zone_id, "BWA-LIFT"),
                action_type=ActionType.LIFT_BOIL_WATER_NOTICE,
                known_at=lift.known_at,
                resolved_at=None,
                target_ids=(zone_id,),
                params=_params(
                    w,
                    "bwa_lift",
                    lift.known_at,
                    zone_id=zone_id,
                    zone_name=name,
                    notice_case_id=notice_case,
                    sample_ids=ids,
                    clean_sets=len(ids),
                    lift_path=lift.check.path,
                    clauses_met=list(lift.check.met),
                    pending_clause=concurrence.clause_id,
                ),
                rationale=(
                    f"{len(ids)} total coliform sample sets from the {name} zone came back absent"
                    f" ({', '.join(ids)}; the last reported {reader(lift.known_at)}) after pressure was"
                    " restored."
                    f" Clauses met: {', '.join(lift.check.met)}. Lifting needs SCDES agreement"
                    f" ({concurrence.clause_id}), which the compliance signature records."
                ),
                clock=CaseClock(
                    step=DecisionStep.D3,
                    title=f"Lift the boil water advisory for the {name} zone",
                    domain=Domain.WATER,
                    consequence_basis=basis("policy.zone_lift_release", "SGW policy (assumed, R29)"),
                    anchor_label="last clean total coliform result reported (LIMS)",
                    anchor_basis=basis("lims.total_coliform", concurrence.citation),
                    anchor_utc=lift.known_at,
                    terms=(
                        AddOnTerm(
                            "lift release target after the last clean result",
                            basis("policy.zone_lift_release", "SGW policy (assumed, R29)"),
                            60.0 * release_h,
                        ),
                    ),
                    lead_key=str(rule["lead_key"]),
                    if_late=f"{name} customers keep boiling water after the samples show it is safe.",
                ),
                evidence=tuple(f"lims:{i}" for i in ids),
            )
        )
    return out


# ---- D7 restoration order, W9 dark section ---------------------------------------------------------------


def restoration_order(w: World) -> list[ZoneHit]:
    rule = _rule(w, "restoration_order")
    d7 = w.seeded(str(rule["seeded_case"]))
    named = w.network["named"]
    other_id, ps17_feeder = (str(e) for e in d7["entities"][:2])
    hospital = named["hospital"]
    zone = w.water("PS-17")
    below = utc(zone["below_floor_utc"])
    faults = [utc(d7["outcome"]["fault_utc"]), utc(d7["outcome"]["ps17_feeder"]["fault_utc"])]
    known_at = max([below, *faults])
    policy = RankPolicy.default()
    feeders = named["feeders"]
    ce = {
        ps17_feeder: expected_impact(
            ImpactInput(
                ps17_feeder, 1.0, int(feeders[ps17_feeder]["customers"]), critical_facilities=("hospital",)
            ),
            policy,
        ),
        other_id: expected_impact(ImpactInput(other_id, 1.0, int(feeders[other_id]["customers"])), policy),
    }
    first, second = sorted(ce, key=lambda f: (-ce[f].expected_impact, f))
    repaired = {
        ps17_feeder: utc(d7["outcome"]["ps17_feeder"]["repaired_utc"]),
        other_id: utc(d7["outcome"]["repaired_utc"]),
    }
    storage_h = float(w.members["hospital_storage_h"])
    margin = 100.0 * (ce[first].expected_impact - ce[second].expected_impact) / ce[first].expected_impact
    return [
        ZoneHit(
            key="restoration_order",
            rule="restoration_order",
            proposer=str(rule["proposer"]),
            case_id=str(rule["case_id"]),
            action_type=ActionType.CROSS_DOMAIN_PRIORITY,
            known_at=known_at,
            resolved_at=repaired[first],
            target_ids=(ps17_feeder, other_id),
            params=_params(
                w,
                "restoration_order",
                known_at,
                priority=[first, second],
                station_id="PS-17",
                zone_id=str(hospital["zone"]),
                critical_customer_id=str(hospital["id"]),
                **{f"customers_{f}": int(feeders[f]["customers"]) for f in (ps17_feeder, other_id)},
                **{f"ce_{f}": ce[f].expected_impact_ce for f in (ps17_feeder, other_id)},
            ),
            rationale=(
                f"{ps17_feeder} (PS-17, {feeders[ps17_feeder]['customers']:,} customers) and {other_id}"
                f" ({feeders[other_id]['customers']:,} customers) are both out, and the Cedarfall zone"
                " has been"
                f" below the 25 psi floor since {reader(below)}. Counting Tallowbranch hospital through"
                " its water"
                f" supply, CE expected impact is {ce[first].expected_impact_ce:,} for {first} against"
                f" {ce[second].expected_impact_ce:,} for {second} ({margin:.0f}% apart): restore {first}"
                " first."
                f" The pre-landfall PS-17 priority put {ps17_feeder} first; command and water operations"
                " decide."
            ),
            clock=CaseClock(
                step=DecisionStep.D3,
                title=f"Set the restoration order of {first} and {second}",
                domain=Domain.ELECTRIC,
                consequence_basis=basis("water_twin.hospital_storage"),
                anchor_label="Cedarfall zone below the 25 psi floor at the hospital connection",
                anchor_basis=basis("rule.sc_service_pressure_normal", "S.C. Code Regs. R.61-58.7.E(7)"),
                anchor_utc=below,
                terms=(
                    AddOnTerm(
                        "hospital onsite storage after the zone floor",
                        basis("water_twin.hospital_storage"),
                        60.0 * storage_h,
                    ),
                ),
                lead_key=str(rule["lead_key"]),
                if_late=(
                    "Crews keep the order they were given;"
                    f" Tallowbranch hospital's water depends on {ps17_feeder}."
                ),
            ),
            evidence=(f"oms:{ps17_feeder}", f"oms:{other_id}", "ranking:ce"),
        )
    ]


def ami_dark_section(w: World) -> list[ZoneHit]:
    rule = _rule(w, "ami_dark_section")
    w9 = w.seeded(str(rule["seeded_case"]))
    o = w9["outcome"]
    section = str(o["section"])
    feeder = str(w9["entities"][0])
    silence = w.policy("ami_silence_min")
    confirm_h = w.policy("silent_outage_confirm_h")
    known_at = utc(o["fault_utc"]) + timedelta(minutes=silence)
    meters = int(o["meters_suppressed"])
    where = f"section {section.rsplit('-S', 1)[1]} of {feeder}"
    return [
        ZoneHit(
            key="ami_dark_section",
            rule="ami_dark_section",
            proposer=str(rule["proposer"]),
            case_id=str(rule["case_id"]),
            action_type=ActionType.WORK_ORDER_DRAFT,
            known_at=known_at,
            resolved_at=utc(o["repaired_utc"]),
            target_ids=(feeder,),
            params=_params(
                w,
                "ami_dark_section",
                known_at,
                work="patrol",
                feeder_id=feeder,
                section_id=section,
                meters_dark=meters,
                last_gasps=int(o["last_gasps_emitted"]),
                silence_min=round(silence),
            ),
            rationale=(
                f"{meters} AMI meters on {where} stopped reporting with no last gasp; after"
                f" {silence:.0f} min"
                " of silence the section is treated as a silent outage the outage system cannot see."
                f" Draft a patrol work order for {where}."
            ),
            clock=CaseClock(
                step=DecisionStep.D2,
                title=f"Patrol the dark AMI section of {feeder}",
                domain=Domain.ELECTRIC,
                consequence_basis=basis("policy.silent_outage_confirm", "SGW policy (assumed, R29)"),
                anchor_label=f"{where.capitalize()} dark for {silence:.0f} min without a last gasp",
                anchor_basis=basis("ami.dark_section"),
                anchor_utc=known_at,
                terms=(
                    AddOnTerm(
                        "silent outage confirmed by patrol",
                        basis("policy.silent_outage_confirm", "SGW policy (assumed, R29)"),
                        60.0 * confirm_h,
                    ),
                ),
                lead_key=str(rule["lead_key"]),
                if_late=f"Customers on {where} stay out with nobody assigned to restore them.",
            ),
            evidence=(f"ami:{section}",),
        )
    ]


# ---- PS-38 fuel reroute, PS-52 mobile generator ----------------------------------------------------------


def _station(w: World, station: str) -> tuple[str, str]:
    ps = w.network["named"]["pump_stations"][station]
    zone_id = str(ps["zone"])
    return zone_id, str(_zones(w)[zone_id]["name"])


def ps38_fuel_reroute(w: World) -> list[ZoneHit]:
    rule = _rule(w, "ps38_fuel_reroute")
    station = str(rule["station"])
    truck = str(rule["resource"])
    generator = str(w.network["named"]["pump_stations"][station]["onsite_generator"])
    requested = w.event(station, truck, f"requested:{generator}")
    dry = w.event(station, generator, "out_of_fuel")
    delivered = w.event(station, truck, f"delivered:{generator}")
    if requested is None or dry is None:
        return []
    pin = w.seeded("D3-FUEL-TRUCK-FLOOD-BLOCK")["pin"]
    zone_id, name = _station(w, station)
    depot = str(w.network["named"]["fuel_truck"]["depot"])
    return [
        ZoneHit(
            key="ps38_fuel_reroute",
            rule="ps38_fuel_reroute",
            proposer=str(rule["proposer"]),
            case_id=str(rule["case_id"]),
            action_type=ActionType.FIELD_RESOURCE_ORDER,
            known_at=requested,
            resolved_at=delivered,
            target_ids=(truck,),
            params=_params(
                w,
                "ps38_fuel_reroute",
                requested,
                resource_kind="fuel",
                resource_id=truck,
                from_id=depot,
                destination_id=station,
                serves_id=generator,
                zone_id=zone_id,
                route="alternate",
                blocked_h=int(pin["refuel_blocked_h"]),
                tank_h=int(pin["tank_h"]),
            ),
            rationale=(
                f"{generator} at {station} has been running on its own tank since landfall and was asked"
                " for fuel"
                f" at {reader(requested)}, but the road from {depot} is flooded (blocked about"
                f" {pin['refuel_blocked_h']} h)."
                f" At the current burn the generator runs dry at {reader(dry)} and the {name} zone loses"
                " pressure."
                f" Reroute {truck} by the alternate road."
            ),
            clock=CaseClock(
                step=DecisionStep.D3,
                title=f"Reroute fuel truck {truck} to {station}",
                domain=Domain.WATER,
                consequence_basis=basis("eam.generator_fuel_level"),
                anchor_label=f"{generator} runs dry at the current burn",
                anchor_basis=basis("eam.generator_fuel_level"),
                anchor_utc=dry,
                lead_key=str(rule["lead_key"]),
                if_late=f"{station} stops pumping and the {name} zone drops below the 25 psi floor.",
            ),
            evidence=(f"eam:{generator}", f"fsm:{truck}"),
        )
    ]


def ps52_mobile_generator(w: World) -> list[ZoneHit]:
    rule = _rule(w, "ps52_mobile_generator")
    station = str(rule["station"])
    mobile = str(rule["resource"])
    generator = str(w.network["named"]["pump_stations"][station]["onsite_generator"])
    failed = w.event(station, generator, "failed_run")
    water = w.water(station)
    if failed is None or water.get("below_floor_utc") is None:
        return []
    below = utc(water["below_floor_utc"])
    zone_id, name = _station(w, station)
    drain_min = (below - failed).total_seconds() / 60.0
    return [
        ZoneHit(
            key="ps52_mobile_generator",
            rule="ps52_mobile_generator",
            proposer=str(rule["proposer"]),
            case_id=str(rule["case_id"]),
            action_type=ActionType.FIELD_RESOURCE_ORDER,
            known_at=failed,
            resolved_at=utc(water["grid_restore_utc"]),
            target_ids=(mobile,),
            params=_params(
                w,
                "ps52_mobile_generator",
                failed,
                resource_kind="mobile_generator",
                resource_id=mobile,
                destination_id=station,
                replaces_id=generator,
                zone_id=zone_id,
                drain_min=round(drain_min),
            ),
            rationale=(
                f"{generator} failed while running at {reader(failed)}; the feeder to {station} is still out."
                f" The {name} zone tank drains to the 25 psi floor in about {drain_min:.0f} min. Send"
                " the portable"
                f" generator {mobile} to {station}."
            ),
            clock=CaseClock(
                step=DecisionStep.D3,
                title=f"Send portable generator {mobile} to {station}",
                domain=Domain.WATER,
                consequence_basis=basis("water_twin.zone_tank_drain", "S.C. Code Regs. R.61-58.7.E(7)"),
                anchor_label=f"{generator} failed while running",
                anchor_basis=basis("eam.generator_status"),
                anchor_utc=failed,
                terms=(
                    AddOnTerm(
                        f"{name} zone tank drain to the 25 psi floor",
                        basis("water_twin.zone_tank_drain", "S.C. Code Regs. R.61-58.7.E(7)"),
                        drain_min,
                    ),
                ),
                lead_key=str(rule["lead_key"]),
                if_late=f"The {name} zone drops below the 25 psi floor; a boil water advisory follows.",
            ),
            evidence=(f"eam:{generator}", f"scada:{station}"),
        )
    ]


def timeline(w: World | None = None) -> list[ZoneHit]:
    """Every hit of the Helene world, ordered by the time its facts are known."""
    w = w or world()
    hits = [
        *ps17_orders(w),
        *hospital_tanker_observed(w),
        *bwa_issues(w),
        *restoration_order(w),
        *ami_dark_section(w),
        *ps38_fuel_reroute(w),
        *ps52_mobile_generator(w),
        *bwa_lifts(w),
    ]
    return sorted(hits, key=lambda h: (h.known_at, h.key))


def active(now: datetime, hits: Sequence[ZoneHit] | None = None) -> list[ZoneHit]:
    return [h for h in (timeline() if hits is None else hits) if h.active(now)]
