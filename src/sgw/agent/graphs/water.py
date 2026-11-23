"""`water_continuity` graph (K5 GRAPHS: workflows W3, W4; decision D3): the PS-17 cascade as evidence, the
cross-domain priority proposal and the boil-water advisory proposal, both raised by rules (`system:rule`),
never by the model.

load_context -> input_guard -> collect_evidence (Send fan-out: PS-17 chain clocks, water status) -> fuse ->
rules (priority rule, BWA rules engine, cascade, notice draft, lifecycle tasks) -> narrate (LLM) ->
draft_rationale (LLM, one per proposal, each on its own evidence) -> verify -> policy_gate (each proposal
drafted through the rule port) -> approval (interrupt) -> execute (asks the store) -> audit.

Cascade: feeder exposure -> generator hookup -> fuel -> zone tank drain -> pressure floor at the
hospital's service connection (SC R.61-58.7.E(7), water twin) -> boil-water advisory. Every number is a slot
filled by code; the LLM explains, and on any failure the M2 templates write the same slots.
"""

from __future__ import annotations

import hashlib
import json
import math
import operator
import re
import statistics
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Protocol

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send, interrupt

from sgw.agent.nodes import evidence_source as es
from sgw.agent.nodes import spine
from sgw.agent.nodes.gate import gated
from sgw.agent.nodes.llm import node_config
from sgw.agent.nodes.ports import (
    EXECUTED_STATES,
    ApprovalServicePort,
    PolicyDenied,
    burn_execution_token,
    with_taint_note,
)
from sgw.agent.nodes.spine import SpineDeps, SpineState, emit
from sgw.agent.nodes.templates import M2_NOTE, narrate_template, rationale_template
from sgw.agent.nodes.text_nodes import (
    Precondition,
    RationaleOut,
    draft_rationale,
    rationale_problems,
)
from sgw.agent.render.evidence import UNTRUSTED, EvidenceBundle, EvidenceItem, SlotValue, build_view
from sgw.agent.render.slots import render_text, slot_values, used_values
from sgw.agent.render.verify import verify
from sgw.approval.policy import Classification as PolicyClassification
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.contracts import approval as ap
from sgw.contracts.api_models import ProposalCreate
from sgw.contracts.tools import TOOLS
from sgw.contracts.vocab import (
    ActionType,
    Classification,
    ClockKind,
    DecisionStep,
    Domain,
    InitiatorKind,
    NoRegretVerdict,
    RiskBand,
    Tier,
    Trust,
)
from sgw.contracts.wire import ApprovalRequiredPayload
from sgw.models.clocks import ps17
from sgw.models.clocks.service import CaseSpec
from sgw.models.water.floors import State
from sgw.rules import bwa, priority

GRAPH_ID = "water_continuity"
REPO = Path(__file__).resolve().parents[4]
CONTINUITY_FILE = REPO / "data" / "artefacts" / "water_twin" / "continuity_helene.json"
TWIN_TABLE_FILE = REPO / "data" / "artefacts" / "water_twin" / "ps17_clock_members.json"
LANDFALL_UTC = datetime(2024, 9, 27, 3, 10, tzinfo=UTC)
ZONE_NAME = "Cedarfall"
STATE = State.SC
PRIORITY_CASE = ps17.CASE_POWER
BWA_CASE = "DC-D3-PS17-CEDARFALL-BWA"
BWA_TITLE = "Issue a boil water advisory for the Cedarfall zone"
BWA_PROPOSERS = {
    bwa.Cause.PRE_HURRICANE: "system:rule:bwa_pre_landfall",
    bwa.Cause.PRESSURE_LOSS: "system:rule:bwa_pressure_loss",
}
PRESTAGED_LAG_MIN = 60
WATER_TOOL = "get_water_status"
PHASE = (
    "pre-landfall water continuity for PS-17 and the hospital it serves (D3: cascade, cross-domain "
    "priority, precautionary boil water advisory). Give reasons in words, never a time as the reason "
    "(write 'to stay ahead of the consequence at {E<n>.consequence}', not 'because {E<n>.consequence}'); "
    "show a range only next to the decide_by it belongs to"
)
M2_PRECONDITIONS = {
    ActionType.CROSS_DOMAIN_PRIORITY.value: [
        Precondition.GENERATOR_READY.value,
        Precondition.FUEL_PATH_OPEN.value,
        Precondition.CREWS_AVAILABLE.value,
    ],
    ActionType.BOIL_WATER_NOTICE.value: [
        Precondition.ADVISORY_CONFIRMS_TRACK.value,
        Precondition.PRESSURE_FLOOR_HELD.value,
    ],
}


def node(name: str, *, llm: bool = False) -> Callable[[Callable[..., Awaitable[dict[str, Any]]]], Any]:
    """The spine's K12 span and K4 step/agent events, for nodes typed on `WaterState`."""
    return spine.node(name, llm=llm)


def load_json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


# ---- rule port: proposals raised by a rule, never by the model or the run's user -------------------------


@dataclass(frozen=True)
class RuleDraft:
    payload: ApprovalRequiredPayload
    escalators: tuple[str, ...]


class RulePort(Protocol):
    def draft(
        self, request: ProposalCreate, *, proposer: str, rationale: str, run_id: str, tainted: bool
    ) -> RuleDraft: ...

    def approval_state(self, proposal_id: str) -> tuple[str, int, str]: ...

    def record_effect(self, proposal_id: str, run_id: str) -> str: ...


def rule_policy_input(request: ProposalCreate, proposer: str) -> dict[str, Any]:
    return {
        "action": "propose",
        "subject": {"user_id": proposer},
        "proposal": {
            "action_type": request.action_type.value,
            "proposed_by": proposer,
            "requested_by": None,
            "initiator_kind": InitiatorKind.SYSTEM_RULE.value,
            "target_ids": list(request.target_ids),
        },
        "facts": {},
        "context": {"degraded_mode": "normal"},
    }


@dataclass
class InMemoryRulePort:
    """Mirror of the approval service for replay tests and the keyless demo: the reference policy decides the
    tier and functions, the action hash is the K8 hash, and state starts at `proposed`."""

    policy: ReferencePolicy = field(default_factory=ReferencePolicy)
    proposals: dict[str, dict[str, Any]] = field(default_factory=dict)
    effects: list[dict[str, Any]] = field(default_factory=list)

    def draft(
        self, request: ProposalCreate, *, proposer: str, rationale: str, run_id: str, tainted: bool
    ) -> RuleDraft:
        decision = self.policy.propose(rule_policy_input(request, proposer))
        if not decision.allow:
            raise PolicyDenied(decision.deny)
        c = decision.classification
        tier = Tier(c.tier)
        material = ap.MaterialFields(
            action_type=request.action_type,
            params=request.model_dump(mode="json")["params"],
            target_ids=list(request.target_ids),
            risk_band=RiskBand.HIGH,
            preconditions={},
            tier=tier,
            escalators=list(c.escalators),
        )
        action_hash = ap.action_hash(material, c.policy_version)
        pid = "PRP-" + hashlib.sha256(f"{run_id}:{action_hash}".encode()).hexdigest()[:12].upper()
        self.proposals[pid] = {
            "request": request.model_dump(mode="json"),
            "state": "proposed",
            "version": 1,
            "action_hash": action_hash,
            "rationale": with_taint_note(rationale, tainted),
            "proposed_by": proposer,
            "initiator_kind": InitiatorKind.SYSTEM_RULE.value,
            "run_id": run_id,
        }
        return RuleDraft(
            ApprovalRequiredPayload(
                proposal_id=pid,
                proposal_version=1,
                action_hash=action_hash,
                tier=tier,
                functions_required=list(c.required_functions),  # type: ignore[arg-type]
                tainted=tainted,
            ),
            c.escalators,
        )

    def approval_state(self, proposal_id: str) -> tuple[str, int, str]:
        p = self.proposals[proposal_id]
        return str(p["state"]), int(p["version"]), str(p["action_hash"])

    def record_effect(self, proposal_id: str, run_id: str) -> str:
        effect_id = f"EFF-{proposal_id}-{len(self.effects) + 1}"
        self.effects.append({"effect_id": effect_id, "proposal_id": proposal_id, "run_id": run_id})
        return effect_id


def bwa_case_spec() -> CaseSpec:
    """The Cedarfall precautionary advisory's own decision case (V2-28): due at landfall under the SC
    pre-hurricane rule (SC-A2), separate from the zone pressure decision it protects against."""
    from sgw.models.clocks.waterfall import ConsequenceSpec
    from sgw.rules.zones import basis

    rule = basis("rule.sc_bwa_pre_landfall", "SC-A2", ClockKind.RULE_DEADLINE)
    return CaseSpec(
        case_id=BWA_CASE,
        step=DecisionStep.D3,
        title=BWA_TITLE,
        domain=Domain.WATER,
        region_id=ps17.REGION,
        consequence=ConsequenceSpec(
            consequence_basis=rule,
            anchor_label="Hurricane landfall",
            anchor_basis=rule,
            anchor_utc=[LANDFALL_UTC],
        ),
        lead_key="boil_water_notice_release",
        if_late="Customers in the Cedarfall zone are not told to boil water before pressure may fall.",
    )


def ensure_bwa_case(conn: psycopg.Connection[Any], now: datetime) -> None:
    """Store the advisory's case before its proposal references it (the advisory queue never holds it)."""
    from sgw.models.clocks.service import compute_queue
    from sgw.models.clocks.store import save_queue

    found = conn.execute("SELECT 1 FROM decision_case WHERE decision_case_id = %s", (BWA_CASE,)).fetchone()
    if found is None:
        save_queue(conn, compute_queue([bwa_case_spec()], now=now))


@dataclass
class ApprovalServiceRulePort:
    """Drafts through WP-09a's approval service in the run's database with initiator kind `system_rule`
    and the rule's principal as proposer (K8 lists it); facts come from the service's own tables."""

    connect: Any
    service: ApprovalService

    def draft(
        self, request: ProposalCreate, *, proposer: str, rationale: str, run_id: str, tainted: bool
    ) -> RuleDraft:
        conn: psycopg.Connection[Any]
        with self.connect() as conn:
            if request.decision_case_id == BWA_CASE:
                ensure_bwa_case(conn, self.service.scenario_clock())
            card = self.service.create(
                conn,
                proposed_by=proposer,
                request=request,
                initiator_kind=InitiatorKind.SYSTEM_RULE,
                rationale=with_taint_note(rationale, tainted),
                run_id=run_id,
            ).value
        return RuleDraft(
            ApprovalRequiredPayload(
                proposal_id=card.proposal_id,
                proposal_version=card.proposal_version,
                action_hash=card.action_hash,
                tier=card.tier,
                functions_required=list(card.functions_required),
                tainted=tainted,
            ),
            tuple(card.escalators),
        )

    def approval_state(self, proposal_id: str) -> tuple[str, int, str]:
        with self.connect() as conn:
            card = self.service.card(conn, proposal_id)
        return card.state.value, card.proposal_version, card.action_hash

    def record_effect(self, proposal_id: str, run_id: str) -> str:
        return burn_execution_token(self.connect, self.service, proposal_id)


# ---- deps and state ---------------------------------------------------------------------------------------


@dataclass
class WaterDeps(SpineDeps):
    rule_port: RulePort = field(default_factory=InMemoryRulePort)
    continuity: Mapping[str, Any] = field(default_factory=lambda: load_json(CONTINUITY_FILE))
    network: Mapping[str, Any] = field(default_factory=lambda: load_json(spine.NETWORK_FILE))
    landfall_utc: datetime = LANDFALL_UTC
    readings: tuple[bwa.PressureReading, ...] = ()


def from_spine(deps: SpineDeps) -> WaterDeps:
    """WaterDeps from the API's spine deps: the twin member table, and a rule port on the same approval
    service and connection when the spine drafts in Postgres (in-memory otherwise)."""
    if isinstance(deps, WaterDeps):
        return deps
    port: RulePort = (
        ApprovalServiceRulePort(connect=deps.proposals.connect, service=deps.proposals.service)
        if isinstance(deps.proposals, ApprovalServicePort)
        else InMemoryRulePort()
    )
    return WaterDeps(
        llm=deps.llm,
        proposals=deps.proposals,
        member_table=load_json(TWIN_TABLE_FILE),
        nodes_file=deps.nodes_file,
        route=deps.route,
        extra_ids=deps.extra_ids,
        model_overrides=dict(deps.model_overrides),
        policy_evidence=deps.policy_evidence,
        llm_gate=deps.llm_gate,
        rule_port=port,
    )


class WaterState(SpineState, total=False):
    proposals: list[dict[str, Any]]
    rationales: Annotated[list[dict[str, Any]], operator.add]
    rule_results: dict[str, Any]
    cascade: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    notice: dict[str, Any] | None
    approvals: list[dict[str, Any]]


def _deps(runtime: Runtime[SpineDeps]) -> WaterDeps:
    deps = runtime.context
    if not isinstance(deps, WaterDeps):
        raise TypeError("water_continuity needs WaterDeps")
    return deps


def _ctx(state: SpineState, deps: SpineDeps) -> dict[str, Any]:
    raw = state.get("input") or {}
    return {
        "member_table": deps.member_table,
        "advisory": str(raw.get("advisory", "N+1")),
        "event_type_inputs": None,
        "region_id": ps17.REGION,
    }


# ---- water status (K5 get_water_status), computed by code -------------------------------------------------


SENSITIVITY_LAGS_MIN = (60, 90, 120)


@dataclass(frozen=True)
class ZoneStatus:
    zone_id: str
    station_id: str
    p_loss: float
    breach_given_loss: float
    breach_p: float
    hookup_lag_min: float
    residual_p: float
    sensitivity: dict[int, float]
    floor_psi: float
    floor_rule_id: str
    critical_node: str
    on_backup_or_exposed: bool
    as_of: datetime


def generator_residual_p(horizon_h: float) -> float:
    """P(the portable generator fails to start or fails while running within the horizon), from the twin's
    maintenance-class mix and failure rates (forecast-time parameters, no outcome data). Treating such a
    failure as a floor breach is conservative: a tank refill can still cover part of a failure."""
    from sgw.models.water.params import twin_params

    tp = twin_params()
    share, fts, mttf = (
        tp["generator.class_share"],
        tp["generator.fail_to_start"],
        tp["generator.run_mttf_h"],
    )
    return math.fsum(
        float(share[c]) * (float(fts[c]) + (1 - float(fts[c])) * (1 - math.exp(-horizon_h / float(mttf[c]))))
        for c in share
    )


def breach_p_at(members: list[dict[str, Any]], lag_min: float, residual: float) -> float:
    """E over members of p_i * b_i: member i's P(PS-17 power loss) times P(floor breach | loss), where the
    breach is certain when the member's zone drain to the floor at the critical node is not longer than the
    generator-hookup lag, and otherwise the generator's own failure probability."""
    return statistics.fmean(
        float(m["p_loss_final"]) * (1.0 if float(m["drain_to_floor_min"]) <= lag_min else residual)
        for m in members
    )


def zone_status(deps: WaterDeps, advisory: str) -> ZoneStatus:
    """Forecast-time P(floor breach at the hospital connection within the continuity horizon) for PS-17's
    zone, per ensemble member (no independence assumption): inputs are the advisory's member table (P(loss),
    drain to the floor from the tank level observed at issue time), the planned hookup lead time and the
    twin's generator failure parameters. The twin's realised-timing continuity result is not used."""
    from sgw.common import numbers as numbers_mod

    link = priority.ps17_link(deps.network)
    adv = deps.member_table["advisories"][advisory]
    members = list(adv["members"])
    p_loss = statistics.fmean(float(m["p_loss_final"]) for m in members)
    lag = float(deps.member_table["lead_min"]["generator.hookup_lead_min"])
    residual = generator_residual_p(float(numbers_mod.value("policy_water_continuity_horizon_h")))
    breach = breach_p_at(members, lag, residual)
    floor = deps.continuity["floor"]
    twin = deps.member_table.get("water_twin") or {}
    counts: dict[str, int] = twin.get("critical_node_counts_members") or {}
    critical = max(counts, key=lambda k: counts[k]) if counts else "J-CF-TALLOWBRANCH"
    station = deps.network["named"]["pump_stations"][link.station_id]
    on_backup = station.get("onsite_generator") is None
    exposed = p_loss >= float(deps.member_table["material_loss_p"])
    return ZoneStatus(
        zone_id=link.zone_id,
        station_id=link.station_id,
        p_loss=p_loss,
        breach_given_loss=breach / p_loss if p_loss else 0.0,
        breach_p=breach,
        hookup_lag_min=lag,
        residual_p=residual,
        sensitivity={lag_s: breach_p_at(members, lag_s, residual) for lag_s in SENSITIVITY_LAGS_MIN},
        floor_psi=float(floor["psi"]),
        floor_rule_id=str(floor["rule_id"]),
        critical_node=critical,
        on_backup_or_exposed=on_backup and exposed,
        as_of=datetime.fromisoformat(adv["issued_utc"].replace("Z", "+00:00")),
    )


def _ppm(p: float) -> int:
    return round(p * 1_000_000)


def water_item(n: int, z: ZoneStatus, deps: WaterDeps) -> EvidenceItem:
    link = priority.ps17_link(deps.network)
    twin = deps.member_table.get("water_twin") or {}
    drain = (twin.get("drain_basis") or {}).get("basis_id", "water_twin.zone_drain_critical_node")
    values = {
        "breach_p": SlotValue(value=_ppm(z.breach_p), format="percent_ppm"),
        "power_loss_p": SlotValue(value=_ppm(z.p_loss), format="percent_ppm"),
        "breach_given_loss_p": SlotValue(value=_ppm(z.breach_given_loss), format="percent_ppm"),
        "floor": SlotValue(value=z.floor_psi, format="psi"),
        "hookup_lag": SlotValue(value=z.hookup_lag_min, format="minutes"),
    }
    return EvidenceItem(
        id=f"E{n}",
        kind="water_continuity",
        label=f"{ZONE_NAME} water zone served by {z.station_id}: forecast pressure at the service "
        f"connection of {link.critical_customer_id}",
        as_of=z.as_of,
        model_version=f"{drain} per member",
        citation=f"{drain}; {link.station_id} generator failure classes; {z.floor_rule_id}",
        classification=Classification.C2,
        label_classification=Classification.C1,
        trust=Trust.SYSTEM,
        values=values,
        hints={"floor_at": "service_connection", "critical_node": "hospital_connection"},
        entity_ids=[z.zone_id, z.station_id, link.critical_customer_id, z.critical_node],
    )


def sensitivity_item(n: int, z: ZoneStatus) -> EvidenceItem:
    """The same forecast with a shorter generator-hookup lag (a pre-staged generator): lower is better."""
    values: dict[str, SlotValue] = {}
    for lag_s, p in z.sensitivity.items():
        values[f"lag_{lag_s}"] = SlotValue(value=lag_s, format="minutes")
        values[f"breach_p_lag_{lag_s}"] = SlotValue(value=_ppm(p), format="percent_ppm")
    return EvidenceItem(
        id=f"E{n}",
        kind="hookup_sensitivity",
        label=f"{ZONE_NAME} zone: forecast chance of falling below the floor if the generator is hooked up "
        "sooner after a loss (pre-staged generator)",
        as_of=z.as_of,
        model_version="water_twin.zone_drain_critical_node per member",
        citation="water_twin.zone_drain_critical_node; hookup lag sensitivity",
        classification=Classification.C2,
        label_classification=Classification.C1,
        trust=Trust.SYSTEM,
        values=values,
        hints={"direction": "shorter_lag_lowers_breach"},
        entity_ids=[z.zone_id, z.station_id],
    )


# ---- graph nodes ------------------------------------------------------------------------------------------


@node("load_context")
async def load_context(state: WaterState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    _deps(runtime)
    advisory = str((state.get("input") or {}).get("advisory", "N+1"))
    if advisory not in runtime.context.member_table.get("advisories", {}):
        raise ValueError(f"advisory {advisory!r} has no member table")
    return {
        "phase": PHASE,
        "status": "running",
        "audit": [{"kind": "run_start", "graph": GRAPH_ID, "user_id": state.get("user_id")}],
    }


def collect_evidence(state: WaterState, runtime: Runtime[SpineDeps]) -> list[Send]:
    """Fan-out decided by code: one `get_decision_case` per PS-17 chain case (critical path first) and one
    `get_water_status` for the station's zone."""
    deps = _deps(runtime)
    calls = es.plan_calls(_ctx(state, deps))
    calls.append((WATER_TOOL, {"zone_ids": [priority.ps17_link(deps.network).zone_id]}))
    return [
        Send("call_tool", {**state, "task": {"tool": name, "args": args, "n": i}})
        for i, (name, args) in enumerate(calls)
    ]


@node("call_tool")
async def call_tool(state: WaterState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    task = state["task"]
    name, args = str(task["tool"]), dict(task["args"])
    if name != WATER_TOOL:
        return await spine.call_tool.__wrapped__(state, runtime)  # type: ignore[attr-defined,no-any-return]
    emit("tool_start", {"tool": name, "args": args, "call": task["n"]})
    TOOLS[name][1].model_validate(args)
    results = [{"kind": "water_status", "zone_id": z} for z in args["zone_ids"]]
    emit("tool_end", {"tool": name, "call": task["n"], "status": "ok", "results": len(results)})
    return {"tool_results": results, "audit": [{"kind": "tool_call", "tool": name, "args": args}]}


@node("fuse")
async def fuse(state: WaterState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    deps = _deps(runtime)
    ctx = _ctx(state, deps)
    results = sorted(state.get("tool_results") or [], key=lambda r: json.dumps(r, sort_keys=True))
    items = es.build_items([r for r in results if r.get("kind") == "decision_clock"], ctx, [])
    if any(r.get("kind") == "water_status" for r in results):
        z = zone_status(deps, ctx["advisory"])
        items.append(water_item(len(items) + 1, z, deps))
        items.append(sensitivity_item(len(items) + 1, z))
    return {
        "bundle": EvidenceBundle(run_id=state["run_id"], items=items).model_dump(mode="json"),
        "audit": [{"kind": "evidence", "items": len(items)}],
    }


def _policy(request: ProposalCreate, proposer: str) -> PolicyClassification:
    return ReferencePolicy().classify(rule_policy_input(request, proposer))


def _policy_item(n: int, c: PolicyClassification, as_of: datetime, what: str) -> EvidenceItem:
    return EvidenceItem(
        id=f"E{n}",
        kind="approval_policy",
        label=f"Approval tier and approver functions for the {what} proposal (approval policy, code)",
        as_of=as_of,
        model_version=c.policy_version,
        citation=f"approval policy {c.policy_version}",
        classification=Classification.C1,
        trust=Trust.SYSTEM,
        values={
            "tier": SlotValue(value=c.tier, format="text"),
            "approver_functions": SlotValue(value=" and ".join(c.required_functions), format="text"),
        },
    )


def _clock(bundle: EvidenceBundle, case_id: str) -> EvidenceItem | None:
    return next(
        (
            i
            for i in bundle.items
            if i.kind == "decision_clock" and case_id in i.entity_ids and i.trust not in UNTRUSTED
        ),
        None,
    )


def cascade_links(
    bundle: EvidenceBundle, water: EvidenceItem | None, bwa_ref: str | None
) -> list[dict[str, Any]]:
    """The PS-17 cascade as ordered links, each pointing at the evidence item and basis that carries it."""

    def ref(case_id: str) -> str | None:
        item = _clock(bundle, case_id)
        return item.id if item else None

    power = _clock(bundle, ps17.CASE_POWER)
    return [
        {
            "step": "feeder_risk",
            "label": "PS-17 feeder exposure",
            "evidence_id": ref(ps17.CASE_POWER),
            "basis_id": "outage.ps17_feeder_exposure",
        },
        {
            "step": "generator",
            "label": "portable generator hookup at PS-17",
            "evidence_id": ref(ps17.CASE_POWER),
            "basis_id": "lead_time.portable_generator_hookup",
        },
        {
            "step": "fuel",
            "label": "fuel truck to PS-17",
            "evidence_id": ref(ps17.CASE_FUEL),
            "basis_id": "water_twin.portable_generator_fuel",
        },
        {
            "step": "tank_drain",
            "label": "zone tank drain to the floor",
            "evidence_id": ref(ps17.CASE_PRESSURE),
            "basis_id": power.citation.split(" - ")[0] if power else None,
        },
        {
            "step": "pressure_floor",
            "label": "pressure floor at the hospital service connection",
            "evidence_id": water.id if water else None,
            "basis_id": "rule.sc_service_pressure_normal",
        },
        {
            "step": "boil_water",
            "label": "precautionary boil water advisory",
            "evidence_id": bwa_ref,
            "basis_id": "rule.sc_bwa_pre_landfall",
        },
    ]


@node("rules")
async def rules(state: WaterState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    """Code, not the model, raises the proposals: rule.ps17_pressure_floor (cross-domain priority) and the
    BWA rules engine (SC pre-landfall; pressure readings at service connections when present)."""
    deps = _deps(runtime)
    bundle = EvidenceBundle.model_validate(state["bundle"])
    advisory = _ctx(state, deps)["advisory"]
    z = zone_status(deps, advisory)
    link = priority.ps17_link(deps.network)
    queue, now = es.clock_queue(deps.member_table, advisory)
    power_case = queue.cases[PRIORITY_CASE].case
    water = next((i for i in bundle.items if i.kind == "water_continuity"), None)
    items = list(bundle.items)
    proposals: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []

    prio = priority.evaluate(
        link,
        verdict=NoRegretVerdict(power_case.no_regret_verdict),
        on_critical_path=power_case.on_critical_path,
        p_loss=z.p_loss,
        case_id=PRIORITY_CASE,
    )
    prio_item = EvidenceItem(
        id=f"E{len(items) + 1}",
        kind="priority_rule",
        label=f"Cross-domain priority rule for {link.feeder_id} and {link.station_id}: customers plus the "
        f"hospital counted through its water",
        as_of=now,
        model_version=f"{priority.RULE_ID} ranking.ce",
        citation=priority.RULE_ID,
        classification=Classification.C1,
        trust=Trust.SYSTEM,
        values=(
            {
                "ce_customers": SlotValue(value=prio.params["ce_customers"], format="count"),
                "ce_critical": SlotValue(value=prio.params["ce_critical"], format="count"),
                "ce_expected_impact": SlotValue(value=prio.params["ce_expected_impact"], format="count"),
            }
            if prio.fires
            else {}
        ),
        hints={"fires": "yes" if prio.fires else "no"},
        entity_ids=[link.feeder_id, link.station_id, link.critical_customer_id],
    )
    items.append(prio_item)
    clock = _clock(bundle, PRIORITY_CASE)
    if prio.fires and clock is not None:
        request = ProposalCreate(
            decision_case_id=PRIORITY_CASE,
            action_type=ActionType.CROSS_DOMAIN_PRIORITY,
            params=prio.params,
            target_ids=list(prio.target_ids),
            evidence_ids=sorted({clock.id, prio_item.id, *([water.id] if water else [])}),
        )
        c = _policy(request, priority.PROPOSER)
        pol = _policy_item(len(items) + 1, c, now, "cross-domain priority")
        items.append(pol)
        proposals.append(
            {
                "request": request.model_dump(mode="json"),
                "proposer": priority.PROPOSER,
                "tier": c.tier,
                "what": "cross-domain priority",
                "include": sorted({*request.evidence_ids, pol.id}, key=lambda e: int(e[1:])),
            }
        )
    audit.append({"kind": "rule", "rule_id": priority.RULE_ID, "fires": prio.fires, "reason": prio.reason})

    hits: list[bwa.RuleHit] = bwa.pressure_hits(STATE, z.zone_id, deps.readings)
    pre = bwa.pre_landfall_hit(
        state=STATE,
        zone_id=z.zone_id,
        now=now,
        landfall_utc=deps.landfall_utc,
        breach_p=z.breach_p,
        on_backup_or_exposed=z.on_backup_or_exposed,
    )
    if pre is not None:
        hits.append(pre)
    hit = min(hits, key=lambda h: (h.due_utc or now, h.clause.clause_id)) if hits else None
    pre_clause = bwa.rulebook().clause("SC-A2")
    bwa_values: dict[str, SlotValue] = {
        "threshold": SlotValue(value=_ppm(float(_threshold())), format="percent_ppm"),
        "landfall": SlotValue(value=deps.landfall_utc, format="utc_minute"),
    }
    clause = hit.clause if hit else pre_clause
    bwa_values["clause"] = SlotValue(value=bwa.clause_text(clause, now), format="text")
    if hit is not None and hit.due_utc is not None:
        bwa_values["due"] = SlotValue(value=hit.due_utc, format="utc_minute")
    bwa_item = EvidenceItem(
        id=f"E{len(items) + 1}",
        kind="bwa_rule",
        label=f"Boil water rules for the {ZONE_NAME} water zone (state rules engine)",
        as_of=now,
        model_version=f"sgw.rules.bwa {bwa.rulebook().version}",
        citation=clause.rule_id,
        classification=Classification.C1,
        trust=Trust.SYSTEM,
        values=bwa_values,
        hints={
            "fires": "yes" if hit else "no",
            "notice_kind": hit.kind.value if hit else "none",
            "cause": hit.cause.value if hit else "none",
            "avoidable_by": "generator_prestaging"
            if z.sensitivity[PRESTAGED_LAG_MIN] < _threshold() <= z.breach_p
            else "none",
        },
        entity_ids=[z.zone_id],
    )
    items.append(bwa_item)
    notice: dict[str, Any] | None = None
    tasks: list[dict[str, Any]] = []
    sens = next((i for i in bundle.items if i.kind == "hookup_sensitivity"), None)
    if hit is not None:
        draft = bwa.notice_draft(
            hit,
            zone_name=ZONE_NAME,
            as_of=now,
            cause_text="Because Hurricane Helene may cause a loss of water pressure in this zone, SGW is "
            "issuing this precautionary advisory before landfall."
            if hit.cause is bwa.Cause.PRE_HURRICANE
            else "Water pressure in this zone fell below the state minimum.",
        )
        notice = {**draft.__dict__, "rule_id": hit.clause.rule_id, "zone_id": z.zone_id}
        tasks = [
            {**t.__dict__, "due_utc": t.due_utc.isoformat() if t.due_utc else None}
            for t in bwa.lifecycle_tasks(hit, critical_customers=[link.critical_customer_id])
        ]
        request = ProposalCreate(
            decision_case_id=BWA_CASE,
            action_type=ActionType.BOIL_WATER_NOTICE,
            params={
                "rule_id": hit.clause.rule_id,
                "clause_id": hit.clause.clause_id,
                "clause": draft.clause,
                "notice_kind": hit.kind.value,
                "cause": hit.cause.value,
                "state": STATE.value,
                "zone_id": z.zone_id,
                "template": draft.template,
                "title": draft.title,
            },
            target_ids=[z.zone_id],
            evidence_ids=sorted({bwa_item.id, *([water.id] if water else [])}, key=lambda e: int(e[1:])),
        )
        proposer = BWA_PROPOSERS[hit.cause]
        c = _policy(request, proposer)
        pol = _policy_item(len(items) + 1, c, now, "boil water advisory")
        items.append(pol)
        proposals.append(
            {
                "request": request.model_dump(mode="json"),
                "proposer": proposer,
                "tier": c.tier,
                "what": "boil water advisory",
                "include": sorted(
                    {*request.evidence_ids, pol.id, *([sens.id] if sens else [])},
                    key=lambda e: int(e[1:]),
                ),
            }
        )
    audit.append(
        {
            "kind": "rule",
            "rule_id": clause.rule_id,
            "fires": hit is not None,
            "breach_p_ppm": _ppm(z.breach_p),
            "breach_p_ppm_by_hookup_lag": {str(k): _ppm(v) for k, v in z.sensitivity.items()},
            "hookup_lag_min": z.hookup_lag_min,
            "clauses": [h.clause.clause_id for h in hits],
        }
    )
    new_bundle = EvidenceBundle(run_id=bundle.run_id, items=items)
    cascade = cascade_links(new_bundle, water, bwa_item.id if hit else None)
    emit("artifact", {"kind": "cascade", "links": cascade}, Classification.C1)
    if notice is not None:
        emit("artifact", {"kind": "bwa_notice_draft", **notice}, Classification.C1)
        emit("artifact", {"kind": "lifecycle_tasks", "tasks": tasks}, Classification.C1)
    notes = state.get("notes") or []
    for note in notes:
        new_bundle.items.append(es.note_item(len(new_bundle.items) + 1, note, now))
    values = slot_values(new_bundle)
    emit(
        "artifact",
        {
            "kind": "evidence",
            "items": [
                {
                    "id": i.id,
                    "kind": i.kind,
                    "label": i.label,
                    "trust": i.trust.value,
                    "citation": i.citation,
                    "values": values[i.id],
                }
                for i in new_bundle.items
            ],
        },
        Classification.C2,
    )
    view = build_view(new_bundle, route=deps.route)
    return {
        "bundle": new_bundle.model_dump(mode="json"),
        "view": view.model_dump(mode="json"),
        "proposals": proposals,
        "rule_results": {"priority": prio.reason, "bwa": [h.clause.clause_id for h in hits]},
        "cascade": cascade,
        "notice": notice,
        "tasks": tasks,
        "audit": audit,
    }


def _threshold() -> float:
    from sgw.common import numbers as numbers_mod

    return float(numbers_mod.value("policy_pre_landfall_breach_p"))


def water_sentences(bundle: EvidenceBundle) -> list[str]:
    """M2 sentences for the water items, slots only, so the template brief covers the cascade too."""
    out: list[str] = []
    for i in bundle.items:
        r = i.id
        if i.kind == "water_continuity":
            out.append(
                "Forecast at the hospital service connection: the chance of pressure below the "
                f"{{{r}.floor}} floor is {{{r}.breach_p}}, from a power-loss chance of "
                f"{{{r}.power_loss_p}} and {{{r}.breach_given_loss_p}} after a loss with the generator "
                f"hooked up {{{r}.hookup_lag}} later."
            )
        elif i.kind == "priority_rule" and i.hints.get("fires") == "yes":
            out.append(
                "The cross-domain priority rule proposes feeder and generator priority: "
                f"{{{r}.ce_customers}} customers plus {{{r}.ce_critical}} customer equivalents for the "
                f"hospital through its water, expected impact {{{r}.ce_expected_impact}}."
            )
        elif i.kind == "bwa_rule" and i.hints.get("fires") == "yes":
            out.append(
                f"The state rules call for a precautionary boil water advisory by {{{r}.due}} under "
                f"{{{r}.clause}}; the draft notice and its tasks wait for approval."
            )
        elif i.kind == "bwa_rule":
            out.append(
                f"The boil water rules do not call for an advisory yet: the forecast stays below the "
                f"{{{r}.threshold}} policy threshold."
            )
    return out


TIME_AS_REASON = re.compile(r"\b(because|since|against|due\s+to)\s+(?:of\s+|the\s+)?\{(E\d+)\.(\w+)\}", re.I)
TIME_WITH_RANGE = re.compile(
    r"\{(E\d+)\.(\w+)\}[^{}.;]{0,40}?\((?:range\s+|between\s+|from\s+)?\{(E\d+)\.(\w+)\}\s*(?:to|and|-)\s*"
    r"\{(E\d+)\.(\w+)\}\)",
    re.I,
)


def approver_text_problems(text: str, bundle: EvidenceBundle) -> list[str]:
    """Meaning checks the D-073 verifier cannot make: a clock time is never given as a reason ("because
    {E1.consequence}"), and a time shown with a range lies inside that range."""
    items = bundle.by_id()

    def slot(ref: str, fld: str) -> SlotValue | None:
        item = items.get(ref)
        return item.values.get(fld) if item else None

    problems: list[str] = []
    for m in TIME_AS_REASON.finditer(text):
        v = slot(m[2], m[3])
        if v is not None and v.format == "utc_minute":
            problems.append(f"time_as_reason: {m[1]} {{{m[2]}.{m[3]}}}")
    for m in TIME_WITH_RANGE.finditer(text):
        shown, lo, hi = slot(m[1], m[2]), slot(m[3], m[4]), slot(m[5], m[6])
        if None in (shown, lo, hi) or any(x.format != "utc_minute" for x in (shown, lo, hi)):  # type: ignore[union-attr]
            continue
        assert shown is not None and lo is not None and hi is not None
        if not lo.value <= shown.value <= hi.value:  # type: ignore[operator]
            problems.append(
                f"time_outside_range: {{{m[1]}.{m[2]}}} not in {{{m[3]}.{m[4]}}}..{{{m[5]}.{m[6]}}}"
            )
    return problems


def _m2_brief(state: WaterState, deps: SpineDeps) -> tuple[str, dict[str, str], str]:
    bundle, view = spine._bundle(state), spine._view(state)
    base = narrate_template(bundle, [r.ref.id for r in view.refs])
    head, sep, tail = base.partition(M2_NOTE)
    text = " ".join([head.strip(), *water_sentences(bundle), sep]).strip() + tail
    problems = verify(text, view.fields(), spine._ids(state, deps)) + approver_text_problems(text, bundle)
    if problems:
        raise RuntimeError(f"water M2 template fails the verifier: {[str(p) for p in problems]}")
    values = slot_values(bundle)
    return text, used_values(text, values), render_text(text, values)


@node("narrate", llm=True)
async def narrate_node(state: WaterState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    out: dict[str, Any] = await spine.narrate_node.__wrapped__(state, runtime)  # type: ignore[attr-defined]
    n = out["narrative"]
    meaning = approver_text_problems(n["text"], spine._bundle(state)) if n["path"] == "llm" else []
    if n["path"] == "llm" and not meaning:
        return out
    text, shown, rendered = _m2_brief(state, runtime.context)
    if meaning:
        n.update(path="m2", reason="verifier_rejected", violations=meaning)
        out["audit"] = [
            {**out["audit"][0], "path": "m2", "reason": "verifier_rejected", "violations": meaning}
        ]
    n.update(text=text, rendered=rendered, slots_shown=shown)
    return out


def bwa_rationale_template(sub: EvidenceBundle) -> dict[str, Any]:
    """M2 rationale for the advisory, bound on the rule deadline (landfall), not on a pressure clock."""
    rule = next(i for i in sub.items if i.kind == "bwa_rule")
    w = next((i for i in sub.items if i.kind == "water_continuity"), None)
    pol = next((i for i in sub.items if i.kind == "approval_policy"), None)
    r = rule.id
    text = (
        f"The state rules call for a precautionary boil water advisory before landfall, due by {{{r}.due}} "
        f"under {{{r}.clause}}."
    )
    ids = [r]
    if w is not None:
        text += (
            f" The forecast chance of pressure below the {{{w.id}.floor}} floor at the hospital service "
            f"connection is {{{w.id}.breach_p}}, against the {{{r}.threshold}} policy threshold."
        )
        ids.append(w.id)
    if pol is not None:
        text += (
            f" The approval policy sets tier {{{pol.id}.tier}}; it needs {{{pol.id}.approver_functions}}; "
            "the approvers decide."
        )
        ids.append(pol.id)
    text += " " + M2_NOTE
    return {
        "rationale": text,
        "preconditions": M2_PRECONDITIONS[ActionType.BOIL_WATER_NOTICE.value],
        "evidence_ids": ids,
    }


def prestaging_sentence(sub: EvidenceBundle) -> tuple[str, list[str]] | None:
    """Code-written: what pre-staging the generator (the priority proposal) does to the advisory's trigger."""
    rule = next((i for i in sub.items if i.kind == "bwa_rule"), None)
    w = next((i for i in sub.items if i.kind == "hookup_sensitivity"), None)
    if rule is None or w is None or f"breach_p_lag_{PRESTAGED_LAG_MIN}" not in w.values:
        return None
    lag, p = f"{{{w.id}.lag_{PRESTAGED_LAG_MIN}}}", f"{{{w.id}.breach_p_lag_{PRESTAGED_LAG_MIN}}}"
    if rule.hints.get("avoidable_by") == "generator_prestaging":
        text = (
            "If the generator is pre-staged under the cross-domain priority proposal and hooked up within "
            f"{lag} of a loss, the forecast chance falls to {p}, below the {{{rule.id}.threshold}} "
            "threshold, so the advisory may not be needed."
        )
    else:
        text = (
            f"Pre-staging the generator (hookup within {lag} of a loss) would put the forecast chance at {p} "
            f"against the {{{rule.id}.threshold}} threshold."
        )
    return text, [rule.id, w.id]


def _sub(state: WaterState, include: list[str], route: str) -> tuple[EvidenceBundle, Any]:
    bundle = EvidenceBundle.model_validate(state["bundle"])
    sub = EvidenceBundle(run_id=bundle.run_id, items=[i for i in bundle.items if i.id in include])
    return sub, build_view(sub, route=route)


@node("draft_rationale", llm=True)
async def rationale_node(state: WaterState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    """One rationale per proposal, each on the evidence its proposal cites plus its policy item."""
    deps = _deps(runtime)
    outs: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    for p in state.get("proposals") or []:
        sub, view = _sub(state, p["include"], deps.route)
        proposal = {**p["request"], "tier": p["tier"]}
        out = (
            await draft_rationale(
                client=gated(deps.llm, deps.llm_gate),
                config=node_config("draft_rationale", deps.nodes_file),
                bundle=sub,
                view=view,
                ids=spine._ids(state, deps),
                proposal=proposal,
                run_id=state.get("run_id"),
                model_override=deps.model_overrides.get("draft_rationale"),
            )
        ).as_state()
        action = p["request"]["action_type"]
        meaning = approver_text_problems(out["text"], sub) if out["path"] == "llm" else []
        if meaning:
            out.update(path="m2", reason="verifier_rejected", violations=meaning)
            out["structured"] = rationale_template(proposal, sub)
            out["text"] = out["structured"]["rationale"]
        if out["path"] == "m2" and action == ActionType.BOIL_WATER_NOTICE.value:
            out["structured"] = bwa_rationale_template(sub)
            out["text"] = out["structured"]["rationale"]
        elif out["path"] == "m2" and out.get("structured"):
            out["structured"]["preconditions"] = M2_PRECONDITIONS[action]
        extra = prestaging_sentence(sub) if action == ActionType.BOIL_WATER_NOTICE.value else None
        if extra is not None:
            head, sep, tail = out["text"].partition(M2_NOTE)
            out["text"] = f"{head.strip()} {extra[0]} {sep}".strip() + tail
            ids = out["structured"]["evidence_ids"]
            out["structured"]["evidence_ids"] = [*ids, *(e for e in extra[1] if e not in ids)]
        values = slot_values(sub)
        out.update(rendered=render_text(out["text"], values), slots_shown=used_values(out["text"], values))
        out["action_type"] = action
        outs.append(out)
        alerts += out["alerts"]
        audit.append(
            {
                "kind": "draft_rationale",
                "action_type": out["action_type"],
                "path": out["path"],
                "reason": out["reason"],
                "violations": out["violations"],
            }
        )
    return {"rationales": outs, "alerts": alerts, "audit": audit}


@node("verify")
async def verify_node(state: WaterState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    """Re-verify every text that will be shown, against the view it was written from, and re-derive the
    values it shows; only then emit it."""
    deps = _deps(runtime)
    ids = spine._ids(state, deps)
    problems: list[str] = []
    n = state.get("narrative") or {}
    if n:
        view = spine._view(state)
        problems += [f"narrative: {p}" for p in verify(n["text"], view.fields(), ids)]
        problems += [f"narrative: {p}" for p in approver_text_problems(n["text"], spine._bundle(state))]
        if used_values(n["text"], slot_values(spine._bundle(state))) != n["slots_shown"]:
            problems.append("narrative: slot values differ from the evidence")
    proposals = {p["request"]["action_type"]: p for p in state.get("proposals") or []}
    for r in state.get("rationales") or []:
        sub, view = _sub(state, proposals[r["action_type"]]["include"], deps.route)
        problems += [f"rationale {r['action_type']}: {p}" for p in verify(r["text"], view.fields(), ids)]
        if used_values(r["text"], slot_values(sub)) != r["slots_shown"]:
            problems.append(f"rationale {r['action_type']}: slot values differ from the evidence")
        problems += [f"rationale {r['action_type']}: {p}" for p in approver_text_problems(r["text"], sub)]
        if r["path"] == "llm" and r.get("structured"):
            problems += [
                f"rationale {r['action_type']}: {p}"
                for p in rationale_problems(RationaleOut.model_validate(r["structured"]), view, ids)
            ]
    if problems:
        return {"status": "blocked", "audit": [{"kind": "verify", "passed": False, "problems": problems}]}
    if n:
        spine._emit_text(n, "brief")
    for r in state.get("rationales") or []:
        emit(
            "artifact",
            {
                "kind": "rationale",
                "action_type": r["action_type"],
                "path": r["path"],
                "rendered": r["rendered"],
                "structured": r["structured"],
            },
            Classification.C2,
        )
    return {"audit": [{"kind": "verify", "passed": True}]}


@node("policy_gate")
async def policy_gate(state: WaterState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    deps = _deps(runtime)
    proposals = state.get("proposals") or []
    if not proposals or state.get("status") == "blocked":
        blocked = state.get("status") == "blocked"
        return {"approvals": [], "status": "blocked" if blocked else "no_action"}
    rationale = {r["action_type"]: r.get("rendered", "") for r in state.get("rationales") or []}
    tainted = bool(state.get("tainted"))
    approvals: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for p in proposals:
        request = ProposalCreate.model_validate(p["request"])
        try:
            drafted = deps.rule_port.draft(
                request,
                proposer=p["proposer"],
                rationale=rationale.get(request.action_type.value, ""),
                run_id=state["run_id"],
                tainted=tainted,
            )
        except PolicyDenied as exc:
            audit.append(
                {"kind": "policy_gate", "allowed": False, "deny": list(exc.deny), "proposer": p["proposer"]}
            )
            continue
        payload = drafted.payload.model_dump(mode="json")
        if payload["tier"] != p["tier"]:
            audit.append(
                {
                    "kind": "policy_gate",
                    "allowed": False,
                    "deny": ["tier_differs_from_shown_text"],
                    "proposal_id": payload["proposal_id"],
                }
            )
            continue
        emit("approval_required", {**payload, "tainted": tainted})
        approvals.append(
            {
                **payload,
                "action_type": request.action_type.value,
                "proposer": p["proposer"],
                "escalators": list(drafted.escalators),
                "tainted": tainted,
            }
        )
        audit.append(
            {
                "kind": "policy_gate",
                "allowed": True,
                "proposal_id": payload["proposal_id"],
                "tier": payload["tier"],
                "proposer": p["proposer"],
                "initiator_kind": InitiatorKind.SYSTEM_RULE.value,
            }
        )
    status = "awaiting_approval" if approvals else "blocked"
    return {"approvals": approvals, "status": status, "audit": audit}


def after_gate(state: WaterState) -> str:
    return "approval" if state.get("approvals") else "audit"


@node("approval")
async def approval(state: WaterState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    """Pause until people act; the resume value is a wake-up signal only and is never read as an approval."""
    claim = interrupt({"reason": "approval_required", "approvals": state.get("approvals")})
    return {"audit": [{"kind": "resume", "claim_ignored": str(claim)[:200]}]}


@node("execute")
async def execute(state: WaterState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    deps = _deps(runtime)
    pending = False
    done: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for a in state.get("approvals") or []:
        pid = str(a["proposal_id"])
        store_state, version, action_hash = deps.rule_port.approval_state(pid)
        bound = version == a["proposal_version"] and action_hash == a["action_hash"]
        if store_state in EXECUTED_STATES and bound:
            effect = deps.rule_port.record_effect(pid, state["run_id"])
            done.append({"proposal_id": pid, "effect_id": effect, "simulated": True})
            audit.append({"kind": "execute", "proposal_id": pid, "effect_id": effect})
        else:
            pending = pending or store_state in ("proposed", "in_review", "draft")
            audit.append(
                {"kind": "execute_refused", "proposal_id": pid, "store_state": store_state, "bound": bound}
            )
    if pending:
        return {"status": "awaiting_approval", "execution": {"effects": done}, "audit": audit}
    total = len(state.get("approvals") or [])
    return {
        "status": "executed" if len(done) == total else "blocked",
        "execution": {"effects": done},
        "audit": audit,
    }


def after_execute(state: WaterState) -> str:
    return "approval" if state.get("status") == "awaiting_approval" else "audit"


@node("audit")
async def audit(state: WaterState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    return {
        "audit": [
            {"kind": "run_end", "status": state.get("status"), "alerts": len(state.get("alerts") or [])}
        ]
    }


def build(checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    g: Any = StateGraph(WaterState, context_schema=SpineDeps)
    g.add_node("load_context", load_context)
    g.add_node("input_guard", spine.input_guard)
    g.add_node("call_tool", call_tool)
    g.add_node("fuse", fuse)
    g.add_node("rules", rules)
    g.add_node("narrate", narrate_node)
    g.add_node("draft_rationale", rationale_node)
    g.add_node("verify", verify_node)
    g.add_node("policy_gate", policy_gate)
    g.add_node("approval", approval)
    g.add_node("execute", execute)
    g.add_node("audit", audit)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "input_guard")
    g.add_conditional_edges("input_guard", collect_evidence, ["call_tool"])
    g.add_edge("call_tool", "fuse")
    g.add_edge("fuse", "rules")
    g.add_edge("rules", "narrate")
    g.add_edge("narrate", "draft_rationale")
    g.add_edge("draft_rationale", "verify")
    g.add_edge("verify", "policy_gate")
    g.add_conditional_edges("policy_gate", after_gate, ["approval", "audit"])
    g.add_edge("approval", "execute")
    g.add_conditional_edges("execute", after_execute, ["approval", "audit"])
    g.add_edge("audit", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())
