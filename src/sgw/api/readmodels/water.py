"""Read side of the water engines for K3 `/api/water/zones`, `/api/water/advisories` and `/api/water/rules`.

Every number comes from an engine, read at the scenario time with known-at discipline:
- zones: the Helene SCADA fixture (`sgw.models.water.telemetry`, value known at or before the scenario time),
  the service floor from `sgw.models.water.floors` (numbers.yaml), backup power from the generator state;
- advisories: the PS-17 zone status of the `water_continuity` graph (`sgw.agent.graphs.water.zone_status`
  on the water-twin member table, WP-13/WP-24) for every NWS advisory issued by the scenario time, the SC
  pre-landfall rule (`sgw.rules.bwa.pre_landfall_hit`), the SC pressure-loss rule on service-connection
  readings (`sgw.rules.bwa.pressure_hits`) and the latest boil-water proposal for the zone; with
  `SGW_ZONE_RULES` on, also the notice of every zone the zone rules raise one for
  (`sgw.rules.zones.bwa_issues`); each zone's notice stage (due, issued, samples, lift decision, lifted) from
  its notice and lift proposals and the clean total coliform results the LIMS feed reported by then;
- rules: the WP-24 rule book `src/sgw/rules/bwa_rules.yaml`.
The water engines are built on the Helene world only, so the fixture is fixed to it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache, lru_cache
from pathlib import Path
from typing import Any, cast

from psycopg import AsyncConnection

from sgw.contracts.api_models import (
    BwaAdvisory,
    BwaAssessment,
    BwaClause,
    BwaRegister,
    BwaRules,
    HookupSensitivity,
    Provenance,
    SopSection,
    WaterZone,
)
from sgw.contracts.base import ppm_from_fraction
from sgw.contracts.vocab import Classification, NumberLabel, ProposalState
from sgw.models.water.floors import State, service_floor
from sgw.models.water.telemetry import Series, load_water_series

REPO = Path(__file__).resolve().parents[4]
FIXTURE = "helene"
NETWORK_FILE = REPO / "data" / "fixtures" / FIXTURE / "network.json"
SCADA_SOURCE = f"data/fixtures/{FIXTURE}/scada.jsonl"
TRUTH_SOURCE = f"data/fixtures/{FIXTURE}/truth_table.json"
NOTICE_ACTION = "boil_water_notice"
LIFT_ACTION = "lift_boil_water_notice"
MEMBER_TABLE_SOURCE = "data/artefacts/water_twin/ps17_clock_members.json"
RULES_SOURCE = "src/sgw/rules/bwa_rules.yaml"
WATER_STATE = State.SC
POLICY_KEY = "policy_pre_landfall_breach_p"
ADVISORY_ORDER = ("N", "N+1")
BACKUP_STATES = frozenset({"running"})
OPEN_STATES = frozenset(
    {ProposalState.PROPOSED, ProposalState.IN_REVIEW, ProposalState.ESCALATED, ProposalState.DRAFT}
)
ISSUED_STATES = frozenset({ProposalState.APPROVED, ProposalState.EXECUTED})


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


@cache
def network() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(NETWORK_FILE.read_text(encoding="utf-8"))
    return data


@cache
def series() -> dict[str, Series]:
    return load_water_series(FIXTURE)


def _station_series(station_id: str, tag: str) -> list[Series]:
    return [s for s in series().values() if s.asset_id == station_id and s.tag == tag]


def latest_state(s: Series, when: float) -> str | None:
    """A text-valued series (generator state) at or before `when`, by known time."""
    idx = [i for i, k in enumerate(s.known_t) if float(k) <= when]
    return str(s.value[idx[-1]]) if idx else None


def latest_report(states: list[Series], when: float) -> str | None:
    """The newest state reported by any of a station's devices at or before `when`, by known time."""
    reports = [
        (float(known), str(value))
        for s in states
        for known, value in zip(s.known_t, s.value, strict=True)
        if float(known) <= when
    ]
    return max(reports)[1] if reports else None


@dataclass(frozen=True)
class ZoneReading:
    zone: WaterZone
    sensor_ids: tuple[str, ...]


def _pressure_sensors(station_id: str, zone_id: str) -> list[Series]:
    """Service-connection sensors in the zone when it has one (the state floor applies there), else the
    pump-station discharge sensor."""
    hospital = network()["named"]["hospital"]
    service = [
        s
        for s in series().values()
        if s.tag == "service_pressure" and hospital["zone"] == zone_id and s.asset_id == hospital["id"]
    ]
    return service or _station_series(station_id, "discharge_pressure")


def zone_readings(at: datetime) -> list[ZoneReading]:
    named = network()["named"]
    hospital = named["hospital"]
    floor = service_floor(WATER_STATE)
    when = at.timestamp()
    out: list[ZoneReading] = []
    for station_id, station in sorted(named["pump_stations"].items()):
        zone_id = str(station["zone"])
        sensors = _pressure_sensors(station_id, zone_id)
        values = [v for v in (s.at_or_before(when) for s in sensors) if v is not None]
        if not values:
            continue
        states = [latest_state(s, when) for s in _station_series(station_id, "state")]
        out.append(
            ZoneReading(
                zone=WaterZone(
                    zone_id=zone_id,
                    pump_station_id=station_id,
                    pressure_psi_x10=round(min(values) * 10),
                    floor_psi_x10=round(floor.psi * 10),
                    critical_facility_ids=[str(hospital["id"])] if hospital["zone"] == zone_id else [],
                    on_backup_power=any(st in BACKUP_STATES for st in states),
                    onsite_generator_id=station.get("onsite_generator"),
                    generator_state=latest_report(_station_series(station_id, "state"), when),
                ),
                sensor_ids=tuple(s.device_id for s in sensors),
            )
        )
    return out


@lru_cache(maxsize=32)
def below_floor_ids(at: datetime) -> frozenset[str]:
    """Every zone below the state floor at `at`, its pump station and the critical facilities it serves."""
    return frozenset(
        i
        for r in zone_readings(at)
        if r.zone.pressure_psi_x10 < r.zone.floor_psi_x10
        for i in (r.zone.zone_id, r.zone.pump_station_id, *r.zone.critical_facility_ids)
    )


def zones_provenance(at: datetime) -> Provenance:
    floor = service_floor(WATER_STATE)
    return Provenance(
        source=SCADA_SOURCE, rule_id=floor.rule_id, model_id=None, as_of=at, label=NumberLabel.S
    )


# ---- boil-water advisory register -------------------------------------------------------------------------


@cache
def member_table() -> dict[str, Any]:
    from sgw.agent.graphs.water import TWIN_TABLE_FILE

    data: dict[str, Any] = json.loads(TWIN_TABLE_FILE.read_text(encoding="utf-8"))
    return data


@cache
def continuity() -> dict[str, Any]:
    from sgw.agent.graphs.water import CONTINUITY_FILE

    data: dict[str, Any] = json.loads(CONTINUITY_FILE.read_text(encoding="utf-8"))
    return data


@dataclass(frozen=True)
class _TwinInputs:
    """The three inputs `zone_status` reads from `WaterDeps` (member table, network, continuity floor)."""

    member_table: Mapping[str, Any]
    network: Mapping[str, Any]
    continuity: Mapping[str, Any]


@dataclass(frozen=True)
class BwaProposal:
    proposal_id: str
    decision_case_id: str
    state: ProposalState


async def latest_bwa_proposal(
    conn: AsyncConnection[Any], zone_id: str, action: str = NOTICE_ACTION
) -> BwaProposal | None:
    cur = await conn.execute(
        "SELECT proposal_id, decision_case_id, state::text FROM proposal"
        " WHERE action_type = %s AND %s = ANY(targets)"
        " ORDER BY created_at DESC, proposal_id DESC LIMIT 1",
        (action, zone_id),
    )
    row = await cur.fetchone()
    return BwaProposal(str(row[0]), str(row[1]), ProposalState(row[2])) if row else None


def _status(due: bool, proposal: BwaProposal | None) -> str:
    if proposal is not None and proposal.state in ISSUED_STATES:
        return "issued"
    if proposal is not None and proposal.state in OPEN_STATES:
        return "proposed"
    return "due" if due else "not_due"


def service_readings(at: datetime) -> dict[str, list[Any]]:
    """Service-connection pressure readings known by `at`, per zone (the floor rules apply only there)."""
    from sgw.rules import bwa

    hospital = network()["named"]["hospital"]
    when = at.timestamp()
    out: dict[str, list[Any]] = {}
    for s in series().values():
        if s.tag != "service_pressure" or s.asset_id != hospital["id"]:
            continue
        out.setdefault(str(hospital["zone"]), []).extend(
            bwa.PressureReading(
                node_id=s.device_id,
                at_utc=datetime.fromtimestamp(float(t), tz=UTC),
                psi=float(v),
                service_connection=True,
            )
            for t, k, v in zip(s.t, s.known_t, s.value, strict=True)
            if float(k) <= when
        )
    return out


def pressure_loss_rows(at: datetime, proposals: Mapping[str, BwaProposal | None]) -> list[BwaAdvisory]:
    """SC-A1: a service-connection reading below the state floor makes a precautionary advisory due."""
    from sgw.rules import bwa

    stations = {str(st["zone"]): sid for sid, st in network()["named"]["pump_stations"].items()}
    rows: list[BwaAdvisory] = []
    for zone_id, readings in sorted(service_readings(at).items()):
        hits = bwa.pressure_hits(WATER_STATE, zone_id, readings)
        if not hits:
            continue
        first = hits[0]
        proposal = proposals.get(zone_id)
        rows.append(
            BwaAdvisory(
                advisory_id=f"BWA-{zone_id}-PRESSURELOSS",
                state=WATER_STATE.value,
                zone_id=zone_id,
                station_id=stations[zone_id],
                kind="pressure_loss",
                clause_ids=[first.clause.clause_id, str(first.detail["floor_clause"])],
                policy_key=POLICY_KEY,
                policy_value_ppm=ppm_from_fraction(float(_policy())),
                assessments=[],
                sensitivity=[],
                due_utc=first.due_utc,
                status=_status(True, proposal),  # type: ignore[arg-type]
                proposal_id=proposal.proposal_id if proposal else None,
                decision_case_id=proposal.decision_case_id if proposal else None,
                classification=Classification.C2,
                provenance=Provenance(
                    source=SCADA_SOURCE,
                    rule_id=first.clause.rule_id,
                    model_id=None,
                    as_of=first.due_utc,
                    label=NumberLabel.S,
                ),
            )
        )
    return rows


def _policy() -> float:
    from sgw.common import numbers as numbers_mod

    return float(numbers_mod.value(POLICY_KEY))


def zone_rule_rows(at: datetime, proposals: Mapping[str, BwaProposal | None]) -> list[BwaAdvisory]:
    """The notices the zone rules raise for zones below the state floor, once the pressure loss is known."""
    from sgw.models.clocks import zone_cases
    from sgw.rules import zones

    if not zone_cases.enabled():
        return []
    rows: list[BwaAdvisory] = []
    for hit in sorted(zones.bwa_issues(zones.world()), key=lambda h: h.target_ids):
        if hit.known_at > at:
            continue
        zone_id = hit.target_ids[0]
        proposal = proposals.get(zone_id)
        rows.append(
            BwaAdvisory(
                advisory_id=f"BWA-{zone_id}-PRESSURELOSS",
                state=WATER_STATE.value,
                zone_id=zone_id,
                station_id=str(hit.params["station_id"]),
                kind="pressure_loss",
                clause_ids=[str(hit.params["clause"]), str(hit.params["floor_clause"])],
                policy_key=POLICY_KEY,
                policy_value_ppm=ppm_from_fraction(float(_policy())),
                assessments=[],
                sensitivity=[],
                due_utc=hit.known_at,
                status=_status(True, proposal),  # type: ignore[arg-type]
                proposal_id=proposal.proposal_id if proposal else None,
                decision_case_id=proposal.decision_case_id if proposal else hit.case_id,
                classification=Classification.C2,
                provenance=Provenance(
                    source=TRUTH_SOURCE,
                    rule_id=str(hit.params["rule_id"]),
                    model_id=None,
                    as_of=hit.known_at,
                    label=NumberLabel.S,
                ),
            )
        )
    return rows


def clean_samples(zone_id: str, at: datetime) -> int:
    """Clean total coliform results reported for the zone by `at`, taken after its pressure came back."""
    from sgw.rules import zones

    w = zones.world()
    station = w.rules["zones"].get(zone_id, {}).get("station")
    restored = w.water(str(station)).get("back_above_floor_utc") if station else None
    if restored is None:
        return 0
    since = _utc(restored)
    return sum(
        1
        for s in w.samples
        if s.zone_id == zone_id and s.absent and s.known_utc <= at and s.taken_utc >= since
    )


def samples_needed() -> int:
    from sgw.common import numbers as numbers_mod

    return int(numbers_mod.value("sc_bwn_lift_sample_sets"))


def _stage(status: str, lift: BwaProposal | None, clean: int) -> str | None:
    if lift is not None and lift.state in ISSUED_STATES:
        return "lifted"
    if lift is not None and lift.state in OPEN_STATES:
        return "lift_decision"
    if status == "issued":
        return "samples" if clean > 0 else "issued"
    if status in ("due", "proposed"):
        return "due"
    return None


def with_stage(row: BwaAdvisory, at: datetime, lift: BwaProposal | None) -> BwaAdvisory:
    clean = clean_samples(row.zone_id, at)
    stage = _stage(row.status, lift, clean)
    return row.model_copy(
        update={
            "status": "lifted" if stage == "lifted" else row.status,
            "stage": stage,
            "clean_samples": clean,
            "samples_needed": samples_needed(),
            "lift_proposal_id": lift.proposal_id if lift else None,
            "lift_decision_case_id": lift.decision_case_id if lift else None,
        }
    )


def register(
    at: datetime,
    proposals: Mapping[str, BwaProposal | None],
    lifts: Mapping[str, BwaProposal | None] | None = None,
) -> BwaRegister:
    rows = [
        pre_landfall_row(at, proposals),
        *pressure_loss_rows(at, proposals),
        *zone_rule_rows(at, proposals),
    ]
    found = lifts or {}
    return BwaRegister(as_of=at, advisories=[with_stage(r, at, found.get(r.zone_id)) for r in rows])


def without_forecasts(register: BwaRegister) -> BwaRegister:
    """The register for a reader outside the water domain: notices kept, C2 zone forecasts emptied."""
    rows = [
        a.model_copy(update={"assessments": [], "sensitivity": [], "classification": Classification.C1})
        for a in register.advisories
    ]
    return register.model_copy(update={"advisories": rows, "forecasts_withheld": True})


def pre_landfall_row(at: datetime, proposals: Mapping[str, BwaProposal | None]) -> BwaAdvisory:
    """The PS-17 zone's pre-landfall advisory: one assessment per NWS advisory issued by `at`."""
    from sgw.agent.graphs import water as graph
    from sgw.rules import bwa

    deps = cast(graph.WaterDeps, _TwinInputs(member_table(), network(), continuity()))
    policy = _policy()
    known = [a for a in ADVISORY_ORDER if _utc(member_table()["advisories"][a]["issued_utc"]) <= at]
    statuses = [graph.zone_status(deps, a) for a in known]
    link = graph.priority.ps17_link(network())
    proposal = proposals.get(link.zone_id)
    latest = statuses[-1] if statuses else None
    hit = (
        bwa.pre_landfall_hit(
            state=WATER_STATE,
            zone_id=latest.zone_id,
            now=at,
            landfall_utc=graph.LANDFALL_UTC,
            breach_p=latest.breach_p,
            on_backup_or_exposed=latest.on_backup_or_exposed,
        )
        if latest is not None
        else None
    )
    lag = int(member_table()["lead_min"]["generator.hookup_lead_min"])
    sensitivity = (
        [
            HookupSensitivity(hookup_lag_min=s, breach_p_ppm=ppm_from_fraction(p))
            for s, p in sorted(latest.sensitivity.items())
        ]
        + [HookupSensitivity(hookup_lag_min=lag, breach_p_ppm=ppm_from_fraction(latest.breach_p))]
        if latest is not None
        else []
    )
    return BwaAdvisory(
        advisory_id=f"BWA-{link.zone_id}-PRELANDFALL",
        state=WATER_STATE.value,
        zone_id=link.zone_id,
        station_id=link.station_id,
        kind="pre_landfall",
        clause_ids=["SC-A2", "SC-P1"],
        policy_key=POLICY_KEY,
        policy_value_ppm=ppm_from_fraction(policy),
        assessments=[
            BwaAssessment(
                advisory=name,
                issued_utc=z.as_of,
                power_loss_p_ppm=ppm_from_fraction(z.p_loss),
                breach_given_loss_p_ppm=ppm_from_fraction(z.breach_given_loss),
                breach_p_ppm=ppm_from_fraction(z.breach_p),
                at_or_above_policy=z.breach_p >= policy,
            )
            for name, z in zip(known, statuses, strict=True)
        ],
        sensitivity=sensitivity,
        due_utc=graph.LANDFALL_UTC,
        status=_status(hit is not None, proposal),  # type: ignore[arg-type]
        proposal_id=proposal.proposal_id if proposal else None,
        decision_case_id=proposal.decision_case_id if proposal else graph.BWA_CASE,
        classification=Classification.C2,
        provenance=Provenance(
            source=MEMBER_TABLE_SOURCE,
            model_id="water_twin.zone_drain_critical_node",
            rule_id="rule.sc_bwa_pre_landfall",
            as_of=latest.as_of if latest is not None else None,
            label=NumberLabel.S,
        ),
    )


def zone_ids() -> list[str]:
    return sorted(str(st["zone"]) for st in network()["named"]["pump_stations"].values())


def rules() -> BwaRules:
    from sgw.rules import bwa

    book = bwa.rulebook()
    return BwaRules(
        version=book.version,
        source=RULES_SOURCE,
        clauses=[
            BwaClause(
                clause_id=c.clause_id,
                state=c.state.value,  # type: ignore[arg-type]
                rule_id=c.rule_id,
                summary=c.summary,
                citation=c.citation,
                sop=SopSection(doc_id=c.sop.doc_id, section=c.sop.section) if c.sop else None,
                label=NumberLabel(c.label),
            )
            for c in book.clauses.values()
        ],
    )
