"""K5 agent tool signatures and graph map (X-04, X-05).

Model-visible tools are read-only. `as_of`, role and region are injected server-side through
`InjectedContext` and never appear in a model-visible args schema. `draft_proposal` and
`optimise_prepositioning` are service functions called by graph code, not tools bound to a model.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from sgw.contracts.base import Contract, Identifier, Ppm, UtcDatetime
from sgw.contracts.vocab import (
    ActionType,
    ApprovalFunction,
    Classification,
    Domain,
    ProposalState,
    RiskBand,
    RunMode,
    Tier,
)

FORBIDDEN_MODEL_ARGS = frozenset({"as_of", "role", "user_role", "region", "region_id", "user_id", "run_mode"})
FORBIDDEN_REQUEST_PARAMS = frozenset({"temperature", "top_p", "top_k"})


class InjectedContext(Contract):
    as_of: UtcDatetime
    user_id: Identifier
    user_role: ApprovalFunction
    region_ids: list[str]
    run_mode: RunMode
    classification_ceiling: Classification


class ToolMeta(Contract):
    name: str
    tier_ceiling: Tier
    reads_classes: list[Classification]
    side_effect: Literal["none", "draft"]
    model_visible: bool
    returns_search_results: bool = False


class GetRiskArgs(Contract):
    level: Literal["county", "h3", "asset"]
    entity_ids: list[Identifier] = Field(default_factory=list, max_length=50)
    domain: Domain | None = None


class RiskRow(Contract):
    entity_id: Identifier
    p_ppm: Ppm
    band: RiskBand
    evidence_id: str


class GetRiskResult(Contract):
    rows: list[RiskRow]
    snapshot_id: Identifier


class GetForecastArgs(Contract):
    target: Literal["outages", "etr", "pressure", "load"]
    entity_id: Identifier


class ForecastResult(Contract):
    evidence_id: str
    quantile_slots: list[str] = Field(description="slot names such as E3.p50; values withheld from the model")


class GetOutagesArgs(Contract):
    feeder_ids: list[Identifier] = Field(default_factory=list, max_length=50)
    only_critical: bool = False


class GetCrewsArgs(Contract):
    status: list[str] = Field(default_factory=list)


class GetWaterStatusArgs(Contract):
    zone_ids: list[Identifier] = Field(default_factory=list)


class ListAnomaliesArgs(Contract):
    domain: Domain | None = None
    limit: int = Field(default=20, ge=1, le=100)


class GetFeedHealthArgs(Contract):
    source_ids: list[Identifier] = Field(default_factory=list)


class SearchProceduresArgs(Contract):
    query: str = Field(min_length=3, max_length=500)
    top_k: int = Field(default=8, ge=1, le=20)


class SearchResultBlock(Contract):
    """Anthropic `search_result` content block; retrieval tools return only these."""

    type: Literal["search_result"] = "search_result"
    source: str
    title: str
    content: list[dict[str, Any]]
    citations: dict[str, bool] = Field(default_factory=lambda: {"enabled": True})


class GetDecisionCaseArgs(Contract):
    decision_case_id: Identifier


class RunWhatIfArgs(Contract):
    scenario: Literal["pump_station_outage", "feeder_restore_order", "crew_shift", "advisory_shift"]
    parameters: dict[str, int | str | bool]


class ListDecisionsArgs(Contract):
    states: list[ProposalState] = Field(default_factory=list, max_length=9)
    limit: int = Field(default=20, ge=1, le=50)


class GetReadinessArgs(Contract):
    domain: Domain | None = None
    status: Literal["ready", "gap", "unknown"] | None = None


class GetEtrArgs(Contract):
    entity_id: Identifier = Field(default="GLOBAL", description="GLOBAL or an operating-area region id")


class ListOutageSurgesArgs(Contract):
    county_fips: list[Annotated[str, Field(pattern=r"^\d{5}$")]] = Field(default_factory=list, max_length=50)
    active_only: bool = False
    limit: int = Field(default=20, ge=1, le=50)


class GetDamagePhotosArgs(Contract):
    limit: int = Field(default=10, ge=1, le=25)
    tier: Literal["structural", "slight"] | None = None
    case_id: Identifier | None = None


class EvidenceListResult(Contract):
    evidence_ids: list[str]


class DraftProposalArgs(Contract):
    action_type: ActionType
    params: dict[str, int | str | bool | list[str]]
    target_ids: list[Identifier]
    evidence_ids: list[str]
    decision_case_id: Identifier


class OptimisePrepositioningArgs(Contract):
    scenario_ids: list[str] = Field(min_length=1)
    staging_site_ids: list[Identifier] = Field(min_length=1)
    crew_budget: int = Field(ge=1)


_C01 = [Classification.C0, Classification.C1]
_C012 = [Classification.C0, Classification.C1, Classification.C2]

TOOLS: dict[str, tuple[ToolMeta, type[Contract], type[Contract]]] = {
    "get_risk": (
        ToolMeta(
            name="get_risk", tier_ceiling=Tier.T0, reads_classes=_C012, side_effect="none", model_visible=True
        ),
        GetRiskArgs,
        GetRiskResult,
    ),
    "get_forecast": (
        ToolMeta(
            name="get_forecast",
            tier_ceiling=Tier.T0,
            reads_classes=_C012,
            side_effect="none",
            model_visible=True,
        ),
        GetForecastArgs,
        ForecastResult,
    ),
    "get_outages": (
        ToolMeta(
            name="get_outages",
            tier_ceiling=Tier.T0,
            reads_classes=_C012,
            side_effect="none",
            model_visible=True,
        ),
        GetOutagesArgs,
        EvidenceListResult,
    ),
    "get_crews": (
        ToolMeta(
            name="get_crews",
            tier_ceiling=Tier.T0,
            reads_classes=_C012,
            side_effect="none",
            model_visible=True,
        ),
        GetCrewsArgs,
        EvidenceListResult,
    ),
    "get_water_status": (
        ToolMeta(
            name="get_water_status",
            tier_ceiling=Tier.T0,
            reads_classes=_C012,
            side_effect="none",
            model_visible=True,
        ),
        GetWaterStatusArgs,
        EvidenceListResult,
    ),
    "list_anomalies": (
        ToolMeta(
            name="list_anomalies",
            tier_ceiling=Tier.T0,
            reads_classes=_C012,
            side_effect="none",
            model_visible=True,
        ),
        ListAnomaliesArgs,
        EvidenceListResult,
    ),
    "get_feed_health": (
        ToolMeta(
            name="get_feed_health",
            tier_ceiling=Tier.T0,
            reads_classes=_C01,
            side_effect="none",
            model_visible=True,
        ),
        GetFeedHealthArgs,
        EvidenceListResult,
    ),
    "search_procedures": (
        ToolMeta(
            name="search_procedures",
            tier_ceiling=Tier.T0,
            reads_classes=_C01,
            side_effect="none",
            model_visible=True,
            returns_search_results=True,
        ),
        SearchProceduresArgs,
        SearchResultBlock,
    ),
    "get_decision_case": (
        ToolMeta(
            name="get_decision_case",
            tier_ceiling=Tier.T0,
            reads_classes=_C012,
            side_effect="none",
            model_visible=True,
        ),
        GetDecisionCaseArgs,
        EvidenceListResult,
    ),
    "run_what_if": (
        ToolMeta(
            name="run_what_if",
            tier_ceiling=Tier.T0,
            reads_classes=_C012,
            side_effect="none",
            model_visible=True,
        ),
        RunWhatIfArgs,
        EvidenceListResult,
    ),
    "list_decisions": (
        ToolMeta(
            name="list_decisions",
            tier_ceiling=Tier.T0,
            reads_classes=_C012,
            side_effect="none",
            model_visible=True,
        ),
        ListDecisionsArgs,
        EvidenceListResult,
    ),
    "get_readiness": (
        ToolMeta(
            name="get_readiness",
            tier_ceiling=Tier.T0,
            reads_classes=_C01,
            side_effect="none",
            model_visible=True,
        ),
        GetReadinessArgs,
        EvidenceListResult,
    ),
    "get_etr": (
        ToolMeta(
            name="get_etr", tier_ceiling=Tier.T0, reads_classes=_C012, side_effect="none", model_visible=True
        ),
        GetEtrArgs,
        EvidenceListResult,
    ),
    "list_outage_surges": (
        ToolMeta(
            name="list_outage_surges",
            tier_ceiling=Tier.T0,
            reads_classes=_C01,
            side_effect="none",
            model_visible=True,
        ),
        ListOutageSurgesArgs,
        EvidenceListResult,
    ),
    "get_damage_photos": (
        ToolMeta(
            name="get_damage_photos",
            tier_ceiling=Tier.T0,
            reads_classes=_C01,
            side_effect="none",
            model_visible=True,
        ),
        GetDamagePhotosArgs,
        EvidenceListResult,
    ),
    "draft_proposal": (
        ToolMeta(
            name="draft_proposal",
            tier_ceiling=Tier.T3,
            reads_classes=_C012,
            side_effect="draft",
            model_visible=False,
        ),
        DraftProposalArgs,
        EvidenceListResult,
    ),
    "optimise_prepositioning": (
        ToolMeta(
            name="optimise_prepositioning",
            tier_ceiling=Tier.T0,
            reads_classes=_C012,
            side_effect="none",
            model_visible=False,
        ),
        OptimisePrepositioningArgs,
        EvidenceListResult,
    ),
}

MODEL_VISIBLE_TOOLS: tuple[str, ...] = tuple(
    name for name, (meta, _, _) in TOOLS.items() if meta.model_visible
)

GRAPHS: dict[str, dict[str, Any]] = {
    "assess": {"workflows": ["W1", "W2"], "decisions": ["D1", "D2"]},
    "water_continuity": {"workflows": ["W3", "W4"], "decisions": ["D3"]},
    "etr": {"workflows": ["W5"], "decisions": ["D4"]},
    "sitrep": {"workflows": ["W7"], "decisions": []},
    "after_action": {"workflows": ["W13"], "decisions": ["D5"]},
    "copilot": {"workflows": ["W9"], "decisions": []},
}


def tool_schemas() -> dict[str, Any]:
    return {
        name: {
            "meta": meta.model_dump(mode="json"),
            "args": args.model_json_schema(),
            "result": result.model_json_schema(),
        }
        for name, (meta, args, result) in TOOLS.items()
    } | {"graphs": GRAPHS}
