"""K3 API models and the endpoint registry.

`ENDPOINTS` is the contract: the routers implement the routes and a route-exists test compares the
running FastAPI app with this list. `contracts/openapi.json` is generated from it (`sgw contracts`).
The `/v1` namespace is reserved for the integration API.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import ConfigDict, Field
from pydantic.json_schema import models_json_schema

from sgw.contracts.approval import BreakGlass, Envelope, EnvelopeBound
from sgw.contracts.base import Contract, Identifier, Ppm, UtcDatetime
from sgw.contracts.clocks import ClockWaterfall, DecisionCase
from sgw.contracts.eval_report import MetricRow
from sgw.contracts.events import CURRENT_SCHEMA_VERSION
from sgw.contracts.vocab import (
    ActionType,
    ApiScope,
    ApprovalDecision,
    ApprovalFunction,
    BlockReason,
    Classification,
    CommitmentState,
    CrewStatus,
    DegradedMode,
    Domain,
    EffectState,
    Effort,
    FeedMode,
    InitiatorKind,
    KillLevel,
    ModelAlias,
    Module,
    NoRegretVerdict,
    NumberKind,
    NumberLabel,
    ProposalState,
    RiskBand,
    RunMode,
    ScenarioMode,
    Tier,
    UiSeverity,
    WebhookDeliveryState,
)
from sgw.contracts.webhooks import WebhookEventV1, WebhookType
from sgw.contracts.wire import WireFrame


class ErrorDetail(Contract):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorBody(Contract):
    error: ErrorDetail


class LoginRequest(Contract):
    user_id: str
    password: str = Field(min_length=1, max_length=256)


class StepUpRequest(Contract):
    password: str = Field(min_length=1, max_length=256)


class AuthConfig(Contract):
    """Public login-page configuration: whether the demo persona picker is shown (DEMO_MODE), and the public
    demo password, present only in DEMO_MODE when every account's stored password is that public value."""

    demo_mode: bool
    demo_password: str | None = None


class Me(Contract):
    user_id: str
    display_name: str
    function: ApprovalFunction
    roles: list[str]
    regions: list[str]
    domains: list[Domain]
    step_up_valid_until: UtcDatetime | None = None
    demo_mode: bool


def _optional_on_the_wire(*names: str) -> ConfigDict:
    """Additive fields the server always sends but older clients and mocks may omit: optional in the
    generated schema and TypeScript (no `required` entry and no `default`, which openapi-typescript reads
    as present)."""

    def drop(schema: dict[str, Any]) -> None:
        schema["required"] = [r for r in schema.get("required", []) if r not in names]
        for name in names:
            schema.get("properties", {}).get(name, {}).pop("default", None)

    return ConfigDict(json_schema_extra=drop)


class Bookmark(Contract):
    name: Literal["H0-72", "H0-24", "H0", "landfall", "peak", "peak+24h", "etr"]
    scenario_time: UtcDatetime


class ScenarioPeriod(Contract):
    """The one source of truth for when the scenario happens: screens show it and AI prompts read
    `statement`, so no one compares scenario times with today's date."""

    title: str
    start_utc: UtcDatetime
    end_utc: UtcDatetime
    time_zone: str = Field(description="IANA zone every screen shows scenario times in")
    label: str = Field(description="the period in that zone, e.g. '23 Sep – 6 Oct 2024'")
    data_note: str
    statement: str = Field(
        description="one sentence for AI prompt context: the period and the never-today rule"
    )


class ScenarioMoment(Contract):
    moment_id: Identifier
    kind: Literal["advisory", "landfall", "peak", "restored", "demo"]
    label: str
    scenario_time: UtcDatetime


ScenarioPhaseName = Literal["before_landfall", "storm", "restoration", "recovery"]


class ScenarioPhase(Contract):
    """One phase of the storm on the scenario clock (`sgw.api.scenario_phase`): before landfall, storm
    (landfall to the observed outage peak), restoration (to 90 percent of the peak customers restored),
    recovery."""

    phase: ScenarioPhaseName
    label: str
    starts_utc: UtcDatetime


class ScenarioState(Contract):
    model_config = _optional_on_the_wire(
        "period", "moments", "jumps", "loads_moments", "phase", "phases", "final_advisory_utc"
    )

    scenario: str
    mode: ScenarioMode
    run_mode: RunMode
    scenario_time: UtcDatetime
    speed: Literal[0, 1, 60, 900]
    bookmarks: list[Bookmark]
    window_start: UtcDatetime
    window_end: UtcDatetime
    period: ScenarioPeriod | None = Field(default=None, description="the scenario period")
    moments: list[ScenarioMoment] = Field(
        default_factory=list, description="key moments of the storm: advisories, landfall, peak"
    )
    jumps: list[ScenarioMoment] = Field(
        default_factory=list,
        description="demo moments a clock operator may seek to (`sgw demo goto` times); the clock moves,"
        " the database does not",
    )
    loads_moments: bool = Field(
        default=False,
        description="the server can load a demo moment's full state (`POST /api/demo/goto`): DEMO_MODE"
        " with a goto connection configured",
    )
    phase: ScenarioPhaseName | None = Field(default=None, description="the phase at `scenario_time`")
    phases: list[ScenarioPhase] = Field(
        default_factory=list, description="the phase timeline; a phase starts at `starts_utc`"
    )
    final_advisory_utc: UtcDatetime | None = Field(
        default=None,
        description="issue time of the final advisory (it names no next advisory); none follows it",
    )


class DemoGotoRequest(Contract):
    bookmark: Identifier = Field(description="a demo moment id from `jumps` (`sgw demo goto` bookmark)")


class DemoGotoResult(Contract):
    bookmark: Identifier
    title: str
    scenario_time: UtcDatetime
    seconds: float = Field(description="time the template copy took")


class ScenarioLoadRequest(Contract):
    scenario: Literal["helene", "ian"] = Field(
        description="`ian` loads the Hurricane Ian 2022 exercise pack at its first moment; `helene` returns"
        " to the Helene replay at the 11 AM advisory demo moment"
    )


class ScenarioLoadResult(Contract):
    scenario: str
    title: str
    scenario_time: UtcDatetime
    seconds: float = Field(description="time the load took")


class ScenarioCommand(Contract):
    action: Literal["play", "pause", "seek", "speed", "bookmark"]
    scenario_time: UtcDatetime | None = None
    speed: Literal[0, 1, 60, 900] | None = None
    bookmark: str | None = None


class Region(Contract):
    region_id: str
    state: Literal["SC", "GA"]
    county_fips: str = Field(pattern=r"^\d{5}$")
    name: str
    bbox_e6: tuple[int, int, int, int] | None = Field(
        default=None,
        description="bounding box of the county geometry in microdegrees"
        " (min lon, min lat, max lon, max lat); null while the region has no geometry",
    )


class Asset(Contract):
    asset_id: Identifier
    domain: Domain
    kind: str
    region_id: str
    lon_e6: int
    lat_e6: int
    criticality: int | None = Field(
        default=None,
        ge=0,
        le=5,
        description="set on `getAsset` only; null in `listAssets`, because a list of assets ranked by"
        " criticality above `policy_c3_aggregation_assets` is C3",
    )
    critical_facility: bool
    customers_served: int = Field(ge=0)
    classification: Classification
    name: str | None = Field(default=None, description="display label for the map; synthetic names say so")


class Provenance(Contract):
    """Where the numbers of a read model come from: the source artefact, snapshot or table, the model or rule
    that produced them, the time they are valid for (null only for offline artefacts without a build time),
    the K10 label (S: computed on synthetic data) and, optionally, the engine's own wording of that label."""

    source: str
    model_id: str | None = None
    rule_id: str | None = None
    as_of: UtcDatetime | None
    label: NumberLabel
    detail: str | None = None


class RiskItem(Contract):
    entity_id: str
    level: Literal["county", "h3", "asset"]
    p_ppm: Ppm
    band: RiskBand
    severity: UiSeverity
    expected_impact: int = Field(ge=0)
    drivers: list[str]


class RiskResponse(Contract):
    model_config = _optional_on_the_wire("advisory_label", "provenance")

    as_of: UtcDatetime
    snapshot_id: Identifier
    items: list[RiskItem]
    advisory_label: str | None = None
    provenance: Provenance | None = None


class QuantileBand(Contract):
    valid_at: UtcDatetime
    p10: float
    p50: float
    p90: float
    p025: float | None = None
    p975: float | None = None


class ForecastResponse(Contract):
    model_config = _optional_on_the_wire("unit", "provenance")

    forecast_id: Identifier
    target: Literal["outages", "etr", "pressure", "load"]
    entity_id: str
    model_version: str
    issued_at: UtcDatetime
    series: list[QuantileBand]
    unit: str | None = None
    provenance: Provenance | None = None


class OutageItem(Contract):
    model_config = _optional_on_the_wire("provenance")

    outage_id: Identifier
    feeder_id: Identifier
    customers_out: int = Field(ge=0)
    started_at: UtcDatetime
    critical_facility_ids: list[Identifier]
    provenance: Provenance | None = None


class OutageSurge(Contract):
    """One county outage surge from the EAGLE-I CUSUM detector (G1), as known at the report's `as_of`."""

    surge_id: str = Field(pattern=r"^SRG-\d{5}-\d{6}T\d{4}$")
    fips: str = Field(pattern=r"^\d{5}$")
    county: str
    state: str
    onset_at: UtcDatetime
    detected_at: UtcDatetime
    status: Literal["active", "ended"]
    customers_out: int = Field(ge=0)
    peak_customers_out: int = Field(ge=0)
    baseline_customers_out: int = Field(ge=0)
    share_out: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_band: Literal["high", "medium", "low"]
    dq_flags: list[str]


class SurgeReport(Contract):
    """Outage surges in the footprint at `as_of` (no data after it is read); numbers label C, public data."""

    as_of: UtcDatetime
    scenario: str
    data_through: UtcDatetime
    counties_monitored: int
    counties_surging: int
    surges_total: int
    first_detected_at: UtcDatetime | None
    model_version: str
    source: str
    label: str
    truncated: bool
    surges: list[OutageSurge]


CrewTargetKind = Literal["decision", "yard"]
CrewAssignmentState = Literal["proposed", "assigned"]
CrewAction = Literal[
    "assign", "sign", "reject", "withdraw", "enroute", "onsite", "staged", "block", "unblock", "release"
]
CrewMove = Literal["enroute", "onsite", "staged", "blocked", "unblock", "release"]


class CrewAssignment(Contract):
    """A crew's open assignment: `proposed` waits for one signature of `required_function`,
    `assigned` is signed. Closed assignments (rejected, withdrawn, released) are in the audit trail only."""

    assignment_id: Identifier
    target_kind: CrewTargetKind
    target_id: Identifier
    target_label: str
    decision_proposal_id: Identifier | None = Field(
        default=None, description="latest proposal of the target decision case, for a link to its page"
    )
    state: CrewAssignmentState
    required_function: ApprovalFunction
    proposed_by: Identifier
    proposed_at: UtcDatetime
    decided_by: Identifier | None = None
    decided_at: UtcDatetime | None = None


class CrewItem(Contract):
    model_config = _optional_on_the_wire("provenance", "region_id", "assignment", "block_reason", "actions")

    crew_id: Identifier
    status: CrewStatus
    location_id: str | None
    headcount: int = Field(ge=0)
    shift_end: UtcDatetime | None
    provenance: Provenance | None = None
    region_id: Identifier | None = Field(
        default=None,
        description="county the crew reports from: its latest status, else its roster row",
    )
    assignment: CrewAssignment | None = None
    block_reason: BlockReason | None = None
    actions: list[CrewAction] = Field(
        default_factory=list, description="what the signed-in person may do with this crew now"
    )


class CrewTarget(Contract):
    """Somewhere a crew can be assigned: an open decision case or a staging yard."""

    kind: CrewTargetKind
    target_id: Identifier
    label: str
    proposal_id: Identifier | None = None


class CrewAssignRequest(Contract):
    target_kind: CrewTargetKind
    target_id: Identifier


class CrewSignRequest(Contract):
    decision: ApprovalDecision
    reason: str | None = Field(default=None, max_length=500, description="why a reject sends it back")


class CrewDispatchResult(Contract):
    crew_id: Identifier
    assignment_id: Identifier | None = None


class CrewMoveRequest(Contract):
    move: CrewMove
    block_reason: BlockReason | None = Field(default=None, description="required when move is blocked")


class CountyFan(Contract):
    """One county's peak customers-out fan for one advisory (A2 county model)."""

    model_config = _optional_on_the_wire("observed_peak")

    fips: str = Field(pattern=r"^\d{5}$")
    name: str
    customers: int = Field(ge=0)
    q0025: int = Field(ge=0)
    q0100: int = Field(ge=0)
    q0250: int = Field(ge=0)
    q0500: int = Field(ge=0)
    q0750: int = Field(ge=0)
    q0900: int = Field(ge=0)
    q0975: int = Field(ge=0)
    mean: int = Field(ge=0)
    observed_peak: int | None = Field(
        default=None, ge=0, description="the county's highest customers out in the outage feed so far"
    )


class ObservedOutages(Contract):
    """The outage feed at the scenario clock for the forecast-vs-actual view."""

    as_of: UtcDatetime
    customers_out_now: int = Field(ge=0)
    peak_customers_out: int = Field(ge=0)
    peak_at_utc: UtcDatetime


class CountyOutage(Contract):
    fips: str = Field(pattern=r"^\d{5}$")
    customers_out: int = Field(gt=0)


class CountyOutagesNow(Contract):
    """Customers out per county in the outage feed at the scenario clock: the hour and source of the Briefing
    and Forecast totals. A county the feed does not list at that hour has no report."""

    as_of: UtcDatetime | None = Field(description="the feed hour read, null before the feed starts")
    customers_out_now: int = Field(ge=0)
    counties: list[CountyOutage]


class ActionShare(Contract):
    """Share of ensemble members under which a no-regret action is needed, and the rule that says so."""

    action_id: Identifier
    label: str
    decision_case_ids: list[Identifier]
    share_ppm: Ppm
    members_needed: int = Field(ge=0)
    members: int = Field(ge=0)
    rule: str


class CountyForecast(Contract):
    model_config = _optional_on_the_wire("observed")

    advisory_label: str
    issued_utc: UtcDatetime
    next_advisory_utc: UtcDatetime | None
    model_version: str
    members: int = Field(ge=0)
    trained_on: list[str]
    counties: list[CountyFan]
    actions: list[ActionShare]
    provenance: Provenance
    observed: ObservedOutages | None = Field(
        default=None, description="actual outages by the scenario time, for forecast vs actual"
    )


class PlanDiffCounty(Contract):
    fips: str = Field(pattern=r"^\d{5}$")
    name: str
    p50_out: tuple[int, int]
    p90_out: tuple[int, int]
    p_ppm: tuple[int, int]
    band: tuple[RiskBand, RiskBand]


class PlanDiffAsset(Contract):
    section_id: Identifier
    p_ppm: tuple[int, int]
    band: tuple[RiskBand, RiskBand]
    expected_impact: tuple[int, int]


class PlanDiffAction(Contract):
    model_config = _optional_on_the_wire("proposal_id", "timing")

    action_id: Identifier
    label: str
    decision_case_ids: list[Identifier]
    share_ppm: tuple[int | None, int]
    crossed_act_now_threshold: bool
    rule: str
    proposal_id: Identifier | None = Field(
        default=None,
        description="the open decision of the action's case, as listed on Decisions; null when none is open",
    )
    timing: NoRegretVerdict | None = Field(
        default=None,
        description="the Timing Decisions shows for the action's case (`DecisionCase.timing` at the"
        " scenario clock); null when the case is not stored",
    )


class PlanDiff(Contract):
    """What changed in the risk picture and the no-regret shares from one advisory to the next."""

    scenario: str
    from_advisory: str
    to_advisory: str
    footprint_mean_out: tuple[int, int]
    footprint_p90_out_sum: tuple[int, int]
    asset_band_changes: int = Field(ge=0)
    act_now_threshold_ppm: Ppm
    act_now_policy_key: str
    counties: list[PlanDiffCounty]
    assets: list[PlanDiffAsset]
    actions: list[PlanDiffAction]
    provenance: Provenance


class CrewPlanYard(Contract):
    home_groups: int = Field(ge=0)
    own_groups: int = Field(ge=0)
    mutual_aid_groups: int = Field(ge=0)
    persons: int = Field(ge=0)


class CrewPlanOutcome(Contract):
    n: int = Field(ge=0)
    expected_customer_hours: float
    p90_customer_hours: float
    cvar90_customer_hours: float | None = None
    expected_idle_early_mutual_aid_persons: float
    expected_late_mutual_aid_persons: float


class CrewPlanCost(Contract):
    total_mutual_aid_usd: float
    total_mutual_aid_person_days: float
    usd_per_customer_hour_avoided_vs_p50: float | None = None


class CrewPlanEnvelope(Contract):
    pct: int
    bounds: dict[str, EnvelopeBound]
    rule: str
    pinned_yards: list[str]
    note: str


class CrewPlanOption(Contract):
    """The P50 plan or one SAA course of action; COAs carry their T3 parameters and envelope bounds."""

    plan_id: str
    title: str
    trade_off: str
    risk: str
    early_mutual_aid_groups: int = Field(ge=0)
    early_mutual_aid_persons: int = Field(ge=0)
    own_groups_staged: int = Field(ge=0)
    committed_early_mutual_aid_usd_per_day: float
    expected_cost: CrewPlanCost
    yards: dict[str, CrewPlanYard]
    out_of_sample: CrewPlanOutcome
    synthetic_truth_customer_hours: float
    observed_scale_stress_customer_hours: float
    params: dict[str, int] | None = None
    envelope: CrewPlanEnvelope | None = None
    resource_request_id: str | None = None


class ValueInterval(Contract):
    value: float
    ci_low: float
    ci_high: float
    n: int = Field(ge=0)
    share_scenarios_better: float | None = None


class CrewPlanVss(Contract):
    ev: ValueInterval
    p50: ValueInterval


class CrewPlanEvpi(Contract):
    in_sample: float
    out_of_sample: float
    out_of_sample_n: int = Field(ge=0)


class CrewPlanSize(Contract):
    yards: int = Field(ge=0)
    clusters: int = Field(ge=0)
    scenarios: int = Field(ge=0)
    out_of_sample: int = Field(ge=0)


class CrewPlanCrews(Contract):
    own_groups: int = Field(ge=0)
    own_group_persons: int = Field(ge=0)
    mutual_aid_group_persons: int = Field(ge=0)


class CrewPlanBandCheck(Contract):
    synthetic_truth_requirement_over_p50: float
    inside_planning_band: bool
    note: str | None = None


class CrewPlanScaleBand(Contract):
    k_low: float
    k_high: float
    observed_scale_stress_k: float


class CrewPlanStagingRules(Contract):
    home_share_min: float
    site_cap_persons: int
    label: str


class CrewPlanDocument(Contract):
    """The latest crew pre-positioning plan published at or before scenario time: the P50 plan
    beside the courses of action, VSS and EVPI. The optimiser never recommends (T3 approvers decide)."""

    snapshot_id: Identifier
    engine_version: str
    scenario: str
    advisory: str
    issued_utc: UtcDatetime
    landfall_utc: UtcDatetime
    objective: str
    size: CrewPlanSize
    crews: CrewPlanCrews
    planning_band_check: CrewPlanBandCheck
    forecast_scale_band: CrewPlanScaleBand
    staging_rules: CrewPlanStagingRules
    vss: CrewPlanVss
    evpi: CrewPlanEvpi
    plans: list[CrewPlanOption]
    recommendation: None = None
    recommendation_note: str
    provenance: Provenance


class HazardAdvisory(Contract):
    advisory_label: str
    issued_utc: UtcDatetime
    next_advisory_utc: UtcDatetime | None


class HazardCone(Contract):
    """NHC cone table: two-thirds error radius (n mi) at each forecast lead (h)."""

    lead_h: list[float]
    radius_nmi: list[float]


class HazardAdvisoryDetail(HazardAdvisory):
    """The official forecast of one advisory (A1): analysis fixes up to its issue `[time_utc, lat, lon,
    vmax_kt]`, official fixes `[lead_h, lat, lon, vmax_kt]`, the cone table and the official peak gust per
    county (m/s)."""

    forecast_id: str | None
    analysis_track: list[tuple[str, float, float, float]]
    official_track: list[tuple[float, float, float, float]]
    cone: HazardCone
    county_peak_gust_ms: dict[str, float]
    provenance: Provenance


FloodCategory = Literal["below", "minor", "moderate", "major"]
WarningKind = Literal["hurricane", "tropical_storm", "flood", "flash_flood", "tornado"]


class GaugeObserved(Contract):
    """A USGS river gauge with NWS flood stages: the highest stage observed from 25 Sep 2024 up to the view
    time (`peak_ft`, null before the first report) and its flood category; nothing after the view time."""

    gauge_id: str
    nws_id: str
    name: str
    state: str
    county: str
    lon: float
    lat: float
    flood_ft: float
    moderate_ft: float | None
    major_ft: float | None
    peak_ft: float | None
    peak_utc: UtcDatetime | None
    category: FloodCategory


class WindStationObserved(Contract):
    """An ASOS airport station: the highest gust observed from 25 Sep 2024 up to the view time, the
    direction the wind blew from at that report (degrees, null when not reported) and the start of a
    silence still running at the view time (`silent_since_utc`, more than 60 min without a report)."""

    station: str
    name: str
    lon: float
    lat: float
    gust_mph: int | None
    from_deg: int | None
    gust_utc: UtcDatetime | None
    silent_since_utc: UtcDatetime | None


class WarningArea(Contract):
    """An NWS warning in force at the view time (IEM VTEC archive), clipped to the service area; `geometry`
    is a GeoJSON MultiPolygon in degrees."""

    warning_id: str
    kind: WarningKind
    office: str
    issued_utc: UtcDatetime
    expires_utc: UtcDatetime
    geometry: dict[str, Any]


class ObservedHazard(Contract):
    """Real observations of Helene at a view time (never after the scenario clock): river gauges, airport
    wind and NWS warnings. Public-domain sources listed in `sources`."""

    as_of: UtcDatetime
    gauges: list[GaugeObserved]
    stations: list[WindStationObserved]
    warnings: list[WarningArea]
    sources: list[str]


class DisasterDeclaration(Contract):
    declaration_id: str
    state: str
    title: str
    declared_on: str
    incident_begin: str
    incident_end: str | None
    programs: list[str]
    counties_total: int = Field(ge=0)
    footprint_counties: list[str]


class StormEventCount(Contract):
    event_type: str
    count: int = Field(ge=0)


class StormEventItem(Contract):
    event_id: int
    event_type: str
    county: str
    state: str
    begin_utc: UtcDatetime
    deaths: int = Field(ge=0)
    injuries: int = Field(ge=0)
    damage_usd: int = Field(ge=0)
    url: str


class OfficialRecord(Contract):
    """What happened, from the official records (After-action): FEMA disaster declarations made by the
    scenario time with their counties in the service area, and NCEI Storm Events in the service area
    that began by then (counts by type, totals and the most severe events with links to their NCEI
    pages). The records were published later; they are filtered by the time each declaration or event
    happened."""

    as_of: UtcDatetime
    declarations: list[DisasterDeclaration]
    events_total: int = Field(ge=0)
    events_by_type: list[StormEventCount]
    deaths: int = Field(ge=0)
    injuries: int = Field(ge=0)
    damage_usd: int = Field(ge=0)
    top_events: list[StormEventItem]
    attribution: list[str]


class WhatIfCell(Contract):
    customer_hours: float
    customers_affected: int = Field(ge=0)
    delta_customer_hours_pct: float
    hours_peak_to_90pct: float | None
    peak_customers_out: int = Field(ge=0)
    peak_utc: str | None = None
    levers: dict[str, float]


class WhatIfScenario(WhatIfCell):
    id: str
    title: str


class WhatIfGrid(Contract):
    """The precomputed what-if grid (W10, T0, no side effects): baseline and named scenarios."""

    scenario: str
    label: str
    mode: str
    tier: Tier
    metric_notes: dict[str, str]
    levers: dict[str, list[float]]
    baseline: WhatIfCell
    scenarios: list[WhatIfScenario]
    provenance: Provenance


class DamageCase(Contract):
    case_id: str
    case_rank: int = Field(ge=1)
    case_score: float
    damage_state: Literal["slight", "moderate", "extensive", "complete"]
    tier: Literal["structural", "slight"]
    photo_ids: list[str]
    photo_ranks: list[int]
    section_id: str
    status: str


class DamagePhoto(Contract):
    image_id: str
    rank: int = Field(ge=1)
    triage_score: float
    tier: Literal["structural", "slight"] | None
    signals: list[str]
    suggested_actions: list[str]
    human_only: list[str]
    seeded_case_id: str | None
    no_damage_control: bool
    section_id: str | None
    source_url: str
    status: str
    thumb_url: str | None


class DamageLabelScore(Contract):
    label: str
    score: float = Field(ge=0, le=1)


class DamagePhotoDetail(Contract):
    """One queued photo for the preview: the model's scores per label (highest first), the served image
    (`full_size` false means only the 240 px thumbnail is on this machine) and the dataset licence."""

    image_id: str
    rank: int = Field(ge=1)
    triage_score: float
    signals: list[str]
    labels: list[DamageLabelScore]
    suggested_actions: list[str]
    human_only: list[str]
    seeded_case_id: str | None
    status: str
    image_url: str
    full_size: bool
    dataset: str
    licence: str
    model_id: str


class DamageSeededOrder(Contract):
    control_group_max_score: float
    control_groups: int
    ladder_discordant_pairs: int
    ladder_pairs: int
    structural_min_score: float
    structural_tier: str
    tier_violations: int
    structural_above_all_control_groups: bool


class DamageQueue(Contract):
    """CV damage-triage review queue: photos ordered by triage score, seeded damage cases with their
    tier. A prioritisation aid: a reviewer confirms or rejects every photo."""

    cases: list[DamageCase]
    rows: list[DamagePhoto]
    total_photos: int = Field(ge=0)
    honest_miss: str
    imagery_note: str
    review_note: str
    model_id: str
    model_revision: str
    policy_version: str
    seeded_order: DamageSeededOrder
    provenance: Provenance


class WaterZone(Contract):
    model_config = _optional_on_the_wire("onsite_generator_id", "generator_state")

    zone_id: Identifier
    pump_station_id: Identifier
    pressure_psi_x10: int = Field(description="pressure in tenths of psi")
    floor_psi_x10: int
    critical_facility_ids: list[Identifier]
    on_backup_power: bool
    onsite_generator_id: Identifier | None = Field(
        default=None,
        description="the station's own standby generator; null when it has none and power loss needs the"
        " portable unit",
    )
    generator_state: str | None = Field(
        default=None,
        description="latest reported state of the generator serving the station at the scenario time"
        " (standby, running, failed_run, out_of_fuel, demobilised); null without a report",
    )


class AnomalyItem(Contract):
    anomaly_id: Identifier
    entity_id: Identifier
    detected_at: UtcDatetime
    score_ppm: Ppm
    anomaly_class: str
    status: Literal["open", "acknowledged", "dismissed"]


class FeedHealthItem(Contract):
    model_config = _optional_on_the_wire("display_name", "measured_by", "status")

    source_id: Identifier
    feed_mode: FeedMode
    ingest_lag_s: int | None
    product_age_s: int | None
    freshness_limit_s: int
    stale: bool
    display_name: str | None = Field(
        default=None, description="plain source name from `sgw.common.sources`; the id is for tooltips"
    )
    measured_by: Literal["age", "delay"] | None = Field(
        default=None,
        description="what `stale` compares with the limit at the replay clock: `age` = product age, for"
        " feeds that report on a schedule; `delay` = ingest lag of the newest data, for feeds that report on"
        " change; null when read from the K1 view",
    )
    status: Literal["on_time", "late", "no_data", "quiet"] | None = Field(
        default=None,
        description="the one status shown: `no_data` when nothing was delivered by the scenario time"
        " (then `stale` is false but the feed is not on time), `quiet` instead for a feed that reports"
        " only on change (not late and not missing, nothing has changed yet), else `late` or"
        " `on_time` as `stale` says",
    )


class ThreadCreate(Contract):
    title: str | None = None
    module: Module


class Thread(Contract):
    thread_id: Identifier
    created_at: UtcDatetime
    module: Module


class RunCreate(Contract):
    graph: Literal["assess", "water_continuity", "etr", "sitrep", "after_action", "copilot"]
    input: dict[str, Any]
    run_mode: RunMode = RunMode.REPLAY


class RunAccepted(Contract):
    run_id: Identifier
    thread_id: Identifier
    events_url: str


AnswerReason = Literal[
    "llm_unavailable", "model_not_in_documents", "out_of_scope", "step_cap", "checks_failed"
]


class MessageCitation(Contract):
    """One checked procedure citation of a copilot answer (the `Sources:` block of `text`, structured)."""

    model_config = _optional_on_the_wire("title")

    n: int = Field(ge=1)
    citation_id: str
    doc_id: str
    version: str
    title: str | None = None
    section: str
    pages: str
    cited_text: str
    unverified: bool = False


class MessageToolCall(Contract):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: str


class MessageReference(Contract):
    """An id the answer names, typed so the reader can open it (built by code from this run's evidence)."""

    kind: Literal[
        "decision",
        "asset",
        "county",
        "zone",
        "advisory",
        "crew",
        "yard",
        "readiness",
        "clause",
        "photo",
        "surge",
        "gauge",
        "check",
    ]
    id: str
    label: str


LinkKind = Literal[
    "page",
    "decision",
    "asset",
    "zone",
    "crew",
    "yard",
    "forecast",
    "photo",
    "readiness",
    "after_action",
    "notice",
    "help",
]


class MessageLink(Contract):
    """A deep link the answer offers into the platform: built by code from the platform map
    (`sgw.agent.copilot.platform_map`), only to pages the signed-in role can open; the model never writes
    one."""

    kind: LinkKind
    label: str = Field(
        description="plain words for the button, e.g. 'Water page', 'Cedarfall pump station on the map'"
    )
    href: str = Field(
        description="in-app path with query, always starting with '/', e.g. '/water?zone=WZ-PS17-CEDARFALL'"
    )
    page: str = Field(
        description="the module key of the target page (decisions, map, forecast, crews, water, ask,"
        " brief, after_action, health, readiness, admin, notifications, help)"
    )


class MessagePhoto(Contract):
    """A damage or flood photo the answer shows inline, from the photo queue the answer read."""

    photo_id: str
    thumb_url: str = Field(description="API path of the 240 px thumbnail, '/api/damage/thumbs/<id>'")
    href: str = Field(description="in-app link to the photo detail, '/crews?photo=<id>'")
    caption: str
    provenance: str = Field(description="where the image comes from and its licence, in plain words")


RefusalKind = Literal["unrelated", "write_action", "injection"]


class Message(Contract):
    model_config = _optional_on_the_wire(
        "run_id",
        "path",
        "reason",
        "citations",
        "tool_calls",
        "references",
        "links",
        "photos",
        "suggestions",
        "refusal",
    )

    message_id: Identifier
    role: Literal["user", "assistant", "system"]
    text: str
    created_at: UtcDatetime
    evidence_ids: list[str] = Field(default_factory=list)
    run_id: str | None = Field(default=None, description="the run that produced the message")
    path: Literal["llm", "m2", "not_in_documents", "guide"] | None = Field(
        default=None,
        description="assistant only: llm (checked model text), m2 (evidence template, no model text),"
        " not_in_documents (abstained), guide (plain text written by code from the platform map: where to"
        " find something, what a term or screen means, or a helpful refusal)",
    )
    reason: AnswerReason | None = Field(
        default=None,
        description="assistant only, why the answer is not model text: llm_unavailable (gateway, replay"
        " without a recording, kill switch, refusal), model_not_in_documents, out_of_scope, step_cap,"
        " checks_failed; null for a checked model answer",
    )
    citations: list[MessageCitation] = Field(default_factory=list)
    tool_calls: list[MessageToolCall] = Field(default_factory=list)
    references: list[MessageReference] = Field(
        default_factory=list,
        description="assistant only: the decisions, assets, places, advisories and clauses the text names,"
        " in order of first mention; `id` is the target id, `label` the plain name",
    )
    links: list[MessageLink] = Field(
        default_factory=list,
        description="assistant only: at most four deep links into the platform, role-filtered, most"
        " relevant first",
    )
    photos: list[MessagePhoto] = Field(
        default_factory=list, description="assistant only: at most six photos to show inline"
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="assistant only: up to three questions the user can ask next (always three on a refusal)",
    )
    did_you_mean: list[str] = Field(
        default_factory=list,
        description="assistant only: two or three concrete readings of an unclear request, or of"
        " something the platform does not have, each a full question the user can send as is",
    )
    refusal: RefusalKind | None = Field(
        default=None,
        description="assistant only: set when Ask declined the request (unrelated topic, a request to"
        " change something, or instruction-like text); the text then says what Ask can do",
    )


class ThreadRunStep(Contract):
    node: str
    status: Literal["done", "running"]
    at: UtcDatetime | None


class ThreadRun(Contract):
    """One run of a thread for the Ask "Runs" tab, newest first; C1 (question, tools and graph steps, no
    model text)."""

    run_id: str
    graph: str
    status: Literal["running", "paused", "done", "error", "cancelled"]
    started_at: UtcDatetime
    ended_at: UtcDatetime | None
    question: str | None
    path: Literal["llm", "m2", "not_in_documents", "guide"] | None
    reason: AnswerReason | None
    tool_calls: list[MessageToolCall]
    steps: list[ThreadRunStep]
    feedback: Literal["up", "down"] | None = None


class RunFeedback(Contract):
    model_config = _optional_on_the_wire("note")

    rating: Literal["up", "down"]
    note: str | None = Field(default=None, max_length=2000)


class Approver(Contract):
    approver_id: str
    function: ApprovalFunction
    decision: ApprovalDecision
    at: UtcDatetime


class Proposer(Contract):
    """Who proposed: a seeded user, or a system initiator (`system:rule:<id>`, `system:optimiser`) whose
    function is null. Agent proposals carry the requesting user."""

    user_id: str
    display_name: str
    function: ApprovalFunction | None
    initiator_kind: InitiatorKind


class ClockShift(Contract):
    """How the latest advisory moved this case's effective decide-by (server rule,
    `sgw.models.clocks.story`): negative minutes mean earlier."""

    advisory_label: str
    previous_advisory_label: str
    previous_effective_decide_by_utc: UtcDatetime
    shift_min: int


class VoidedApproval(Contract):
    """A signature a later material version voided (version rule); kept so the card can show it."""

    approver_id: str
    function: ApprovalFunction
    decision: ApprovalDecision
    at: UtcDatetime
    proposal_version: int = Field(ge=1)
    voided_by_version: int | None
    voided_at: UtcDatetime
    reason: str | None = Field(description="the reason recorded for the version that voided it")


class EvidenceRecord(Contract):
    """One evidence id of a decision card, resolved in the bundle of the run that made the proposal."""

    id: str
    recorded: bool = Field(description="false when the proposal was not made by an agent run with a bundle")
    kind: str | None = None
    title: str | None = Field(default=None, description="the item label; null when withheld or not recorded")
    source: str | None = Field(default=None, description="the item citation; null when withheld")
    as_of_utc: UtcDatetime | None = None
    model_version: str | None = None
    classification: Classification | None = None
    trust: str | None = None
    withheld: bool = False
    run_id: str | None = None
    graph: str | None = None


class ProposalSummary(Contract):
    model_config = _optional_on_the_wire("clock_shift", "outcome", "decided_at_utc")

    proposal_id: Identifier
    decision_case_id: Identifier
    action_type: ActionType
    title: str
    tier: Tier
    state: ProposalState
    proposal_version: int = Field(ge=1)
    action_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decide_by_utc: UtcDatetime
    effective_decide_by_utc: UtcDatetime
    on_critical_path: bool
    functions_required: list[ApprovalFunction]
    approvals: list[Approver]
    expires_at: UtcDatetime | None
    severity: UiSeverity = Field(
        description="queue severity on the scenario clock (server rule, `sgw.approval.severity`);"
        " the UI never derives it"
    )
    proposed_by: Proposer
    owner_function: ApprovalFunction | None = Field(
        description="the function that owns the decision: the proposer's function when a person proposed,"
        " else the first required approval function; null for system proposals without approvers"
    )
    clock_shift: ClockShift | None = Field(
        default=None,
        description="set when the advisory in force moved the effective decide-by against the previous"
        " advisory; the UI shows it as 'Earlier by ..., was ...' and never infers it",
    )
    outcome: Literal["on_time", "late", "missed"] | None = Field(
        default=None,
        description="closed decisions only (server rule, `sgw.approval.outcome`): on_time or late against the"
        " effective decide-by, timed by the first authority record on the scenario clock; missed when it"
        " expired unsigned; null while open, for drafts, sent back or withdrawn",
    )
    decided_at_utc: UtcDatetime | None = Field(
        default=None,
        description="scenario time of the first authority record (execution token or break-glass)",
    )


class MissedDecisionCase(Contract):
    """A decision whose deadline passed with no proposal: missed, as After-action counts it; Decisions >
    Closed lists it beside the closed proposals."""

    decision_case_id: Identifier
    title: str
    domain: Domain
    effective_decide_by_utc: UtcDatetime


class ProposalCard(ProposalSummary):
    model_config = _optional_on_the_wire(
        "clock_shift", "voided_approvals", "revision_reason", "outcome", "decided_at_utc"
    )

    case: DecisionCase
    params: dict[str, Any]
    target_ids: list[Identifier]
    preconditions: dict[str, bool]
    escalators: list[str]
    evidence_ids: list[str]
    rationale: str
    policy_version: str
    envelope: Envelope | None = None
    break_glass: BreakGlass | None = None
    changes_since_version: list[str] = Field(default_factory=list)
    voided_approvals: list[VoidedApproval] = Field(default_factory=list)
    revision_reason: str | None = Field(
        default=None, description="the recorded reason of the current version (null for version 1)"
    )


class ProposalCreate(Contract):
    decision_case_id: Identifier
    action_type: ActionType
    params: dict[str, int | str | bool | list[str]]
    target_ids: list[Identifier]
    evidence_ids: list[str]


class ApprovalRequest(Contract):
    decision: Literal["approve", "reject"]
    proposal_version: int = Field(ge=1)
    action_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_code: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class ApprovalResponse(Contract):
    approval_id: Identifier
    proposal_state: ProposalState
    remaining_functions: list[ApprovalFunction]


class StaleProposal(Contract):
    """412 body: what changed since the version the approver saw."""

    current_version: int
    current_action_hash: str
    changed_fields: list[str]


class BreakGlassRequest(Contract):
    proposal_version: int = Field(ge=1)
    action_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=10, max_length=2000)


class CosignTaskOut(Contract):
    """A break-glass co-sign task (PLAN section 2): the second function co-signs within 24 h; every task is
    also an after-action flag. `overdue` is judged on the scenario clock."""

    break_glass_id: int
    proposal_id: Identifier
    proposal_version: int = Field(ge=1)
    ic_id: Identifier
    reason: str
    used_at_utc: UtcDatetime
    cosign_due_utc: UtcDatetime
    functions: list[ApprovalFunction]
    cosigned_by: Identifier | None = None
    cosigned_at_utc: UtcDatetime | None = None
    overdue: bool


class WithdrawRequest(Contract):
    reason: str = Field(min_length=3, max_length=500)


class PolicyParam(Contract):
    key: str
    value: float | int | str
    unit: str
    label: NumberLabel
    kind: Literal[NumberKind.POLICY]
    chip: Literal["Assumed SGW policy"] = "Assumed SGW policy"
    source: str


ReadinessResultStatus = Literal["ready", "not_ready", "waived"]


class ReadinessResult(Contract):
    """The latest result the check's owner recorded; it stands at the pre-season review, not at the replay
    clock."""

    status: ReadinessResultStatus
    note: str
    evidence_url: str | None
    recorded_by: Identifier
    recorded_at_utc: UtcDatetime = Field(description="wall-clock time the owner recorded it")
    reviewed_at_utc: UtcDatetime = Field(description="the pre-season review the result is recorded at")


class ReadinessRecord(Contract):
    status: ReadinessResultStatus
    note: str = Field(min_length=3, max_length=300)
    evidence_url: str | None = Field(default=None, max_length=500, pattern=r"^https?://\S+$")


class ReadinessItem(Contract):
    model_config = _optional_on_the_wire("evaluated_at_utc", "result")

    item_id: Identifier
    title: str
    domain: Domain
    status: Literal["ready", "gap", "unknown", "waived"]
    owner_function: ApprovalFunction
    due_utc: UtcDatetime | None
    evaluated_at_utc: UtcDatetime | None = Field(
        default=None,
        description="the pre-season review the status and due dates are read at",
    )
    result: ReadinessResult | None = Field(
        default=None,
        description="the owner's latest recorded result; it sets `status` (not_ready is `gap`)",
    )


class HazardSource(Contract):
    """One input of a hazard library view: what it holds, the committed file it is read from, and whether its
    values are real observations (ASOS, NIFC) or synthetic SGW data built on them."""

    what: str
    source: str
    origin: Literal["real", "synthetic"]
    detail: str | None = None


class HazardAction(Contract):
    """A step the hazard model recommends, with its approval tier and the functions that would sign it (SGW
    policy, assumed). Read-only: nothing is proposed or signed from the library."""

    action_id: Identifier
    text: str
    tier: Tier
    signers: list[ApprovalFunction]
    applies_to: str
    recommended: bool
    why: str | None = None


class HeatDay(Contract):
    day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Eastern local date")
    tmax_c: float = Field(description="mean of the five stations' daily maximum temperature")
    hot: bool


class HeatUnit(Contract):
    asset_id: Identifier
    site: Identifier
    protected_load: bool
    peak_hot_spot_c: float
    peak_utc: UtcDatetime
    hours_ge_110c: float = Field(ge=0)
    hours_ge_120c: float = Field(ge=0)
    aging_equiv_days: float = Field(ge=0)
    alarm: Literal["normal", "watch", "warning", "emergency"]
    first_warning_utc: UtcDatetime | None


class HeatLineCheck(Contract):
    feeder_id: Identifier
    conductor: str
    still_air_peak_loading_pct: float
    rating_wind_peak_loading_pct: float
    line_limit_utc: UtcDatetime | None
    transformer_warning_utc: UtcDatetime | None
    line_leads_transformer_h: float


class HazardLibraryHeat(Contract):
    """July 2024 heat wave (`heat` fixture): the station-mean daily maximum against the out-of-sample
    trigger threshold, the transformer hot spots and the still-air line check, as of the trigger."""

    hazard: Literal["heat"] = "heat"
    title: str
    window_start_utc: UtcDatetime
    window_end_utc: UtcDatetime
    as_of: UtcDatetime
    trigger_rule_id: str
    threshold_c: float
    trigger_fired_utc: UtcDatetime
    stations: list[str]
    days: list[HeatDay]
    units: list[HeatUnit]
    line: HeatLineCheck
    actions: list[HazardAction]
    sources: list[HazardSource]
    provenance: Provenance


class FireWeatherHour(Contract):
    t_utc: UtcDatetime
    ffwi: float = Field(ge=0, le=100)
    rh_pct: float = Field(ge=0, le=100)
    wind_ms: float = Field(ge=0)
    red_flag: bool


class FireEpisode(Contract):
    start_utc: UtcDatetime
    end_utc: UtcDatetime
    hours: int = Field(ge=1)
    ffwi_max: float
    rh_min_pct: float


class FireAnchor(Contract):
    name: str
    acres: int = Field(ge=0)
    county_fips: str
    county: str
    discovered_utc: UtcDatetime


class CircuitRisk(Contract):
    rank: int = Field(ge=1)
    feeder_id: Identifier
    county_fips: str
    county: str
    customers: int = Field(ge=0)
    overhead_km: float = Field(ge=0)
    p_ignition_window: float = Field(ge=0, le=1)
    ratio_to_average_window: float = Field(ge=0)


class HazardLibraryWildfire(Contract):
    """March 2025 Table Rock fire weather (`tablerock` fixture): hourly Fosberg index at GSP against the
    Red Flag trigger, the ranked circuits and the protocol, as of the first trigger."""

    hazard: Literal["wildfire"] = "wildfire"
    title: str
    window_start_utc: UtcDatetime
    window_end_utc: UtcDatetime
    as_of: UtcDatetime
    trigger_rule_id: str
    ffwi_min: float
    rh_max_pct: float
    min_hours: int
    station: str
    hours: list[FireWeatherHour]
    episodes: list[FireEpisode]
    fires: list[FireAnchor]
    kbdi_max: float
    kbdi_min_trigger: float
    circuits: list[CircuitRisk]
    circuits_total: int = Field(ge=0)
    expected_ignitions_all: float = Field(ge=0)
    actions: list[HazardAction]
    sources: list[HazardSource]
    provenance: Provenance


class AuditEventOut(Contract):
    stream: str
    seq: int
    occurred_at: UtcDatetime
    actor_type: Literal["user", "system", "agent"]
    actor_id: str
    kind: str
    subject: str
    payload_hash: str
    prev_hash: str
    hash: str
    decision: str | None = Field(default=None, description="approve, reject or cosign on a signature record")
    reason: str | None = Field(default=None, description="the reason a person gave (send back, withdrawal)")


class AuditVerifyResult(Contract):
    ok: bool
    checked_to_seq: int
    first_bad_seq: int | None
    signed_head_seq: int | None
    notary: Literal["signed", "UNSIGNED"]


class PipelineRunOut(Contract):
    run_id: Identifier
    asset: str
    status: Literal["running", "success", "failed", "partial"]
    started_at: UtcDatetime
    finished_at: UtcDatetime | None
    rows_in: int
    rows_out: int
    rows_quarantined: int
    error: str | None


class DqCheckOut(Contract):
    check_id: Identifier
    asset: str
    name: str
    severity: Literal["warn", "error"]
    passed: bool
    observed: str
    checked_at: UtcDatetime


class ModelCard(Contract):
    name: str
    version: str
    alias: str | None
    data_hash: str
    eval_report: str | None


class ControlState(Contract):
    kill_level: KillLevel
    degraded_mode: DegradedMode
    run_mode: RunMode
    updated_by: list[str]
    updated_at: UtcDatetime


class KillRequest(Contract):
    kill_level: KillLevel
    reason: str = Field(min_length=3)


class ModeRequest(Contract):
    degraded_mode: DegradedMode
    reason: str = Field(min_length=3)


class Health(Contract):
    status: Literal["ok", "degraded", "down"]
    checks: dict[str, str]


class DecisionV1(Contract):
    decision_case_id: Identifier
    title: str
    tier: Tier
    state: ProposalState
    decide_by_utc: UtcDatetime
    effective_decide_by_utc: UtcDatetime
    on_critical_path: bool
    schema_version: int = CURRENT_SCHEMA_VERSION


class CommitmentMilestoneV1(Contract):
    name: str
    due_utc: UtcDatetime
    met_utc: UtcDatetime | None


class CommitmentV1(Contract):
    commitment_id: Identifier
    decision_case_id: Identifier
    state: CommitmentState
    promised_by_utc: UtcDatetime
    projected_utc: UtcDatetime | None
    milestones: list[CommitmentMilestoneV1]


class CommitmentSummary(Contract):
    """K3 `/api/commitments` row: what an approved decision promised and where it stands."""

    commitment_id: Identifier
    decision_case_id: Identifier
    proposal_id: Identifier
    title: str
    state: CommitmentState
    promised_by_utc: UtcDatetime
    projected_utc: UtcDatetime | None
    drift_min: int | None = Field(description="projected minus promised, whole minutes rounded up, >= 0")
    milestones_met: int
    milestones_total: int


class CommitmentMilestone(Contract):
    seq: int
    name: str
    due_utc: UtcDatetime
    met_utc: UtcDatetime | None
    lead_key: str | None
    remaining_min: int | None = Field(description="minutes of the chain still to run after this milestone")
    signal_type: str | None = Field(description="ledger signal that marks the milestone met")


class CommitmentDriftEntry(Contract):
    seq: int
    detected_at: UtcDatetime
    state: CommitmentState
    reason: Literal["milestone_late", "input_changed"]
    milestone_seq: int | None
    promised_by_utc: UtcDatetime
    projected_utc: UtcDatetime
    drift_min: int
    tolerance_min: int
    reopened: bool
    proposal_version: int | None
    note: str


class CommitmentDetail(CommitmentSummary):
    milestones: list[CommitmentMilestone]
    drift_log: list[CommitmentDriftEntry]


class WebhookSubscriptionCreate(Contract):
    url: str = Field(pattern=r"^https://", max_length=2048)
    event_types: list[WebhookType] = Field(min_length=1)


class WebhookSubscriptionV1(Contract):
    subscription_id: Identifier
    url: str
    event_types: list[WebhookType]
    created_at: UtcDatetime
    active: bool
    secret_hint: str = Field(description="last 4 characters only; the secret is shown once at creation")


class WebhookDeliveryV1(Contract):
    delivery_id: Identifier
    subscription_id: Identifier
    event_id: Identifier
    state: WebhookDeliveryState
    attempts: int
    last_status: int | None


class ApiTokenCreate(Contract):
    name: str = Field(min_length=3, max_length=80)
    scopes: list[ApiScope] = Field(min_length=1)
    expires_at: UtcDatetime


class WebhookSecretRotated(Contract):
    subscription_id: Identifier
    secret: str = Field(description="shown once; the previous secret keeps signing until previous_retires_at")
    secret_hint: str
    previous_retires_at: UtcDatetime


class ApiTokenOut(Contract):
    token_id: Identifier
    name: str
    scopes: list[ApiScope]
    created_by: Identifier
    created_at: UtcDatetime
    expires_at: UtcDatetime
    revoked_at: UtcDatetime | None
    last_used_at: UtcDatetime | None


class ApiTokenCreated(Contract):
    token_id: Identifier
    token: str = Field(description="shown once; stored only as SHA-256")
    scopes: list[ApiScope]
    expires_at: UtcDatetime


class EffectOut(Contract):
    effect_id: Identifier
    proposal_id: Identifier
    channel: str
    state: EffectState


class BwaAssessment(Contract):
    advisory: str
    issued_utc: UtcDatetime
    power_loss_p_ppm: Ppm
    breach_given_loss_p_ppm: Ppm
    breach_p_ppm: Ppm
    at_or_above_policy: bool


class HookupSensitivity(Contract):
    hookup_lag_min: int = Field(ge=0)
    breach_p_ppm: Ppm


NoticeStage = Literal["due", "issued", "samples", "lift_decision", "lifted"]


class BwaAdvisory(Contract):
    model_config = _optional_on_the_wire(
        "stage", "clean_samples", "samples_needed", "lift_proposal_id", "lift_decision_case_id"
    )

    advisory_id: Identifier
    state: Literal["SC", "GA"]
    zone_id: Identifier
    station_id: Identifier
    kind: Literal["pre_landfall", "pressure_loss"]
    clause_ids: list[str]
    policy_key: str
    policy_value_ppm: Ppm
    assessments: list[BwaAssessment] = Field(description="advisories issued at or before the scenario time")
    sensitivity: list[HookupSensitivity]
    due_utc: UtcDatetime | None
    status: Literal["not_due", "due", "proposed", "issued", "lifted"]
    proposal_id: Identifier | None
    decision_case_id: Identifier | None
    classification: Classification
    provenance: Provenance
    stage: NoticeStage | None = Field(
        default=None,
        description="where the zone's notice stands: due (not signed yet), issued, samples (clean samples"
        " coming in), lift_decision (lift waiting for sign-off), lifted; null when no notice is due",
    )
    clean_samples: int | None = Field(
        default=None, ge=0, description="clean total coliform results reported for the zone (LIMS) by now"
    )
    samples_needed: int | None = Field(
        default=None, ge=0, description="clean sample sets the lift rule needs (`bwa.lift_check`)"
    )
    lift_proposal_id: Identifier | None = None
    lift_decision_case_id: Identifier | None = None


class BwaRegister(Contract):
    as_of: UtcDatetime
    advisories: list[BwaAdvisory]
    forecasts_withheld: bool = Field(
        default=False,
        description="true for readers outside the water domain: notice status and due times are shown, the C2"
        " zone forecasts (`assessments`, `sensitivity`) are emptied",
    )


class SopSection(Contract):
    doc_id: str
    section: str


class BwaClause(Contract):
    clause_id: str
    state: Literal["SC", "GA"]
    rule_id: str
    summary: str
    citation: str
    sop: SopSection | None
    label: NumberLabel


class BwaRules(Contract):
    version: str
    source: str
    clauses: list[BwaClause]


class ApprovalRight(Contract):
    action_type: ActionType
    tier: Tier
    role: Literal["approver", "escalation_approver"]


class UserApprovalRights(Contract):
    user_id: str
    function: ApprovalFunction
    can_approve: bool
    break_glass_eligible: bool
    may_approve: list[ApprovalRight]


class AiNodeEval(Contract):
    report: str
    metric: str
    value_ppm: Ppm
    passed: bool


class AiNodeConfig(Contract):
    node: str
    model: ModelAlias
    effort: Effort
    max_tokens: int
    prompt_version: str
    class_ceiling: Classification
    citations: bool
    routes: list[str]
    allowed_tools: list[str] = Field(description="custom tools the node may call (K5); empty for text nodes")
    tool_types: list[str]
    eval_result: AiNodeEval | None


class AiConfig(Contract):
    version: int
    source: str
    nodes: list[AiNodeConfig]


class AuditChainCheck(Contract):
    ok: bool
    checked_to_seq: int
    first_bad_seq: int | None
    signed_head_seq: int | None
    trusted_to_seq: int = Field(description="records after this sequence are left out of the review")
    problems: list[str]


class ClockOutcomeRow(Contract):
    decision_case_id: str
    step: str
    title: str
    effective_decide_by: UtcDatetime
    decided_at: UtcDatetime | None
    decided_by: Literal["approval", "break_glass"] | None
    proposal_id: str | None
    outcome: Literal["met", "missed", "open", "unverifiable"]
    margin_min: int | None = Field(description="decide-by minus decision time; negative when late")
    proposed: bool = Field(True, description="false when the decision never got a proposal")


class BreakGlassUseRow(Contract):
    break_glass_id: int
    proposal_id: str
    title: str | None
    ic_id: str
    tier: str
    reason: str
    reason_code: str | None = Field(description="reason code of the co-sign approval (late_cosign) if any")
    used_at: UtcDatetime
    cosign_due: UtcDatetime
    cosigned_by: str | None
    cosigned_at: UtcDatetime | None
    status: Literal[
        "cosigned_on_time", "cosigned_late", "overdue_unsigned", "awaiting_cosign", "unverifiable"
    ]
    table_agrees: bool = Field(description="the break_glass table agrees with the audit chain")


class AuditTimelineEntry(Contract):
    seq: int
    occurred_at: UtcDatetime
    kind: str
    actor_id: str
    subject: str


class EtrScoreRow(Contract):
    estimate_id: str
    scope: str
    region_id: str
    as_of_utc: UtcDatetime
    actual_utc: UtcDatetime | None
    actual_label: str
    p50_error_h: float | None
    abs_error_h: float | None
    analog_abs_error_h: float | None
    in_p25_p75: bool | None
    in_p10_p90: bool | None


class EtrScorecard(Contract):
    name: str
    label: NumberLabel
    actual_label: str
    source: str = Field(
        description="`snapshot` (ETR publication in the database), the artefact path, or `none`"
    )
    as_of: UtcDatetime | None
    resolved: int = Field(description="estimates whose actual time is at or before the scenario time")
    total: int
    resolved_label: str = Field(description="`<resolved> of <total> resolved`")
    metrics: list[MetricRow] = Field(description="computed over the resolved estimates only")
    estimates: list[EtrScoreRow] = Field(
        description="actual, errors and in-band flags are null until the actual time has passed"
    )


class InterruptionRow(Contract):
    area_id: str
    area_kind: str
    county_code: str | None
    started_at: UtcDatetime
    restored_at: UtcDatetime
    duration_h: float
    customers_interrupted: int
    sections: int
    max_gust_ms: float
    damage_states: dict[str, int]
    cause: str
    report_required: bool


class RegulatorReportDraft(Contract):
    citation: str
    source_note: str
    label: str
    threshold_h: float
    event_name: str
    filed: Literal[False] = False
    system: InterruptionRow
    counties: list[InterruptionRow]
    markdown: str


class AfterActionView(Contract):
    """The after-action review at the scenario time: the audit chain is verified first and only records
    up to the last trusted sequence are used; drafts only, nothing filed."""

    as_of: UtcDatetime
    usable: bool = Field(description="false when the audit chain did not verify")
    chain: AuditChainCheck
    clocks: list[ClockOutcomeRow]
    break_glass: list[BreakGlassUseRow]
    timeline: list[AuditTimelineEntry]
    scorecard: EtrScorecard
    sc_report: RegulatorReportDraft | None = Field(description="null before any SC interruption has ended")
    provenance: Provenance


class TamperDemoRequest(Contract):
    seq: int | None = Field(
        default=None, ge=1, description="the record to alter; default the latest approval"
    )


class TamperDemoResult(Contract):
    tampered_seq: int
    altered: str = Field(description="what was changed in the in-memory copy")
    result: AuditVerifyResult
    untrusted_from_seq: int | None
    problems: list[str]
    real_chain_touched: Literal[False] = False


class DeliveryCounts(Contract):
    delivered: int
    pending: int
    failed: int


class IntegrationSubscription(Contract):
    subscription_id: str
    token_id: str
    host: str = Field(description="host[:port] of the endpoint only; no path, query or credentials")
    event_types: list[WebhookType]
    state: Literal["active", "disabled"]
    disabled_reason: str | None
    created_at: UtcDatetime
    last_delivery_at: UtcDatetime | None
    counts: DeliveryCounts


class IntegrationDelivery(Contract):
    delivery_id: str
    subscription_id: str
    event_type: str
    status: Literal["delivered", "pending", "failed"]
    attempts: int
    last_status: int | None
    last_error: str | None
    created_at: UtcDatetime
    delivered_at: UtcDatetime | None


class AdminIntegrations(Contract):
    tokens: list[ApiTokenOut]
    subscriptions: list[IntegrationSubscription]
    deliveries: list[IntegrationDelivery] = Field(description="the latest 50 deliveries")


class RouteTiming(Contract):
    route: str = Field(description="route template, e.g. /api/runs/{run_id}")
    requests: int
    typical_ms: int = Field(description="median response time over the recent window")
    slow_ms: int = Field(description="95th percentile response time over the recent window")


class ApiActivity(Contract):
    requests: int = Field(description="requests handled since this API process started")
    server_errors: int = Field(description="5xx responses since this API process started")
    window: int = Field(description="how many of the latest timed requests the times are computed over")
    typical_ms: int | None = Field(description="median response time; null before the first timed request")
    slow_ms: int | None = Field(
        description="95th percentile response time; null before the first timed request"
    )
    slowest: list[RouteTiming] = Field(description="up to five routes with the highest 95th percentile")


class SystemMetricsLink(Contract):
    obs_profile_up: bool
    grafana_url: str | None = Field(description="set only while the obs profile answers")
    checked_at: UtcDatetime
    how_to_enable: str
    api: ApiActivity | None = Field(
        default=None,
        description="in-app request metrics of this API process; no obs profile needed",
    )


class AgentRunSummary(Contract):
    run_id: str
    thread_id: str
    graph: str
    graph_version: str
    user_id: str
    run_mode: RunMode
    status: Literal["running", "paused", "done", "error", "cancelled"]
    started_at: UtcDatetime
    ended_at: UtcDatetime | None
    duration_ms: int | None
    llm_calls: int
    billed_calls: int
    tokens_in: int = Field(description="input tokens incl. cache reads and writes, from llm_call")
    tokens_out: int
    cost_usd_micros: int
    nodes: list[str] = Field(description="LLM nodes called, in call order")
    models: list[str]
    tainted: bool
    classification: Classification
    trace_id: str | None
    trace_url: str | None = Field(description="MLflow trace link when the tracking UI is configured")


class AgentRunStep(Contract):
    model_config = _optional_on_the_wire("worker", "tool", "status", "args", "cache_read_tokens")

    seq: int
    kind: Literal["graph_step", "llm_call", "worker", "tool_call"]
    node: str
    at: UtcDatetime | None
    model: str | None = None
    mode: str | None = None
    decision: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd_micros: int = 0
    latency_ms: int | None = None
    worker: str | None = Field(default=None, description="copilot team: the analyst lane of the step")
    tool: str | None = Field(default=None, description="tool_call: the K5 tool name")
    status: str | None = Field(default=None, description="worker ok|error; tool_call ok|empty|refused|error")
    args: dict[str, str | int | bool] | None = Field(
        default=None, description="tool_call: at most two flat argument values (ids, C1)"
    )
    cache_read_tokens: int | None = Field(default=None, description="llm_call: the cached part of tokens_in")


class AgentRunDetail(Contract):
    run: AgentRunSummary
    steps: list[AgentRunStep]


class BriefNumber(Contract):
    key: Literal["customers_out", "critical_facilities", "water_zones_advisory", "crews_working"]
    label: str
    actual: int | None
    forecast: int | None = Field(
        description="null when no forecast exists for this number at the scenario time"
    )
    forecast_basis: str | None
    unit: str
    breakdown: dict[str, int] = Field(default_factory=dict)
    provenance: Provenance


class BriefAdvisory(Contract):
    label: str
    issued_utc: UtcDatetime
    landfall_eta_utc: UtcDatetime | None
    next_advisory_utc: UtcDatetime | None


class BriefFunctionLine(Contract):
    function: ApprovalFunction
    sentence: str


class ExecutiveBrief(Contract):
    """W7 executive Brief at the scenario time: a status word, four numbers with Forecast and Actual, the open
    T3 decisions with their clocks, one sentence per function, the last advisory and a caveat line. Every
    sentence is rendered by code from the numbers shown."""

    as_of: UtcDatetime
    status_word: Literal["Normal", "Watch", "Warning", "Emergency", "Restoring"]
    status_basis: str
    numbers: list[BriefNumber]
    open_t3: list[ProposalSummary]
    functions: list[BriefFunctionLine]
    last_advisory: BriefAdvisory | None
    caveat: str
    label: NumberLabel


class SitrepDraft(Contract):
    run_id: str
    thread_id: str
    drafted_by: str
    started_at: UtcDatetime
    as_of_utc: UtcDatetime | None
    tier: Tier | None
    path: str | None = Field(description="`llm` or the M2 `template` path of the narrative node")
    text: str | None
    slots: dict[str, str] = Field(description="every number shown, by evidence slot id")
    tainted: bool
    status: Literal["draft", "blocked", "promoted"]
    promoted_by: str | None
    promoted_at: UtcDatetime | None
    audit_seq: int | None
    classification: Classification


class Permissions(Contract):
    """What the signed-in person may do, from the same rules the write routes enforce, so the UI offers only
    controls the API accepts."""

    model_config = _optional_on_the_wire("readiness_record")

    stop_raise: bool = Field(description="raise the kill level (`setKill` upwards)")
    stop_restore: bool = Field(description="sign a restore of the kill level (one of the two functions)")
    mode_raise: bool = Field(description="raise the degraded mode (`setMode`)")
    mode_lower: bool = Field(description="lower a manual degraded mode")
    crew_dispatch: bool = Field(description="assign a crew or mark it blocked")
    pipeline_run: bool = Field(description="start a pipeline asset run (`runPipelineAsset`)")
    agent_run_cancel: bool = Field(description="cancel any running or paused agent run (`cancelAgentRun`)")
    admin: bool = Field(description="read the admin views")
    readiness_record: list[Identifier] = Field(
        default_factory=list,
        description="readiness checks whose result the person may record (`recordReadiness`, the owner)",
    )


class AgentRunCancel(Contract):
    reason: str = Field(min_length=3, max_length=300)


NotificationKind = Literal[
    "decision_waiting",
    "boil_water_due",
    "deadline_soon",
    "signature_recorded",
    "signature_voided",
    "proposal_withdrawn",
    "crew_signature_waiting",
    "crew_assignment_signed",
    "crew_assignment_rejected",
    "signature_withdrawn",
    "cosign_waiting",
    "emergency_approval",
    "restore_waiting",
    "stop_level_changed",
    "mode_changed",
    "surge_detected",
    "etr_published",
    "water_decision_open",
]


class Notification(Contract):
    """One item of the person's feed, derived from open decisions, the audit chain and the surge detector;
    `notification_id` is stable, so a read mark survives a refresh."""

    notification_id: str = Field(max_length=160)
    kind: NotificationKind
    title: str
    detail: str | None = None
    at: UtcDatetime
    href: str = Field(description="the page the item opens, an app path")
    read: bool


class NotificationFeed(Contract):
    items: list[Notification]
    unread: int = Field(ge=0)


class NotificationRead(Contract):
    """Mark items read: the listed ids, or every item in the current feed when `all` is true."""

    ids: list[str] = Field(default_factory=list, max_length=200)
    all: bool = False


class SitrepPromote(Contract):
    note: str | None = Field(default=None, max_length=280)


EtrOutcome = Literal["waiting", "past_p50", "late", "restored_early", "restored", "restored_late"]


class EtrArea(Contract):
    """One restoration-model estimate of the time to 90 percent of the peak customers out restored: the whole
    service area (`scope` global) or one operating area (the crew yard's area)."""

    model_config = _optional_on_the_wire("actual_out_now", "actual_still_out_ppm", "restored_utc", "outcome")

    estimate_id: str
    scope: Literal["global", "region"]
    region_id: str
    name: str = Field(description="`Whole service area`, or the area named after its crew yard's county")
    county: str | None = Field(description="county of the area's crew yard")
    customers_out_now: int
    peak_customers_out: int
    still_out_ppm: Ppm = Field(description="customers out now as a share of the area's peak")
    p10_utc: UtcDatetime
    p50_utc: UtcDatetime
    p90_utc: UtcDatetime
    p50_h: float = Field(description="hours from the issue time to P50")
    p90_h: float = Field(description="hours from the issue time to P90")
    range_h: float = Field(description="P10 to P90 width in hours")
    calibrated: bool
    actual_out_now: int | None = Field(
        default=None, description="customers out at the scenario clock from the outage feed"
    )
    actual_still_out_ppm: Ppm | None = Field(
        default=None, description="actual customers out now as a share of the area's observed peak"
    )
    restored_utc: UtcDatetime | None = Field(
        default=None, description="when the area was back to 90 percent restored after its peak, if by now"
    )
    outcome: EtrOutcome | None = Field(
        default=None,
        description="the estimate against actuals at the scenario clock: waiting, past_p50, late (past P90),"
        " restored_early (before P10), restored, restored_late (after P90)",
    )


class EtrPublication(Contract):
    """The latest D4 global ETR proposal (`publish_global_etr`) and, once executed, its publication."""

    proposal_id: str
    run_id: str | None
    run_status: str | None = Field(
        description="K1 status of the `etr` run that drafted it: paused (waiting to publish), done, error"
    )
    state: ProposalState
    proposed_by: str
    estimate_id: str
    p50_utc: UtcDatetime
    required_functions: list[ApprovalFunction]
    signed_functions: list[ApprovalFunction]
    created_at: UtcDatetime
    published_at: UtcDatetime | None
    published_by: str | None
    audit_seq: int | None


class EtrRevision(Contract):
    """Whether actual restoration has moved the published global ETR enough to revise it, with the
    revised time next to the published one."""

    model_config = _optional_on_the_wire("rule_name", "published_p50_utc", "revised_p50_utc")

    due: bool
    ahead_h: float = Field(
        description="hours restoration runs ahead of the published estimate (negative: behind)"
    )
    reason: str
    rule: str = Field(description="the procedure clause, shown in a tooltip")
    rule_name: str = Field(default="ETR revision rule", description="plain name of the rule")
    published_p50_utc: UtcDatetime | None = Field(
        default=None, description="the likely 90% restored time of the published ETR"
    )
    revised_p50_utc: UtcDatetime | None = Field(
        default=None,
        description="the published likely time moved by the actual pace; the time it was restored once it is",
    )


class EtrView(Contract):
    """Global and per-area ETR at the scenario time from the latest ETR publication issued by then, the
    honest coverage caveat (K17, synthetic storms) and the D4 publication state. `can_draft` and
    `can_publish` apply the approval policy's proposer list to the signed-in user."""

    model_config = _optional_on_the_wire("actual_as_of", "revision")

    as_of: UtcDatetime
    issued_at: UtcDatetime | None
    next_issue_utc: UtcDatetime | None
    target: str
    whole: EtrArea | None
    areas: list[EtrArea]
    coverage80_ppm: Ppm | None
    n_storms: int | None
    real_storm_checked: bool
    basis: str | None
    model_version: str | None
    drafting: bool = Field(description="an `etr` run of this user is still running")
    publication: EtrPublication | None
    can_draft: bool
    can_publish: bool
    provenance: Provenance
    actual_as_of: UtcDatetime | None = Field(default=None, description="outage-feed hour of the actuals")
    revision: EtrRevision | None = Field(
        default=None, description="the published global ETR against actuals; set once it is published"
    )


class AfterActionDraft(Contract):
    """A draft of the `after_action` graph (D5) read from its run state: the review summary and the
    code-formatted Markdown; never filed."""

    run_id: str
    thread_id: str
    drafted_by: str
    started_at: UtcDatetime
    as_of_utc: UtcDatetime | None = Field(description="scenario time the review covers")
    status: Literal["running", "draft", "blocked", "error"]
    path: str | None = Field(description="`llm` or the M2 template path of the summary node")
    summary: str | None
    markdown: str | None
    usable: bool | None
    classification: Classification


class Endpoint(Contract):
    method: Literal["GET", "POST", "PUT", "DELETE"]
    path: str
    operation_id: str
    tag: str
    request: str | None = None
    response: str | None = None
    response_list: bool = False
    status: int = 200
    errors: tuple[int, ...] = ()
    query: tuple[str, ...] = ()
    sse: bool = False
    description: str | None = None
    auth: Literal["session", "none", "api_token"] = "session"
    accepted: str | None = Field(
        default=None,
        description="an additional documented 202 answer with the same body (when and which header marks it)",
    )


def _e(method: str, path: str, op: str, tag: str, **kw: Any) -> Endpoint:
    return Endpoint(method=method, path=path, operation_id=op, tag=tag, **kw)  # type: ignore[arg-type]


V1_EVENTS_DOC = (
    "Server-sent events of the webhook event types the token may read. Frames: `id: v1.<epoch>.<seq>`,"
    " `event: <type>`, `data: <WebhookEventV1>`; `Last-Event-ID` resumes from the ledger; an id the"
    " server cannot honour gets one `event: resync` frame. Comment heartbeats every 10 s; a revoked or"
    " expired token ends the stream."
)

ASSETS_DOC = (
    "C0/C1 assets with a geometry, ordered by `asset_id`. `bbox` is `min_lon,min_lat,max_lon,max_lat` in"
    " degrees; `domain` a K7 domain; `region` a region id (repeatable); `limit` 1-1000 (default 500); `after`"
    ' the last `asset_id` of the previous page. A `Link: <...>; rel="next"` header marks a further page;'
    " `ETag` with `If-None-Match` answers 304, and pages may be cached privately for 60 s. `criticality` is"
    " null in the list (C3 aggregation rule); `getAsset` carries it."
)

ENDPOINTS: tuple[Endpoint, ...] = (
    _e(
        "POST",
        "/api/auth/login",
        "login",
        "auth",
        request="LoginRequest",
        response="Me",
        errors=(401,),
        auth="none",
    ),
    _e("POST", "/api/auth/logout", "logout", "auth", status=204),
    _e("POST", "/api/auth/step-up", "stepUp", "auth", request="StepUpRequest", response="Me", errors=(401,)),
    _e("GET", "/api/me", "getMe", "auth", response="Me"),
    _e(
        "GET",
        "/api/me/permissions",
        "getMyPermissions",
        "auth",
        response="Permissions",
        description="What the signed-in person may do, from the rules the write routes enforce.",
    ),
    _e(
        "GET",
        "/api/notifications",
        "listNotifications",
        "auth",
        response="NotificationFeed",
        description="The person's feed: decisions waiting on their function, deadlines within 2 h,"
        " signatures, crew sign-offs, stop-level and mode changes, outage surges and published ETRs;"
        " read state per user.",
    ),
    _e(
        "POST",
        "/api/notifications/read",
        "markNotificationsRead",
        "auth",
        request="NotificationRead",
        response="NotificationFeed",
        errors=(422,),
    ),
    _e(
        "GET",
        "/api/auth/config",
        "getAuthConfig",
        "auth",
        response="AuthConfig",
        auth="none",
        description="Public: whether the login page offers the demo persona picker. Cacheable for 60 s.",
    ),
    _e("GET", "/api/scenario", "getScenario", "scenario", response="ScenarioState"),
    _e(
        "POST",
        "/api/scenario",
        "commandScenario",
        "scenario",
        request="ScenarioCommand",
        response="ScenarioState",
    ),
    _e(
        "POST",
        "/api/demo/goto",
        "loadDemoMoment",
        "scenario",
        request="DemoGotoRequest",
        response="DemoGotoResult",
        errors=(403, 404, 409, 503),
        description="Presenter only (clock operator roles), DEMO_MODE with a goto connection: replace the"
        " database with a demo moment's saved state (`sgw demo goto`); the caller's session is kept and every"
        " client resyncs. 503 `DEMO_GOTO_UNAVAILABLE` when the server cannot load moments.",
    ),
    _e(
        "POST",
        "/api/demo/scenario",
        "loadScenario",
        "scenario",
        request="ScenarioLoadRequest",
        response="ScenarioLoadResult",
        errors=(403, 409, 422, 503),
        description="Presenter only, DEMO_MODE with a goto connection: load another scenario for every"
        " user. `ian` starts the Hurricane Ian exercise pack (scripted synthetic data) at its first moment;"
        " `helene` returns to the Helene replay at the 11 AM advisory demo moment.",
    ),
    _e("GET", "/api/regions", "listRegions", "reference", response="Region", response_list=True),
    _e(
        "GET",
        "/api/assets",
        "listAssets",
        "reference",
        response="Asset",
        response_list=True,
        query=("bbox", "domain", "region", "limit", "after"),
        errors=(422,),
        description=ASSETS_DOC,
    ),
    _e("GET", "/api/assets/{asset_id}", "getAsset", "reference", response="Asset", errors=(404,)),
    _e(
        "GET",
        "/api/risk",
        "getRisk",
        "risk",
        response="RiskResponse",
        query=("as_of", "level"),
        errors=(404, 422),
    ),
    _e(
        "GET",
        "/api/forecasts",
        "getForecast",
        "risk",
        response="ForecastResponse",
        query=("target", "entity"),
        errors=(404, 422),
    ),
    _e("GET", "/api/outages", "listOutages", "ops", response="OutageItem", response_list=True),
    _e(
        "GET",
        "/api/outages/counties",
        "listCountyOutages",
        "ops",
        response="CountyOutagesNow",
        query=("as_of",),
        errors=(422,),
        description="Customers out per county in the replayed outage feed at `as_of` (default and upper"
        " bound: the scenario clock), the same hour and source as the Briefing total; counties without a"
        " report are not listed.",
    ),
    _e(
        "GET",
        "/api/outages/surges",
        "listOutageSurges",
        "ops",
        response="SurgeReport",
        query=("as_of",),
        errors=(404, 422),
        description="County outage surges from the EAGLE-I CUSUM detector at `as_of` (default and upper"
        " bound: the scenario clock); real public 2024 data, label C. 404 when the scenario has no series.",
    ),
    _e("GET", "/api/crews", "listCrews", "ops", response="CrewItem", response_list=True, query=("status",)),
    _e(
        "GET",
        "/api/crews/plan",
        "getCrewPlan",
        "ops",
        response="CrewPlanDocument",
        errors=(404, 422),
        query=("advisory",),
    ),
    _e(
        "GET",
        "/api/crews/targets",
        "listCrewTargets",
        "ops",
        response="CrewTarget",
        response_list=True,
        description="Open decisions and staging yards a crew can be assigned to.",
    ),
    _e(
        "POST",
        "/api/crews/{crew_id}/assignments",
        "assignCrew",
        "ops",
        request="CrewAssignRequest",
        response="CrewDispatchResult",
        status=201,
        errors=(403, 404, 409, 422),
        description="Propose an assignment; it waits for one signature of the function the dispatch"
        " policy names.",
    ),
    _e(
        "POST",
        "/api/crews/{crew_id}/assignment/sign",
        "signCrewAssignment",
        "ops",
        request="CrewSignRequest",
        response="CrewDispatchResult",
        errors=(403, 404, 409, 422),
    ),
    _e(
        "POST",
        "/api/crews/{crew_id}/assignment/withdraw",
        "withdrawCrewAssignment",
        "ops",
        response="CrewDispatchResult",
        errors=(403, 404, 409),
    ),
    _e(
        "POST",
        "/api/crews/{crew_id}/status",
        "moveCrew",
        "ops",
        request="CrewMoveRequest",
        response="CrewDispatchResult",
        errors=(403, 404, 409, 422),
        description="Move an assigned crew (on the way, on site, staged), block it with a reason, clear"
        " the block or release it; each move is a CrewStatus event in the ledger and an audit record.",
    ),
    _e(
        "GET",
        "/api/forecasts/outages/counties",
        "getCountyForecast",
        "risk",
        response="CountyForecast",
        errors=(404, 422),
        query=("advisory",),
    ),
    _e(
        "GET",
        "/api/forecasts/outages/plan-diff",
        "getPlanDiff",
        "risk",
        response="PlanDiff",
        errors=(404, 422),
        query=("to",),
    ),
    _e(
        "GET",
        "/api/hazard/advisories",
        "listHazardAdvisories",
        "risk",
        response="HazardAdvisory",
        response_list=True,
    ),
    _e(
        "GET",
        "/api/hazard/advisories/{label}",
        "getHazardAdvisory",
        "risk",
        response="HazardAdvisoryDetail",
        errors=(404,),
    ),
    _e(
        "GET",
        "/api/hazard/observed",
        "getObservedHazard",
        "risk",
        response="ObservedHazard",
        query=("as_of",),
        errors=(422,),
        description="Real Helene observations at `as_of` (default and upper bound: the scenario clock): USGS"
        " gauges with NWS flood categories, ASOS gusts and NWS warnings in force, peaks so far only.",
    ),
    _e("GET", "/api/whatif", "getWhatIf", "risk", response="WhatIfGrid"),
    _e("GET", "/api/damage/queue", "getDamageQueue", "ops", response="DamageQueue", query=("limit",)),
    _e(
        "GET",
        "/api/damage/thumbs/{image_id}",
        "getDamageThumb",
        "ops",
        errors=(404,),
        description="JPEG thumbnail (240 px) of one queued photo; LADI v2, CC-BY-4.0 (PROVENANCE.csv).",
    ),
    _e(
        "GET",
        "/api/damage/photos/{image_id}",
        "getDamagePhoto",
        "ops",
        response="DamagePhotoDetail",
        errors=(404,),
    ),
    _e(
        "GET",
        "/api/damage/images/{image_id}",
        "getDamageImage",
        "ops",
        errors=(404,),
        description="JPEG of one queued photo: the full-size file downloaded to this machine (`sgw photos`),"
        " else the 240 px thumbnail; header X-SGW-Image says which. LADI v2, CC-BY-4.0.",
    ),
    _e("GET", "/api/water/zones", "listWaterZones", "ops", response="WaterZone", response_list=True),
    _e("GET", "/api/anomalies", "listAnomalies", "ops", response="AnomalyItem", response_list=True),
    _e("GET", "/api/feeds/health", "listFeedHealth", "health", response="FeedHealthItem", response_list=True),
    _e("GET", "/api/stream/ops", "streamOps", "stream", sse=True),
    _e(
        "POST", "/api/threads", "createThread", "agent", request="ThreadCreate", response="Thread", status=201
    ),
    _e(
        "GET",
        "/api/threads/{thread_id}/messages",
        "listMessages",
        "agent",
        response="Message",
        response_list=True,
    ),
    _e(
        "POST",
        "/api/threads/{thread_id}/runs",
        "createRun",
        "agent",
        request="RunCreate",
        response="RunAccepted",
        status=202,
        errors=(409,),
    ),
    _e("GET", "/api/threads/{thread_id}/events", "streamRun", "stream", sse=True),
    _e("POST", "/api/threads/{thread_id}/runs/{run_id}/cancel", "cancelRun", "agent", status=204),
    _e(
        "GET",
        "/api/proposals/{proposal_id}/evidence",
        "listProposalEvidence",
        "decisions",
        response="EvidenceRecord",
        response_list=True,
        errors=(404,),
        description="The card's evidence ids resolved in the bundle of the run that made the proposal (ids"
        " are run-local): kind, title, source, as-of, model version, classification, trust; labels above the"
        " reader's clearance are withheld.",
    ),
    _e(
        "GET",
        "/api/threads/{thread_id}/runs",
        "listThreadRuns",
        "agent",
        response="ThreadRun",
        response_list=True,
        errors=(404,),
        description="The owner's runs of one thread, newest first: question, answer path and reason, tool"
        " calls, graph steps and the owner's feedback (the Ask Runs tab after a reload).",
    ),
    _e(
        "POST",
        "/api/threads/{thread_id}/runs/{run_id}/feedback",
        "putRunFeedback",
        "agent",
        request="RunFeedback",
        status=204,
        errors=(404,),
        description="The run owner's rating of the answer (up or down, optional note); one per run, a new"
        " rating replaces the old one.",
    ),
    _e(
        "POST",
        "/api/runs/{run_id}/resume",
        "resumeRun",
        "agent",
        response="RunAccepted",
        status=202,
        errors=(404, 409),
    ),
    _e("GET", "/api/proposals", "listProposals", "decisions", response="ProposalSummary", response_list=True),
    _e(
        "GET",
        "/api/decision-cases/missed",
        "listMissedDecisionCases",
        "decisions",
        response="MissedDecisionCase",
        response_list=True,
    ),
    _e(
        "GET",
        "/api/proposals/{proposal_id}",
        "getProposal",
        "decisions",
        response="ProposalCard",
        errors=(404,),
    ),
    _e(
        "POST",
        "/api/proposals",
        "createProposal",
        "decisions",
        request="ProposalCreate",
        response="ProposalCard",
        status=201,
    ),
    _e(
        "POST",
        "/api/proposals/{proposal_id}/approvals",
        "approveProposal",
        "decisions",
        request="ApprovalRequest",
        response="ApprovalResponse",
        errors=(403, 409, 412),
    ),
    _e(
        "POST",
        "/api/proposals/{proposal_id}/withdraw",
        "withdrawProposal",
        "decisions",
        request="WithdrawRequest",
        response="ProposalSummary",
        errors=(409,),
    ),
    _e(
        "POST",
        "/api/proposals/{proposal_id}/break-glass",
        "breakGlass",
        "decisions",
        request="BreakGlassRequest",
        response="ProposalCard",
        errors=(403, 409, 412),
    ),
    _e(
        "POST",
        "/api/proposals/{proposal_id}/cosign",
        "cosignBreakGlass",
        "decisions",
        response="CosignTaskOut",
        errors=(403, 404, 409, 412),
    ),
    _e("GET", "/api/proposals/{proposal_id}/clock", "getClock", "decisions", response="ClockWaterfall"),
    _e("GET", "/api/policies", "listPolicies", "governance", response="PolicyParam", response_list=True),
    _e("GET", "/api/readiness", "listReadiness", "decisions", response="ReadinessItem", response_list=True),
    _e(
        "POST",
        "/api/readiness/{item_id}",
        "recordReadiness",
        "decisions",
        request="ReadinessRecord",
        response="ReadinessItem",
        errors=(403, 404),
        description="The check's owner records its result (ready, not ready or waived, with a note) at the"
        " pre-season review; recorded in the audit chain (`readiness_recorded`).",
    ),
    _e(
        "GET",
        "/api/hazards/library/heat",
        "getHazardLibraryHeat",
        "decisions",
        response="HazardLibraryHeat",
        description="The July 2024 heat wave as of its trigger, read from the committed fixture;"
        " independent of the replay clock.",
    ),
    _e(
        "GET",
        "/api/hazards/library/wildfire",
        "getHazardLibraryWildfire",
        "decisions",
        response="HazardLibraryWildfire",
        description="The March 2025 Table Rock fire weather as of its first Red Flag trigger, read from the"
        " committed fixture; independent of the replay clock.",
    ),
    _e(
        "GET",
        "/api/audit",
        "listAudit",
        "governance",
        response="AuditEventOut",
        response_list=True,
        query=("from_seq", "subject"),
        description="Audit records in seq order, 500 per page; `subject` narrows to one proposal (or other"
        " subject) so a card's History reads its whole ledger in one call.",
    ),
    _e("POST", "/api/audit/verify", "verifyAudit", "governance", response="AuditVerifyResult"),
    _e(
        "GET",
        "/api/pipeline/runs",
        "listPipelineRuns",
        "health",
        response="PipelineRunOut",
        response_list=True,
    ),
    _e("GET", "/api/pipeline/assets", "listPipelineAssets", "health"),
    _e(
        "POST",
        "/api/pipeline/assets/{name}/run",
        "runPipelineAsset",
        "health",
        response="PipelineRunOut",
        status=202,
        errors=(403, 404),
    ),
    _e("GET", "/api/dq/checks", "listDqChecks", "health", response="DqCheckOut", response_list=True),
    _e("GET", "/api/models", "listModels", "health", response="ModelCard", response_list=True),
    _e(
        "GET",
        "/api/models/{name}/evaluation",
        "getModelEvaluation",
        "health",
        errors=(404,),
        description=(
            "A K17 report by name (outage_loso, outage_loso_v2, etr, saa, ladi_reference, anomaly_a7_a8):"
            " name, schema_version, created_at, code_version, command, metrics, caveats, provenance. Any"
            " other name is a registered model: its card and the K17 metrics of its serving version."
        ),
    ),
    _e("GET", "/api/llm/usage", "getLlmUsage", "health", query=("group_by", "since", "until", "run_id")),
    _e("GET", "/api/control/capabilities", "getCapabilities", "control"),
    _e("GET", "/api/control/kill", "getKill", "control", response="ControlState"),
    _e(
        "POST",
        "/api/control/kill",
        "setKill",
        "control",
        request="KillRequest",
        response="ControlState",
        errors=(403, 409),
        accepted="restore pending: first of two restore signatures; state unchanged; header"
        " `X-SGW-Restore: pending; id=<id>; awaiting=<function>`",
    ),
    _e("GET", "/api/control/mode", "getMode", "control", response="ControlState"),
    _e(
        "POST",
        "/api/control/mode",
        "setMode",
        "control",
        request="ModeRequest",
        response="ControlState",
        errors=(403, 409),
    ),
    _e("GET", "/api/admin/users", "listUsers", "admin", response="Me", response_list=True),
    _e(
        "GET",
        "/api/admin/approval-rights",
        "listApprovalRights",
        "admin",
        response="UserApprovalRights",
        response_list=True,
        errors=(403,),
        description="What each user may approve: action types and tiers from the authority rules.",
    ),
    _e(
        "GET",
        "/api/admin/ai-config",
        "getAiConfig",
        "admin",
        response="AiConfig",
        errors=(403,),
        description="Per-node LLM configuration from llm_nodes.yaml (read-only; no prompts, no keys).",
    ),
    _e(
        "GET",
        "/api/water/advisories",
        "listWaterAdvisories",
        "ops",
        response="BwaRegister",
        errors=(403,),
        description="Boil-water advisory register at the scenario time; C2, water domain only.",
    ),
    _e("GET", "/api/water/rules", "listWaterRules", "ops", response="BwaRules"),
    _e(
        "GET",
        "/api/commitments",
        "listCommitments",
        "decisions",
        response="CommitmentSummary",
        response_list=True,
        query=("state",),
    ),
    _e(
        "GET",
        "/api/commitments/{commitment_id}",
        "getCommitment",
        "decisions",
        response="CommitmentDetail",
        errors=(404,),
        description="Milestones and the drift log of one commitment.",
    ),
    _e(
        "GET",
        "/api/commitments/{commitment_id}/milestones",
        "listCommitmentMilestones",
        "decisions",
        response="CommitmentMilestone",
        response_list=True,
        errors=(404,),
    ),
    _e(
        "GET",
        "/api/after-action",
        "getAfterAction",
        "governance",
        response="AfterActionView",
        description="After-action review at the scenario time over the verified audit chain, the ETR"
        " scorecard and the SC 103-314 draft (not filed).",
    ),
    _e(
        "GET",
        "/api/after-action/official-record",
        "getOfficialRecord",
        "governance",
        response="OfficialRecord",
        description="FEMA declarations and NCEI Storm Events in the service area up to the scenario time.",
    ),
    _e(
        "POST",
        "/api/audit/tamper-demo",
        "tamperDemo",
        "governance",
        request="TamperDemoRequest",
        response="TamperDemoResult",
        errors=(404, 429),
        description="Alters one record in an in-memory copy of the chain and verifies the copy; the real"
        " chain is never written.",
    ),
    _e(
        "GET",
        "/api/admin/integrations",
        "getAdminIntegrations",
        "admin",
        response="AdminIntegrations",
        errors=(403,),
    ),
    _e(
        "GET",
        "/api/admin/system",
        "getSystemMetricsLink",
        "admin",
        response="SystemMetricsLink",
        errors=(403,),
    ),
    _e(
        "GET",
        "/api/runs",
        "listAgentRuns",
        "agent",
        response="AgentRunSummary",
        response_list=True,
        query=("graph", "status", "limit"),
        description="Recent agent runs with tokens and cost from llm_call; own runs, or every run for"
        " platform, command, executive, data and audit.",
    ),
    _e("GET", "/api/runs/{run_id}", "getAgentRun", "agent", response="AgentRunDetail", errors=(404,)),
    _e(
        "POST",
        "/api/runs/{run_id}/cancel",
        "cancelAgentRun",
        "agent",
        request="AgentRunCancel",
        response="AgentRunSummary",
        errors=(403, 404, 409),
        description="Platform or data cancels a running or paused agent run of anyone, with a reason;"
        " recorded in the audit chain (`agent_run_cancelled`).",
    ),
    _e(
        "GET",
        "/api/brief",
        "getBrief",
        "decisions",
        response="ExecutiveBrief",
        description="Executive Brief at the scenario time (W7): status word, four numbers with Forecast and"
        " Actual, open T3 clocks, one sentence per function, last advisory, caveat.",
    ),
    _e(
        "GET",
        "/api/sitreps",
        "listSitreps",
        "decisions",
        response="SitrepDraft",
        response_list=True,
        errors=(403,),
        description="Sitrep drafts of finished `sitrep` runs (C2) with their promotion state; command,"
        " executive and planning see every draft, others their own.",
    ),
    _e(
        "POST",
        "/api/sitreps/{run_id}/promote",
        "promoteSitrep",
        "decisions",
        request="SitrepPromote",
        response="SitrepDraft",
        errors=(403, 404, 409),
        description="A person in the command function promotes a verified T1 sitrep draft; recorded in the"
        " audit chain (`sitrep_promoted`). The draft text is not changed.",
    ),
    _e(
        "GET",
        "/api/etr",
        "getEtr",
        "risk",
        response="EtrView",
        description="Global and per-area ETR (P10/P50/P90 of 90 percent restored) from the latest ETR"
        " publication issued by the scenario time, its coverage caveat and the D4 publication state.",
    ),
    _e(
        "GET",
        "/api/etr/areas/{region_id}",
        "getEtrArea",
        "risk",
        response="EtrArea",
        errors=(404,),
        description="One ETR estimate (`GLOBAL` or an operating area) issued by the scenario time.",
    ),
    _e(
        "GET",
        "/api/after-action/drafts",
        "listAfterActionDrafts",
        "governance",
        response="AfterActionDraft",
        response_list=True,
        description="Drafts of `after_action` runs (C2), newest first; command, executive, planning and audit"
        " see every draft, others their own.",
    ),
    _e(
        "POST",
        "/api/after-action/drafts",
        "draftAfterAction",
        "governance",
        response="RunAccepted",
        status=202,
        errors=(403, 409),
        description="Starts the `after_action` graph at the scenario time for the command function or the"
        " auditor; recorded in the audit chain (`after_action_drafted`). Never filed.",
    ),
    _e("GET", "/healthz", "healthz", "ops", response="Health", auth="none"),
    _e("GET", "/readyz", "readyz", "ops", response="Health", auth="none"),
    _e(
        "GET",
        "/v1/decisions",
        "v1ListDecisions",
        "integration",
        response="DecisionV1",
        response_list=True,
        auth="api_token",
    ),
    _e(
        "GET",
        "/v1/decisions/{decision_case_id}",
        "v1GetDecision",
        "integration",
        response="DecisionV1",
        errors=(404,),
        auth="api_token",
    ),
    _e(
        "GET",
        "/v1/commitments",
        "v1ListCommitments",
        "integration",
        response="CommitmentV1",
        response_list=True,
        auth="api_token",
    ),
    _e(
        "POST",
        "/v1/webhooks",
        "v1CreateWebhook",
        "integration",
        request="WebhookSubscriptionCreate",
        response="WebhookSubscriptionV1",
        status=201,
        auth="api_token",
    ),
    _e(
        "GET",
        "/v1/webhooks",
        "v1ListWebhooks",
        "integration",
        response="WebhookSubscriptionV1",
        response_list=True,
        auth="api_token",
    ),
    _e(
        "DELETE",
        "/v1/webhooks/{subscription_id}",
        "v1DeleteWebhook",
        "integration",
        status=204,
        auth="api_token",
    ),
    _e(
        "POST",
        "/api/admin/tokens",
        "createApiToken",
        "admin",
        request="ApiTokenCreate",
        response="ApiTokenCreated",
        status=201,
    ),
    _e(
        "GET",
        "/v1/events",
        "v1StreamEvents",
        "integration",
        response="WebhookEventV1",
        sse=True,
        query=("types",),
        errors=(401, 403),
        auth="api_token",
        description=V1_EVENTS_DOC,
    ),
    _e(
        "POST",
        "/v1/webhooks/{subscription_id}/rotate-secret",
        "v1RotateWebhookSecret",
        "integration",
        response="WebhookSecretRotated",
        query=("overlap_s",),
        errors=(404,),
        auth="api_token",
        description="Adds a new signing secret; the previous one keeps signing for `overlap_s` seconds.",
    ),
    _e(
        "GET",
        "/v1/webhooks/{subscription_id}/deliveries",
        "v1ListWebhookDeliveries",
        "integration",
        response="WebhookDeliveryV1",
        response_list=True,
        query=("limit",),
        errors=(404,),
        auth="api_token",
    ),
    _e("GET", "/api/admin/tokens", "listApiTokens", "admin", response="ApiTokenOut", response_list=True),
    _e(
        "DELETE",
        "/api/admin/tokens/{token_id}",
        "revokeApiToken",
        "admin",
        status=204,
        errors=(404,),
        description="Revokes the token and disables its webhook subscriptions.",
    ),
)

SCHEMA_MODELS: tuple[type[Contract], ...] = (
    ErrorBody,
    LoginRequest,
    StepUpRequest,
    AuthConfig,
    Me,
    ScenarioState,
    ScenarioCommand,
    DemoGotoRequest,
    DemoGotoResult,
    ScenarioLoadRequest,
    ScenarioLoadResult,
    Region,
    Asset,
    RiskResponse,
    ForecastResponse,
    OutageItem,
    OutageSurge,
    SurgeReport,
    CountyOutagesNow,
    CrewItem,
    CrewTarget,
    CrewAssignRequest,
    CrewSignRequest,
    CrewMoveRequest,
    CrewDispatchResult,
    Provenance,
    CountyForecast,
    PlanDiff,
    CrewPlanDocument,
    DamageQueue,
    DamagePhotoDetail,
    HazardAdvisory,
    HazardAdvisoryDetail,
    ObservedHazard,
    OfficialRecord,
    WhatIfGrid,
    WaterZone,
    AnomalyItem,
    FeedHealthItem,
    ThreadCreate,
    Thread,
    RunCreate,
    RunAccepted,
    Message,
    ProposalSummary,
    MissedDecisionCase,
    ProposalCard,
    ProposalCreate,
    ApprovalRequest,
    ApprovalResponse,
    StaleProposal,
    BreakGlassRequest,
    CosignTaskOut,
    WithdrawRequest,
    ClockWaterfall,
    PolicyParam,
    ReadinessResult,
    ReadinessRecord,
    ReadinessItem,
    HazardLibraryHeat,
    HazardLibraryWildfire,
    AuditEventOut,
    AuditVerifyResult,
    PipelineRunOut,
    DqCheckOut,
    ModelCard,
    ControlState,
    KillRequest,
    ModeRequest,
    Health,
    DecisionV1,
    CommitmentV1,
    CommitmentSummary,
    CommitmentMilestone,
    CommitmentDriftEntry,
    CommitmentDetail,
    WebhookSubscriptionCreate,
    WebhookSubscriptionV1,
    WebhookDeliveryV1,
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenOut,
    WebhookSecretRotated,
    EffectOut,
    WebhookEventV1,
    WireFrame,
    Provenance,
    BwaRegister,
    BwaRules,
    UserApprovalRights,
    AiConfig,
    AfterActionView,
    TamperDemoRequest,
    TamperDemoResult,
    AdminIntegrations,
    SystemMetricsLink,
    AgentRunSummary,
    AgentRunDetail,
    ExecutiveBrief,
    SitrepDraft,
    SitrepPromote,
    EtrArea,
    EtrPublication,
    EtrView,
    AfterActionDraft,
    MessageCitation,
    MessageToolCall,
    ClockShift,
    VoidedApproval,
    EvidenceRecord,
    ThreadRun,
    ThreadRunStep,
    RunFeedback,
    MessageReference,
    Permissions,
    AgentRunCancel,
    Notification,
    NotificationFeed,
    NotificationRead,
)

_PATH_PARAM = re.compile(r"\{([a-z_]+)\}")
_ERROR_TEXT = {
    401: "Unauthenticated",
    403: "Forbidden by policy",
    404: "Not found",
    409: "State conflict",
    412: "Proposal version or action hash changed",
    422: "Invalid request",
    429: "Too many requests",
    503: "Unavailable",
}


def openapi_document() -> dict[str, Any]:
    _, defs = models_json_schema(
        [(m, "serialization") for m in SCHEMA_MODELS], ref_template="#/components/schemas/{model}"
    )
    schemas = dict(sorted(defs["$defs"].items()))
    ref = "#/components/schemas/"
    paths: dict[str, dict[str, Any]] = {}
    for ep in ENDPOINTS:
        op: dict[str, Any] = {"operationId": ep.operation_id, "tags": [ep.tag]}
        if ep.description:
            op["description"] = ep.description
        params = [
            {"name": p, "in": "path", "required": True, "schema": {"type": "string"}}
            for p in _PATH_PARAM.findall(ep.path)
        ]
        params += [
            {"name": q, "in": "query", "required": False, "schema": {"type": "string"}} for q in ep.query
        ]
        if params:
            op["parameters"] = params
        if ep.request:
            op["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": {"$ref": ref + ep.request}}},
            }
        responses: dict[str, Any] = {}
        if ep.sse:
            frame = ep.response or "WireFrame"
            label = "K4 SSE stream of WireFrame" if frame == "WireFrame" else f"SSE stream of {frame}"
            responses["200"] = {
                "description": label,
                "content": {"text/event-stream": {"schema": {"$ref": ref + frame}}},
            }
        elif ep.response:
            item = {"$ref": ref + ep.response}
            body = {"type": "array", "items": item} if ep.response_list else item
            responses[str(ep.status)] = {
                "description": "OK",
                "content": {"application/json": {"schema": body}},
            }
        else:
            responses[str(ep.status)] = {"description": "OK"}
        if ep.accepted:
            responses["202"] = {**responses[str(ep.status)], "description": ep.accepted}
        for code in ep.errors:
            schema = ref + ("StaleProposal" if code == 412 else "ErrorBody")
            responses[str(code)] = {
                "description": _ERROR_TEXT[code],
                "content": {"application/json": {"schema": {"$ref": schema}}},
            }
        op["responses"] = responses
        if ep.auth == "api_token":
            op["security"] = [{"apiToken": []}]
        elif ep.auth == "none":
            op["security"] = []
        paths.setdefault(ep.path, {})[ep.method.lower()] = op
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "SGW Resilience Decision Platform API",
            "version": f"1.0.0+schema{CURRENT_SCHEMA_VERSION}",
        },
        "servers": [{"url": "/"}],
        "paths": dict(sorted(paths.items())),
        "components": {
            "schemas": schemas,
            "securitySchemes": {
                "session": {"type": "apiKey", "in": "cookie", "name": "sgw_session"},
                "apiToken": {"type": "http", "scheme": "bearer"},
            },
        },
        "security": [{"session": []}],
    }


def contract_routes() -> set[tuple[str, str]]:
    return {(ep.method, ep.path) for ep in ENDPOINTS}


def missing_routes(app_routes: set[tuple[str, str]], *, prefixes: tuple[str, ...] = ("/",)) -> list[str]:
    """Contract routes under `prefixes` that a running app does not serve (route-exists test)."""
    return sorted(
        f"{method} {path}"
        for method, path in contract_routes() - app_routes
        if any(path.startswith(p) for p in prefixes)
    )
