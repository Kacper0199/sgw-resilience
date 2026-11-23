"""K2 event envelope and event types.

Every event carries `schema_version`. Readers call `parse_event`, which upcasts older payload
versions through `UPCASTERS` before validation, so stored ledgers stay readable after additive changes.
Ledger events never coalesce; only K4 `state` tiles may.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, create_model, model_validator

from sgw.contracts.approval import EnvelopeBound
from sgw.contracts.base import Contract, Identifier, Ppm, UtcDatetime
from sgw.contracts.vocab import (
    ActionType,
    ApprovalDecision,
    ApprovalFunction,
    Classification,
    ClockKind,
    CommitmentState,
    CrewStatus,
    DegradedMode,
    Domain,
    EffectState,
    FeedMode,
    Finality,
    KillLevel,
    NoRegretVerdict,
    Quality,
    RiskBand,
    RunMode,
    Tier,
    Trust,
    UiSeverity,
)

CURRENT_SCHEMA_VERSION = 1


class WeatherAlert(Contract):
    alert_id: Identifier
    product: Literal["warning", "watch", "advisory", "statement"]
    event_name: str
    severity: UiSeverity
    area_fips: list[str] = Field(min_length=1)
    effective_utc: UtcDatetime
    expires_utc: UtcDatetime
    headline: str


class WeatherForecastIssued(Contract):
    forecast_id: Identifier
    issuer: Literal["NHC", "NWS", "synthetic"]
    advisory_label: str
    storm_name: str
    landfall_eta_utc: UtcDatetime | None = None
    ts_wind_onset_utc: UtcDatetime | None = Field(
        default=None, description="forecast onset of 34 kt winds in the first footprint county (H0, X-09)"
    )
    max_gust_ms_by_fips: dict[str, float] = Field(default_factory=dict)
    next_advisory_utc: UtcDatetime | None = None


class OutageEvent(Contract):
    outage_id: Identifier
    status: Literal["open", "updated", "restored"]
    device_id: Identifier
    feeder_id: Identifier
    customers_out: int = Field(ge=0)
    cause: Literal["unknown", "wind", "tree", "flood", "equipment", "planned"]
    critical_facility_ids: list[Identifier] = Field(default_factory=list)


class DeviceState(Contract):
    device_id: Identifier
    device_kind: Literal["breaker", "recloser", "feeder", "pump", "generator", "pressure_sensor", "tank"]
    tag: str
    value: float | int | str | bool
    unit: str | None = None
    asset_id: Identifier | None = None


class MeterEvent(Contract):
    meter_id: Identifier
    kind: Literal["last_gasp", "power_restore", "voltage_sag"]
    premise_id: Identifier
    feeder_id: Identifier


class WorkOrder(Contract):
    work_order_id: Identifier
    status: Literal["draft", "open", "assigned", "in_progress", "closed", "cancelled"]
    asset_id: Identifier
    work_type: str
    crew_id: Identifier | None = None
    proposal_id: Identifier | None = None


class CrewStatusEvent(Contract):
    crew_id: Identifier
    status: CrewStatus
    location_id: Identifier | None = None
    headcount: int = Field(ge=0)
    block_reason: str | None = None


class NetworkTrace(Contract):
    trace_id: Identifier
    source_id: Identifier
    downstream_ids: list[Identifier]
    cross_domain_ids: list[Identifier] = Field(default_factory=list)


class WaterQualitySample(Contract):
    sample_id: Identifier
    zone_id: Identifier
    analyte: Literal["total_coliform", "e_coli", "chlorine_residual", "turbidity"]
    result: str
    value: float | None = None
    unit: str | None = None


class RiskEntry(Contract):
    entity_id: Identifier
    p_ppm: Ppm
    band: RiskBand


class RiskSnapshotPublished(Contract):
    snapshot_id: Identifier
    engine_version: str
    as_of_utc: UtcDatetime
    top_entities: list[RiskEntry]


class AnomalyDetected(Contract):
    anomaly_id: Identifier
    entity_id: Identifier
    score_ppm: Ppm
    anomaly_class: str


class ProposalCreated(Contract):
    proposal_id: Identifier
    decision_case_id: Identifier
    action_type: ActionType
    tier: Tier
    proposal_version: int = Field(ge=1)
    action_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposed_by: str
    decide_by_utc: UtcDatetime
    clock_kind: ClockKind


class ProposalUpdated(Contract):
    proposal_id: Identifier
    material: bool
    proposal_version: int = Field(ge=1)
    action_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    changed_fields: list[str]
    voided_approval_ids: list[Identifier] = Field(default_factory=list)
    decide_by_utc: UtcDatetime | None = None
    reason: str


class ApprovalRecorded(Contract):
    approval_id: Identifier
    proposal_id: Identifier
    proposal_version: int = Field(ge=1)
    action_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approver_id: Identifier
    function: ApprovalFunction
    decision: ApprovalDecision
    reason_code: str | None = None


class ProposalExpired(Contract):
    proposal_id: Identifier
    proposal_version: int = Field(ge=1)


class ProposalEscalated(Contract):
    proposal_id: Identifier
    from_tier: Tier
    to_tier: Tier
    escalators: list[str]


class EffectStateChanged(Contract):
    effect_id: Identifier
    proposal_id: Identifier
    channel: str
    state: EffectState


class ModeChanged(Contract):
    run_mode: RunMode
    degraded_mode: DegradedMode
    changed_by: Identifier


class KillSwitchChanged(Contract):
    kill_level: KillLevel
    changed_by: list[Identifier] = Field(min_length=1)
    reason: str


class PipelineRunFinished(Contract):
    run_id: Identifier
    asset: str
    status: Literal["success", "failed", "partial"]
    rows_in: int = Field(ge=0)
    rows_out: int = Field(ge=0)
    rows_quarantined: int = Field(ge=0)


class DQCheckFailed(Contract):
    check_id: Identifier
    asset: str
    severity: Literal["warn", "error"]
    detail: str


class CoverageGap(Contract):
    gap_source_id: Identifier
    from_utc: UtcDatetime
    to_utc: UtcDatetime
    reason: str


class ScenarioClockChanged(Contract):
    scenario_time_utc: UtcDatetime
    speed: Literal[0, 1, 60, 900]
    bookmark: str | None = None


class EnvelopeApproved(Contract):
    envelope_id: Identifier
    proposal_id: Identifier
    bounds: dict[str, EnvelopeBound]
    valid_until_utc: UtcDatetime


class BreakGlassUsed(Contract):
    proposal_id: Identifier
    ic_id: Identifier
    reason: str = Field(min_length=10)
    cosign_due_utc: UtcDatetime


class ClockBreached(Contract):
    decision_case_id: Identifier
    proposal_id: Identifier | None = None
    effective_decide_by_utc: UtcDatetime
    breached_at_utc: UtcDatetime
    clock_kind: ClockKind


class CommitmentCreated(Contract):
    commitment_id: Identifier
    decision_case_id: Identifier
    proposal_id: Identifier
    promised_by_utc: UtcDatetime
    milestones: list[str]


class CommitmentDrifted(Contract):
    commitment_id: Identifier
    state: CommitmentState
    promised_by_utc: UtcDatetime
    projected_utc: UtcDatetime
    drift_min: int


class DecisionApproved(Contract):
    decision_case_id: Identifier
    proposal_id: Identifier
    proposal_version: int = Field(ge=1)
    action_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    tier: Tier
    approver_ids: list[Identifier] = Field(min_length=1)
    break_glass: bool = False


class DecisionClockUpdated(Contract):
    decision_case_id: Identifier
    decide_by_utc: UtcDatetime
    effective_decide_by_utc: UtcDatetime
    previous_decide_by_utc: UtcDatetime | None = None
    on_critical_path: bool
    no_regret_verdict: NoRegretVerdict
    cause_event_id: UUID | None = None


class EtrPublished(Contract):
    """Restoration-time estimate (P10..P90 of the time all customers in scope are restored), WP-17."""

    estimate_id: Identifier
    scope: Literal["global", "region"]
    region_id: str
    as_of_utc: UtcDatetime
    p10_utc: UtcDatetime
    p25_utc: UtcDatetime
    p50_utc: UtcDatetime
    p75_utc: UtcDatetime
    p90_utc: UtcDatetime
    peak_customers_out: int = Field(ge=0)
    model_version: str


SOURCE_EVENTS: dict[str, type[Contract]] = {
    "WeatherAlert": WeatherAlert,
    "WeatherForecastIssued": WeatherForecastIssued,
    "OutageEvent": OutageEvent,
    "DeviceState": DeviceState,
    "MeterEvent": MeterEvent,
    "WorkOrder": WorkOrder,
    "CrewStatus": CrewStatusEvent,
    "NetworkTrace": NetworkTrace,
    "WaterQualitySample": WaterQualitySample,
}

PLATFORM_EVENTS: dict[str, type[Contract]] = {
    "RiskSnapshotPublished": RiskSnapshotPublished,
    "AnomalyDetected": AnomalyDetected,
    "ProposalCreated": ProposalCreated,
    "ProposalUpdated": ProposalUpdated,
    "ApprovalRecorded": ApprovalRecorded,
    "ProposalExpired": ProposalExpired,
    "ProposalEscalated": ProposalEscalated,
    "EffectStateChanged": EffectStateChanged,
    "ModeChanged": ModeChanged,
    "KillSwitchChanged": KillSwitchChanged,
    "PipelineRunFinished": PipelineRunFinished,
    "DQCheckFailed": DQCheckFailed,
    "CoverageGap": CoverageGap,
    "ScenarioClockChanged": ScenarioClockChanged,
    "EnvelopeApproved": EnvelopeApproved,
    "BreakGlassUsed": BreakGlassUsed,
    "ClockBreached": ClockBreached,
    "CommitmentCreated": CommitmentCreated,
    "CommitmentDrifted": CommitmentDrifted,
    "DecisionApproved": DecisionApproved,
    "DecisionClockUpdated": DecisionClockUpdated,
    "EtrPublished": EtrPublished,
}

EVENT_PAYLOADS: dict[str, type[Contract]] = {**SOURCE_EVENTS, **PLATFORM_EVENTS}
WEBHOOK_EVENT_TYPES: tuple[str, ...] = (
    "ClockBreached",
    "CommitmentCreated",
    "CommitmentDrifted",
    "DecisionApproved",
)


class EnvelopeBase(Contract):
    type: str
    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION, ge=1)
    event_id: UUID
    source_id: Identifier
    feed_mode: FeedMode
    run_mode: RunMode
    event_time: UtcDatetime
    issued_at: UtcDatetime | None = None
    valid_at: UtcDatetime | None = None
    received_at: UtcDatetime
    known_at: UtcDatetime
    scenario_known_at: UtcDatetime
    ledger_seq: int | None = Field(default=None, ge=1)
    dedup_key: str = Field(min_length=1, max_length=256)
    classification: Classification
    trust: Trust
    quality: Quality = Quality.GOOD
    coverage_ppm: int = Field(default=1_000_000, ge=0, le=1_000_000)
    finality: Finality = Finality.CONFIRMED
    supersedes: UUID | None = None
    region_id: str | None = None
    domain: Domain | None = None

    @model_validator(mode="after")
    def _time_order(self) -> EnvelopeBase:
        if self.known_at < self.event_time and self.valid_at is None:
            raise ValueError("known_at precedes event_time for an observation without valid_at")
        return self


def _make_event_model(type_name: str, payload: type[Contract]) -> type[EnvelopeBase]:
    model = create_model(
        f"{type_name}Event",
        __base__=EnvelopeBase,
        type=(Literal[type_name], ...),  # type: ignore[arg-type]
        schema_version=(int, Field(default=EVENT_SCHEMA_VERSIONS[type_name], ge=1)),
        payload=(payload, ...),
    )
    model.__doc__ = f"K2 envelope carrying a `{type_name}` payload."
    return model


EVENT_SCHEMA_VERSIONS: dict[str, int] = {name: CURRENT_SCHEMA_VERSION for name in EVENT_PAYLOADS}
"""Current payload version per event type; bump one type, register its upcaster, leave the others alone."""

EVENT_MODELS: dict[str, type[EnvelopeBase]] = {
    name: _make_event_model(name, payload) for name, payload in EVENT_PAYLOADS.items()
}

_union: Any = EVENT_MODELS["WeatherAlert"]
for _model in list(EVENT_MODELS.values())[1:]:
    _union = _union | _model
AnyEvent = Annotated[_union, Field(discriminator="type")]
EVENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(AnyEvent)

Upcaster = Callable[[dict[str, Any]], dict[str, Any]]
UPCASTERS: dict[tuple[str, int], Upcaster] = {}


def register_upcaster(type_name: str, from_version: int) -> Callable[[Upcaster], Upcaster]:
    def deco(fn: Upcaster) -> Upcaster:
        UPCASTERS[(type_name, from_version)] = fn
        return fn

    return deco


def upcast(raw: dict[str, Any]) -> dict[str, Any]:
    data = dict(raw)
    version = int(data.get("schema_version", 1))
    type_name = str(data.get("type"))
    if type_name not in EVENT_SCHEMA_VERSIONS:
        raise ValueError(f"unknown event type {type_name!r}")
    current = EVENT_SCHEMA_VERSIONS[type_name]
    while version < current:
        step = UPCASTERS.get((type_name, version))
        if step is None:
            raise ValueError(f"no upcaster for {type_name} v{version}")
        data = step(data)
        version += 1
        data["schema_version"] = version
    if version > current:
        raise ValueError(f"{type_name} v{version} is newer than this reader (v{current})")
    return data


def parse_event(raw: dict[str, Any]) -> EnvelopeBase:
    event: EnvelopeBase = EVENT_ADAPTER.validate_python(upcast(raw))
    return event


def parse_event_json(line: str | bytes) -> EnvelopeBase:
    import json

    return parse_event(json.loads(line))


def dump_event(event: EnvelopeBase) -> dict[str, Any]:
    return event.model_dump(mode="json", exclude_none=False)


def events_json_schema() -> dict[str, Any]:
    schema = EVENT_ADAPTER.json_schema(ref_template="#/$defs/{model}")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://sgw-resilience-platform/contracts/schema/events.json"
    schema["title"] = "SGW K2 event envelope"
    schema["x-schema-versions"] = dict(EVENT_SCHEMA_VERSIONS)
    schema["x-webhook-event-types"] = list(WEBHOOK_EVENT_TYPES)
    return schema
