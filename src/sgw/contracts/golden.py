"""Golden material pinned by the contracts: the hand-made `helene_micro` fixture (the PS-17 story), the K16
PS-17 hinge clock vectors and the K4 golden streams. All values are synthetic and labelled so; real storm
facts (Helene, landfall 2024-09-27 03:10 UTC) are only the frame.

Story: advisory N (09-26 09:00Z) puts PS-17's decide-by at 05:30Z; advisory N+1 (15:00Z) brings the
tropical-storm wind onset forward, so PS-17's decide-by moves to 04:10Z, the PS-17 case pulls the crew
pre-positioning case earlier through the critical path, the crew count at Sandhill Yard changes (material),
the first T3 signature is voided and re-collected. PS-17 is approved by ic_01 and wtr_lead_01 at
15:58Z, well before its 04:10Z decide-by; the generator work order points at that approved proposal.
Feeder FDR-AIK-2207 trips at 04:20Z.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sgw.contracts.approval import MaterialFields, action_hash, envelope_from_plan
from sgw.contracts.base import utc_iso
from sgw.contracts.clocks import (
    ClockBasis,
    ClockNode,
    DecisionClock,
    build_clock,
    no_regret_verdict,
    propagate,
)
from sgw.contracts.events import EVENT_MODELS, EnvelopeBase
from sgw.contracts.vocab import ActionType, ClockKind, RiskBand, RunMode, Tier
from sgw.contracts.wire import SseId, WireEvent, WireFrame, encode_frame

NAMESPACE = uuid.UUID("6b1f3c2e-17a5-4d0e-9c3b-5a1e2d4f7017")
POLICY_VERSION = "policy-2026.11.19-w0"
NO_REGRET_THRESHOLD_PPM = 800_000
SCENARIO_START = datetime(2024, 9, 26, 0, 0, tzinfo=UTC)
SCENARIO_END = datetime(2024, 9, 27, 18, 0, tzinfo=UTC)

REGION_AIKEN = "SC-45003"
REGION_RICHMOND = "GA-13245"
PS17 = "PS-17"
HOSPITAL = "HSP-AIK-TALLOWBRANCH"
FEEDER_PS17 = "FDR-AIK-2207"
FEEDER_LARGER = "FDR-AIK-2219"
SUBSTATION = "SUB-AIK-BRAMBLEGATE"
PRESSURE_SENSOR = "PT-PS17-DISCH"
ZONE = "WZ-PS17-CEDARFALL"
YARD_SANDHILL = "STG-AIK-SANDHILL-YARD"
YARD_MILLPOND = "STG-RCH-MILLPOND-YARD"
CREWS = ("CRW-OSPREY-04", "CRW-OSPREY-07", "CRW-KESTREL-02", "CRW-MA-TALON-11")
CASE_CREWS = "DC-D2-CREWS-AIK"
CASE_PS17 = "DC-D3-PS17-POWER"
PROPOSAL_CREWS = "PRP-CREW-AIK-0926A"
PROPOSAL_PS17 = "PRP-PS17-FDR2207-PRIO"


def t(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2024, 9, day, hh, mm, tzinfo=UTC)


@dataclass(frozen=True)
class Advisory:
    label: str
    issued: datetime
    onset_aiken: datetime
    onset_millpond: datetime
    next_advisory: datetime
    ps17_no_regret_ppm: int


ADVISORY_N = Advisory("N", t(26, 9), t(27, 5, 0), t(27, 6, 10), t(26, 15), 640_000)
ADVISORY_N1 = Advisory("N+1", t(26, 15), t(27, 3, 40), t(27, 4, 50), t(26, 21), 910_000)

PS17_LEAD_MIN = 150
CREWS_LEAD_MIN = 300
TANK_DRAWDOWN_MIN = 180

_PRESSURE_MODEL = ClockBasis(
    kind=ClockKind.MODEL_ESTIMATE,
    basis_id="water_twin.ps17_pressure_floor",
    basis_version="0.1-synthetic",
    citation="SC R.61-58.7.E(7) 25 psi floor",
)
_GEN_HOOKUP = ClockBasis(
    kind=ClockKind.MODEL_ESTIMATE,
    basis_id="lead_time.portable_generator_hookup",
    basis_version="0.1-synthetic",
    citation="SOP-WTR-4.2",
)
_WIND_ONSET = ClockBasis(
    kind=ClockKind.MODEL_ESTIMATE,
    basis_id="hazard.ts_wind_onset",
    basis_version="0.1-synthetic",
    citation=None,
)
_CREW_MOBILISE = ClockBasis(
    kind=ClockKind.MODEL_ESTIMATE,
    basis_id="lead_time.crew_mobilise_and_stage",
    basis_version="0.1-synthetic",
    citation="SOP-ELE-2.1",
)


def ps17_clock(adv: Advisory) -> DecisionClock:
    consequence = adv.onset_aiken + timedelta(minutes=TANK_DRAWDOWN_MIN)
    return build_clock(
        consequence_p10_utc=consequence - timedelta(minutes=45),
        consequence_utc=consequence,
        consequence_p90_utc=consequence + timedelta(minutes=50),
        consequence_basis=_PRESSURE_MODEL,
        action_lead_time_min=PS17_LEAD_MIN,
        lead_time_basis=_GEN_HOOKUP,
        if_late="Hospital zone pressure falls below the 25 psi floor before a generator is running at PS-17.",
    )


def crews_clock(adv: Advisory) -> DecisionClock:
    return build_clock(
        consequence_p10_utc=adv.onset_millpond - timedelta(minutes=40),
        consequence_utc=adv.onset_millpond,
        consequence_p90_utc=adv.onset_millpond + timedelta(minutes=40),
        consequence_basis=_WIND_ONSET,
        action_lead_time_min=CREWS_LEAD_MIN,
        lead_time_basis=_CREW_MOBILISE,
        if_late="Crews travel into tropical-storm winds or arrive after the first feeder trips.",
    )


def clock_nodes(adv: Advisory) -> list[ClockNode]:
    return [
        ClockNode(
            case_id=CASE_CREWS,
            decide_by_utc=crews_clock(adv).decide_by_utc,
            action_lead_time_min=CREWS_LEAD_MIN,
        ),
        ClockNode(
            case_id=CASE_PS17,
            decide_by_utc=ps17_clock(adv).decide_by_utc,
            action_lead_time_min=PS17_LEAD_MIN,
            prerequisite_ids=(CASE_CREWS,),
        ),
    ]


def hinge_vectors() -> dict[str, Any]:
    out: dict[str, Any] = {
        "label": "synthetic",
        "policy_no_regret_act_now_ppm": NO_REGRET_THRESHOLD_PPM,
        "cases": {},
    }
    for adv in (ADVISORY_N, ADVISORY_N1):
        prop = propagate(clock_nodes(adv))
        ps = ps17_clock(adv)
        verdict = no_regret_verdict(
            share_ppm=adv.ps17_no_regret_ppm,
            effective_decide_by_utc=prop[CASE_PS17].effective_decide_by_utc,
            next_advisory_utc=adv.next_advisory,
            act_now_threshold_ppm=NO_REGRET_THRESHOLD_PPM,
        )
        out["cases"][adv.label] = {
            "advisory_issued_utc": utc_iso(adv.issued),
            "ps17": {
                "consequence_utc": utc_iso(ps.consequence_utc),
                "action_lead_time_min": ps.action_lead_time_min,
                "decide_by_utc": utc_iso(ps.decide_by_utc),
                "decide_by_p10_utc": utc_iso(ps.decide_by_p10_utc),
                "decide_by_p90_utc": utc_iso(ps.decide_by_p90_utc),
                "effective_decide_by_utc": utc_iso(prop[CASE_PS17].effective_decide_by_utc),
                "no_regret_share_ppm": adv.ps17_no_regret_ppm,
                "next_advisory_utc": utc_iso(adv.next_advisory),
                "no_regret_verdict": verdict.value,
            },
            "crews": {
                "decide_by_utc": utc_iso(crews_clock(adv).decide_by_utc),
                "effective_decide_by_utc": utc_iso(prop[CASE_CREWS].effective_decide_by_utc),
                "bound_by_case_id": prop[CASE_CREWS].bound_by_case_id,
                "on_critical_path": prop[CASE_CREWS].on_critical_path,
            },
        }
    return out


def crew_material(sandhill: int, millpond: int) -> MaterialFields:
    return MaterialFields(
        action_type=ActionType.PREPOSITION_CREWS,
        params={
            f"crews_at_{YARD_SANDHILL}": sandhill,
            f"crews_at_{YARD_MILLPOND}": millpond,
            "envelope_pct": 20,
        },
        target_ids=[YARD_SANDHILL, YARD_MILLPOND],
        risk_band=RiskBand.HIGH,
        preconditions={"roads_open_to_yards": True, "mutual_aid_confirmed": False},
        tier=Tier.T3,
        escalators=["targets_gt_10_or_cost", "helene_scale"],
    )


def ps17_material() -> MaterialFields:
    return MaterialFields(
        action_type=ActionType.CROSS_DOMAIN_PRIORITY,
        params={"restore_first": FEEDER_PS17, "restore_after": FEEDER_LARGER, "portable_generator_kw": 500},
        target_ids=[PS17, FEEDER_PS17],
        risk_band=RiskBand.VERY_HIGH,
        preconditions={"hospital_on_own_generator": True, "ps17_onsite_generator": False},
        tier=Tier.T3,
        escalators=["critical_facility", "cross_domain"],
    )


class _Builder:
    def __init__(self) -> None:
        self.events: list[EnvelopeBase] = []

    def add(
        self,
        type_name: str,
        at: datetime,
        payload: dict[str, Any],
        *,
        key: str,
        source: str,
        classification: str = "C1",
        trust: str = "verified_internal",
        region: str | None = REGION_AIKEN,
        domain: str | None = None,
        issued: datetime | None = None,
        valid: datetime | None = None,
    ) -> None:
        dedup = f"helene_micro:{type_name}:{key}"
        known = at + timedelta(seconds=30)
        model = EVENT_MODELS[type_name]
        self.events.append(
            model.model_validate(
                {
                    "type": type_name,
                    "schema_version": 1,
                    "event_id": str(uuid.uuid5(NAMESPACE, dedup)),
                    "source_id": source,
                    "feed_mode": "synthetic",
                    "run_mode": "replay",
                    "event_time": at,
                    "issued_at": issued,
                    "valid_at": valid,
                    "received_at": known,
                    "known_at": known,
                    "scenario_known_at": known,
                    "dedup_key": dedup,
                    "classification": classification,
                    "trust": trust,
                    "region_id": region,
                    "domain": domain,
                    "payload": payload,
                }
            )
        )


def _pressure_psi(at: datetime) -> float:
    trip = t(27, 4, 20)
    if at < trip:
        return round(62.0 - ((at - t(27, 0)).seconds // 900) * 0.2, 1)
    minutes = (at - trip).total_seconds() / 60
    return round(max(8.0, 60.6 - minutes * 0.2), 1)


def build_micro_events() -> list[EnvelopeBase]:  # noqa: PLR0915
    b = _Builder()
    nws: dict[str, Any] = dict(source="nws-alerts", classification="C0", trust="external", domain=None)
    b.add(
        "WeatherAlert",
        t(26, 3),
        {
            "alert_id": "NWS-SYN-TSW-AIK-01",
            "product": "watch",
            "event_name": "Tropical Storm Watch",
            "severity": "advisory",
            "area_fips": ["45003", "13245"],
            "effective_utc": t(26, 3),
            "expires_utc": t(26, 21),
            "headline": "Tropical Storm Watch (synthetic)",
        },
        key="tsw-01",
        **nws,
    )
    b.add(
        "WeatherAlert",
        t(26, 15, 20),
        {
            "alert_id": "NWS-SYN-TSWARN-AIK-02",
            "product": "warning",
            "event_name": "Tropical Storm Warning",
            "severity": "severe",
            "area_fips": ["45003", "13245"],
            "effective_utc": t(26, 15, 20),
            "expires_utc": t(27, 15),
            "headline": "Tropical Storm Warning (synthetic)",
        },
        key="tswarn-02",
        **nws,
    )
    b.add(
        "WeatherAlert",
        t(27, 1),
        {
            "alert_id": "NWS-SYN-HWW-AIK-03",
            "product": "warning",
            "event_name": "High Wind Warning",
            "severity": "critical",
            "area_fips": ["45003"],
            "effective_utc": t(27, 1),
            "expires_utc": t(27, 15),
            "headline": "High Wind Warning (synthetic)",
        },
        key="hww-03",
        **nws,
    )
    prior = Advisory("N-1", t(26, 3), t(27, 5, 30), t(27, 6, 40), t(26, 9), 520_000)
    for adv in (prior, ADVISORY_N, ADVISORY_N1):
        b.add(
            "WeatherForecastIssued",
            adv.issued,
            {
                "forecast_id": f"ADV-HELENE-SYN-{adv.label.replace('+', 'P')}",
                "issuer": "synthetic",
                "advisory_label": adv.label,
                "storm_name": "Helene",
                "landfall_eta_utc": t(27, 3, 10),
                "ts_wind_onset_utc": adv.onset_aiken,
                "max_gust_ms_by_fips": {"45003": 31.5 if adv is ADVISORY_N1 else 29.0, "13245": 30.0},
                "next_advisory_utc": adv.next_advisory,
            },
            key=f"adv-{adv.label}",
            source="nhc-advisory-synthetic",
            classification="C0",
            trust="external",
            region=None,
            issued=adv.issued,
        )

    for i, crew in enumerate(CREWS):
        yard = YARD_SANDHILL if i % 2 == 0 else YARD_MILLPOND
        region = REGION_AIKEN if yard == YARD_SANDHILL else REGION_RICHMOND
        for j, (status, at) in enumerate(
            (("available", t(26, 10, 5 + i)), ("enroute", t(26, 17, 10 + i)), ("staged", t(26, 22, 30 + i)))
        ):
            b.add(
                "CrewStatus",
                at,
                {
                    "crew_id": crew,
                    "status": status,
                    "location_id": yard if j else None,
                    "headcount": 40 if "MA" in crew else 24,
                },
                key=f"{crew}-{j}",
                source="fsm-crews",
                region=region,
                domain="electric",
            )

    b.add(
        "NetworkTrace",
        t(26, 9, 30),
        {
            "trace_id": "TRC-FDR2207-PS17",
            "source_id": FEEDER_PS17,
            "downstream_ids": [PS17, ZONE],
            "cross_domain_ids": [PS17, HOSPITAL],
        },
        key="trace-2207",
        source="gis-trace",
        classification="C2",
        domain="electric",
    )

    for k in range(37):
        at = t(27, 0) + timedelta(minutes=15 * k)
        b.add(
            "DeviceState",
            at,
            {
                "device_id": PRESSURE_SENSOR,
                "device_kind": "pressure_sensor",
                "tag": "discharge_pressure",
                "value": _pressure_psi(at),
                "unit": "psi",
                "asset_id": PS17,
            },
            key=f"pt-{k:02d}",
            source="scada-water",
            classification="C2",
            domain="water",
        )
    b.add(
        "DeviceState",
        t(27, 4, 20),
        {
            "device_id": f"BRK-{FEEDER_PS17}",
            "device_kind": "breaker",
            "tag": "state",
            "value": "open",
            "asset_id": FEEDER_PS17,
        },
        key="brk-2207",
        source="scada-electric",
        classification="C2",
        domain="electric",
    )
    b.add(
        "DeviceState",
        t(
            27,
            4,
            20,
        ),
        {
            "device_id": f"PMP-{PS17}-1",
            "device_kind": "pump",
            "tag": "running",
            "value": False,
            "asset_id": PS17,
        },
        key="pump-ps17",
        source="scada-water",
        classification="C2",
        domain="water",
    )
    b.add(
        "DeviceState",
        t(27, 4, 35),
        {
            "device_id": f"BRK-{FEEDER_LARGER}",
            "device_kind": "breaker",
            "tag": "state",
            "value": "open",
            "asset_id": FEEDER_LARGER,
        },
        key="brk-2219",
        source="scada-electric",
        classification="C2",
        domain="electric",
    )
    b.add(
        "OutageEvent",
        t(27, 4, 21),
        {
            "outage_id": "OUT-AIK-0927-0412",
            "status": "open",
            "device_id": f"BRK-{FEEDER_PS17}",
            "feeder_id": FEEDER_PS17,
            "customers_out": 1840,
            "cause": "wind",
            "critical_facility_ids": [PS17],
        },
        key="out-2207",
        source="oms",
        domain="electric",
    )
    b.add(
        "OutageEvent",
        t(27, 4, 36),
        {
            "outage_id": "OUT-AIK-0927-0436",
            "status": "open",
            "device_id": f"BRK-{FEEDER_LARGER}",
            "feeder_id": FEEDER_LARGER,
            "customers_out": 3960,
            "cause": "tree",
        },
        key="out-2219",
        source="oms",
        domain="electric",
    )
    for m in range(120):
        feeder = FEEDER_PS17 if m < 48 else FEEDER_LARGER
        base = t(27, 4, 20) if m < 48 else t(27, 4, 35)
        b.add(
            "MeterEvent",
            base + timedelta(seconds=5 * (m % 48) + 3),
            {
                "meter_id": f"MTR-AIK-{70311 + m * 7}",
                "kind": "last_gasp",
                "premise_id": f"PRM-AIK-{50217 + m * 11}",
                "feeder_id": feeder,
            },
            key=f"mtr-{m:03d}",
            source="ami-headend",
            domain="electric",
        )
    b.add(
        "WaterQualitySample",
        t(26, 14),
        {
            "sample_id": "LIMS-SYN-PS17-0926",
            "zone_id": ZONE,
            "analyte": "chlorine_residual",
            "result": "within_range",
            "value": 1.1,
            "unit": "mg/L",
        },
        key="cl-0926",
        source="lims",
        domain="water",
    )
    b.add(
        "WorkOrder",
        t(27, 3, 5),
        {
            "work_order_id": "WO-SYN-PS17-GEN-01",
            "status": "draft",
            "asset_id": PS17,
            "work_type": "portable_generator_hookup",
            "proposal_id": PROPOSAL_PS17,
        },
        key="wo-ps17",
        source="eam",
        domain="water",
    )

    platform: dict[str, Any] = dict(source="sgw-platform", trust="system")
    for adv, delay in ((ADVISORY_N, 20), (ADVISORY_N1, 20)):
        at = adv.issued + timedelta(minutes=delay)
        b.add(
            "RiskSnapshotPublished",
            at,
            {
                "snapshot_id": f"SNP-RISK-{adv.label.replace('+', 'P')}",
                "engine_version": "risk-0.1-synthetic",
                "as_of_utc": adv.issued,
                "top_entities": [
                    {
                        "entity_id": FEEDER_PS17,
                        "p_ppm": 710_000 if adv is ADVISORY_N else 840_000,
                        "band": "high" if adv is ADVISORY_N else "very_high",
                    },
                    {
                        "entity_id": PS17,
                        "p_ppm": 690_000 if adv is ADVISORY_N else 820_000,
                        "band": "high" if adv is ADVISORY_N else "very_high",
                    },
                ],
            },
            key=f"risk-{adv.label}",
            domain=None,
            **platform,
        )
        prop = propagate(clock_nodes(adv))
        for case, clock in ((CASE_CREWS, crews_clock(adv)), (CASE_PS17, ps17_clock(adv))):
            verdict = no_regret_verdict(
                share_ppm=adv.ps17_no_regret_ppm if case == CASE_PS17 else None,
                effective_decide_by_utc=prop[case].effective_decide_by_utc,
                next_advisory_utc=adv.next_advisory,
                act_now_threshold_ppm=NO_REGRET_THRESHOLD_PPM,
            )
            previous = (
                None
                if adv is ADVISORY_N
                else (crews_clock if case == CASE_CREWS else ps17_clock)(ADVISORY_N).decide_by_utc
            )
            b.add(
                "DecisionClockUpdated",
                at + timedelta(minutes=2),
                {
                    "decision_case_id": case,
                    "decide_by_utc": clock.decide_by_utc,
                    "effective_decide_by_utc": prop[case].effective_decide_by_utc,
                    "previous_decide_by_utc": previous,
                    "on_critical_path": prop[case].on_critical_path,
                    "no_regret_verdict": verdict.value,
                    "cause_event_id": str(
                        uuid.uuid5(NAMESPACE, f"helene_micro:WeatherForecastIssued:adv-{adv.label}")
                    ),
                },
                key=f"clock-{case}-{adv.label}",
                domain="water" if case == CASE_PS17 else "electric",
                **platform,
            )

    v1 = action_hash(crew_material(14, 9), POLICY_VERSION)
    v2 = action_hash(crew_material(18, 9), POLICY_VERSION)
    ps17_hash = action_hash(ps17_material(), POLICY_VERSION)
    b.add(
        "ProposalCreated",
        t(26, 9, 40),
        {
            "proposal_id": PROPOSAL_CREWS,
            "decision_case_id": CASE_CREWS,
            "action_type": "preposition_crews",
            "tier": "T3",
            "proposal_version": 1,
            "action_hash": v1,
            "proposed_by": "ops_dm_01",
            "decide_by_utc": crews_clock(ADVISORY_N).decide_by_utc,
            "clock_kind": "model_estimate",
        },
        key="prp-crews-v1",
        domain="electric",
        **platform,
    )
    b.add(
        "ProposalCreated",
        t(26, 9, 45),
        {
            "proposal_id": PROPOSAL_PS17,
            "decision_case_id": CASE_PS17,
            "action_type": "cross_domain_priority",
            "tier": "T3",
            "proposal_version": 1,
            "action_hash": ps17_hash,
            "proposed_by": "system:rule:ps17_pressure_floor",
            "decide_by_utc": ps17_clock(ADVISORY_N).decide_by_utc,
            "clock_kind": "model_estimate",
        },
        key="prp-ps17-v1",
        domain="water",
        classification="C2",
        **platform,
    )
    b.add(
        "ApprovalRecorded",
        t(26, 12, 30),
        {
            "approval_id": "APR-CREW-V1-IC",
            "proposal_id": PROPOSAL_CREWS,
            "proposal_version": 1,
            "action_hash": v1,
            "approver_id": "ic_01",
            "function": "command",
            "decision": "approve",
        },
        key="apr-crews-v1-ic",
        domain="electric",
        **platform,
    )
    b.add(
        "ProposalUpdated",
        t(26, 15, 25),
        {
            "proposal_id": PROPOSAL_CREWS,
            "material": True,
            "proposal_version": 2,
            "action_hash": v2,
            "changed_fields": ["params"],
            "voided_approval_ids": ["APR-CREW-V1-IC"],
            "decide_by_utc": crews_clock(ADVISORY_N1).decide_by_utc,
            "reason": f"Advisory N+1: crews at {YARD_SANDHILL} 14 -> 18",
        },
        key="prp-crews-v2",
        domain="electric",
        **platform,
    )
    b.add(
        "ProposalUpdated",
        t(26, 15, 26),
        {
            "proposal_id": PROPOSAL_PS17,
            "material": False,
            "proposal_version": 1,
            "action_hash": ps17_hash,
            "changed_fields": ["decide_by_utc"],
            "decide_by_utc": ps17_clock(ADVISORY_N1).decide_by_utc,
            "reason": "Advisory N+1 moved the decide-by earlier; no material field changed",
        },
        key="prp-ps17-clock",
        domain="water",
        classification="C2",
        **platform,
    )
    for at, apr, user, fn in (
        (t(26, 16, 5), "APR-CREW-V2-IC", "ic_01", "command"),
        (t(26, 16, 10), "APR-CREW-V2-LOG", "log_01", "logistics"),
    ):
        b.add(
            "ApprovalRecorded",
            at,
            {
                "approval_id": apr,
                "proposal_id": PROPOSAL_CREWS,
                "proposal_version": 2,
                "action_hash": v2,
                "approver_id": user,
                "function": fn,
                "decision": "approve",
            },
            key=apr.lower(),
            domain="electric",
            **platform,
        )
    bounds = envelope_from_plan({f"crews_at_{YARD_SANDHILL}": 18, f"crews_at_{YARD_MILLPOND}": 9}, pct=20)
    b.add(
        "EnvelopeApproved",
        t(26, 16, 11),
        {
            "envelope_id": "ENV-CREW-AIK-V2",
            "proposal_id": PROPOSAL_CREWS,
            "bounds": {k: b.model_dump() for k, b in bounds.items()},
            "valid_until_utc": t(27, 12),
        },
        key="env-crews",
        domain="electric",
        **platform,
    )
    b.add(
        "DecisionApproved",
        t(26, 16, 11),
        {
            "decision_case_id": CASE_CREWS,
            "proposal_id": PROPOSAL_CREWS,
            "proposal_version": 2,
            "action_hash": v2,
            "tier": "T3",
            "approver_ids": ["ic_01", "log_01"],
        },
        key="dec-crews",
        domain="electric",
        **platform,
    )
    for at, apr, user, fn in (
        (t(26, 15, 52), "APR-PS17-V1-IC", "ic_01", "command"),
        (t(26, 15, 58), "APR-PS17-V1-WLEAD", "wtr_lead_01", "water_operations"),
    ):
        b.add(
            "ApprovalRecorded",
            at,
            {
                "approval_id": apr,
                "proposal_id": PROPOSAL_PS17,
                "proposal_version": 1,
                "action_hash": ps17_hash,
                "approver_id": user,
                "function": fn,
                "decision": "approve",
            },
            key=apr.lower(),
            domain="water",
            classification="C2",
            **platform,
        )
    b.add(
        "DecisionApproved",
        t(26, 15, 58),
        {
            "decision_case_id": CASE_PS17,
            "proposal_id": PROPOSAL_PS17,
            "proposal_version": 1,
            "action_hash": ps17_hash,
            "tier": "T3",
            "approver_ids": ["ic_01", "wtr_lead_01"],
        },
        key="dec-ps17",
        domain="water",
        classification="C2",
        **platform,
    )
    b.add(
        "CommitmentCreated",
        t(26, 16, 12),
        {
            "commitment_id": "CMT-CREW-AIK-STAGED",
            "decision_case_id": CASE_CREWS,
            "proposal_id": PROPOSAL_CREWS,
            "promised_by_utc": t(26, 23, 30),
            "milestones": ["mobilised", "enroute", "staged"],
        },
        key="cmt-crews",
        domain="electric",
        **platform,
    )
    b.add(
        "ScenarioClockChanged",
        t(26, 3, 40),
        {"scenario_time_utc": t(26, 3, 40), "speed": 60, "bookmark": "H0-24"},
        key="bookmark-h0-24",
        region=None,
        **platform,
    )
    return sorted(b.events, key=lambda e: (e.event_time, e.dedup_key))


MICRO_HEADER: dict[str, object] = {
    "fixture": "helene_micro",
    "schema_version": 1,
    "feed": "all",
    "feed_mode": "synthetic",
    "generator": "hand-made:wp-02 (sgw.contracts.golden)",
    "generator_version": "1.0.0",
    "seed": None,
    "calibration_source": "none; story frame from handoff section 3 (Helene landfall 2024-09-27 03:10 UTC)",
    "scenario_window": {"start_utc": SCENARIO_START, "end_utc": SCENARIO_END},
    "licence": "Apache-2.0 (synthetic data)",
    "hand_made": True,
    "data_label": "synthetic",
    "note": "Hand-made PS-17 story for contract tests: advisory N and N+1, feeder trip, one crew proposal. "
    "Every value is synthetic.",
}


def _frame(type_: WireEvent, seq: int, at: datetime, payload: dict[str, Any], **kw: Any) -> WireFrame:
    return WireFrame(
        type=type_,
        seq=seq,
        ts=at.replace(year=2026, month=11, day=20),
        scenario_time=at,
        run_mode=RunMode.REPLAY,
        classification=kw.pop("classification", "C1"),
        payload=payload,
        **kw,
    )


def ops_stream(events: list[EnvelopeBase]) -> str:
    out: list[str] = []
    ledger = [e for e in events if e.source_id == "sgw-platform"]
    first = ledger[0].event_time
    hb = _frame(
        WireEvent.HEARTBEAT,
        0,
        first,
        {
            "head_ledger_seq": 0,
            "server_time": "2026-11-20T00:00:00Z",
            "kill_level": "K0",
            "degraded_mode": "M0",
        },
    )
    out.append(encode_frame(hb, SseId(stream="ops", epoch=1, seq=0)))
    for i, e in enumerate(ledger, 1):
        payload = {
            "event_type": e.type,
            "event_id": str(e.event_id),
            "payload": e.model_dump(mode="json")["payload"],
        }
        frame = _frame(
            WireEvent.LEDGER, i, e.event_time, payload, ledger_seq=i, classification=e.classification.value
        )
        out.append(encode_frame(frame, SseId(stream="ops", epoch=1, seq=i)))
        if e.type == "DecisionClockUpdated":
            p = e.model_dump(mode="json")["payload"]
            tile = _frame(
                WireEvent.STATE,
                i,
                e.event_time,
                {"tile": "decision_clock", "entity_id": p["decision_case_id"], "version": i, "value": p},
            )
            out.append(encode_frame(tile, SseId(stream="ops", epoch=1, seq=i)))
    resync = _frame(
        WireEvent.RESYNC,
        len(ledger) + 1,
        SCENARIO_END,
        {"reason": "epoch_mismatch", "epoch": 2, "snapshot_url": "/api/proposals"},
    )
    out.append(encode_frame(resync, SseId(stream="ops", epoch=2, seq=0)))
    return "".join(out)


def run_stream() -> str:
    run = "run_ps17_water_continuity_01"
    stream = f"run:{run}"
    at = t(26, 15, 30)
    ph = action_hash(ps17_material(), POLICY_VERSION)
    frames: list[tuple[WireEvent, dict[str, Any], list[str]]] = [
        (WireEvent.RUN_START, {"graph": "water_continuity", "graph_version": "0.1"}, []),
        (WireEvent.AGENT_START, {"node": "narrate"}, ["water_continuity"]),
        (
            WireEvent.TOOL_START,
            {"tool": "get_water_status", "args": {"zone_ids": [ZONE]}},
            ["water_continuity"],
        ),
        (
            WireEvent.TOOL_END,
            {"tool": "get_water_status", "evidence_ids": ["E1", "E2"]},
            ["water_continuity"],
        ),
        (
            WireEvent.TEXT_DELTA,
            {"text": "PS-17 decide-by moved to {E1.decide_by} after advisory N+1. "},
            ["water_continuity"],
        ),
        (
            WireEvent.TEXT_DELTA,
            {"text": "Hospital zone pressure reaches the floor at {E2.consequence}."},
            ["water_continuity"],
        ),
        (WireEvent.AGENT_END, {"node": "narrate"}, ["water_continuity"]),
        (WireEvent.ARTIFACT, {"kind": "proposal_card", "proposal_id": PROPOSAL_PS17}, []),
        (
            WireEvent.APPROVAL_REQUIRED,
            {
                "proposal_id": PROPOSAL_PS17,
                "proposal_version": 1,
                "action_hash": ph,
                "tier": "T3",
                "functions_required": ["command", "water_operations"],
            },
            [],
        ),
        (WireEvent.RUN_PAUSED, {"reason": "approval_required"}, []),
        (WireEvent.RUN_END, {"status": "paused_for_approval"}, []),
    ]
    out = []
    for seq, (kind, payload, ns) in enumerate(frames, 1):
        frame = _frame(
            kind, seq, at + timedelta(seconds=seq), payload, run_id=run, ns=ns, classification="C2"
        )
        out.append(encode_frame(frame, SseId(stream=stream, epoch=1, seq=seq)))
    return "".join(out)


def action_hash_vectors() -> dict[str, Any]:
    cases = {
        "crews_v1": crew_material(14, 9),
        "crews_v2": crew_material(18, 9),
        "ps17_priority": ps17_material(),
    }
    from sgw.contracts.approval import canonical_json

    vectors = []
    for name, mat in cases.items():
        body = {
            "material": mat.model_dump(mode="json"),
            "policy_version": POLICY_VERSION,
            "tier": mat.tier.value,
        }
        vectors.append(
            {
                "name": name,
                "input": body,
                "canonical": canonical_json(body).decode(),
                "sha256": action_hash(mat, POLICY_VERSION),
            }
        )
    extra_input = {"z": [3, 1, 2], "a": {"é": True, "b": None}, "m": "line\n"}
    extra_canonical = canonical_json(extra_input)
    vectors.append(
        {
            "name": "unicode_and_ordering",
            "input": extra_input,
            "canonical": extra_canonical.decode(),
            "sha256": hashlib.sha256(extra_canonical).hexdigest(),
        }
    )
    return {"algorithm": "SHA-256 over RFC 8785 canonical JSON", "vectors": vectors}


def webhook_vectors() -> dict[str, Any]:
    from sgw.contracts.webhooks import sign

    body = b'{"data":{"decision_case_id":"DC-D3-PS17-POWER"},"id":"whd_01","type":"ClockBreached"}'
    secret = b"test-only-webhook-key"
    return {
        "secret_utf8": secret.decode(),
        "timestamp": 1727409600,
        "delivery_id": "whd_01",
        "body_utf8": body.decode(),
        "header": sign(secret, timestamp=1727409600, delivery_id="whd_01", body=body),
    }
