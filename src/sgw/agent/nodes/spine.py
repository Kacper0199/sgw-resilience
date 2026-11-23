"""Shared spine nodes (DC-08): load_context -> input_guard -> collect_evidence (Send fan-out over
deterministic tool calls) -> fuse -> optimise -> narrate (LLM) -> draft_rationale (LLM) -> verify ->
policy_gate -> approval (interrupt) -> execute -> audit.

State is plain JSON so a checkpoint can be replayed. Dependencies (gateway client, proposal port, member
table) come through the LangGraph runtime context, never through state, so a client cannot inject them.
Nodes emit K4 run events through the stream writer; only verified, rendered text is ever emitted.
"""

from __future__ import annotations

import json
import operator
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache, wraps
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime
from langgraph.types import Send, interrupt
from opentelemetry import trace

from sgw.agent.nodes import evidence_source as es
from sgw.agent.nodes.gate import GateCheck, gated
from sgw.agent.nodes.llm import NODES_FILE, LlmClient, node_config
from sgw.agent.nodes.ports import EXECUTED_STATES, PolicyDenied, ProposalPort
from sgw.agent.nodes.text_nodes import RationaleOut, draft_rationale, narrate, rationale_problems
from sgw.agent.render.evidence import (
    UNTRUSTED,
    EvidenceBundle,
    EvidenceItem,
    EvidenceView,
    SlotValue,
    build_view,
)
from sgw.agent.render.slots import slot_values, used_values
from sgw.agent.render.verify import known_ids, verify
from sgw.approval.policy import Classification as PolicyClassification
from sgw.approval.policy import ReferencePolicy
from sgw.common.telemetry import sgw_span
from sgw.contracts.api_models import ProposalCreate
from sgw.contracts.vocab import ActionType, Classification, RunMode, Trust

NETWORK_FILE = Path(__file__).resolve().parents[4] / "data" / "fixtures" / "helene" / "network.json"
ALLOWED_INPUT = frozenset({"advisory", "notes", "event_type_inputs", "region_id"})
ZERO_WIDTH = re.compile("[​-‏⁠-⁤﻿]")
CREWS_CASE = "DC-D2-CREWS-AIK"
CREWS_YARDS = ("STG-AIK-SANDHILL-YARD", "STG-RCH-MILLPOND-YARD")


@dataclass
class SpineDeps:
    llm: LlmClient
    proposals: ProposalPort
    member_table: Mapping[str, Any]
    nodes_file: Path = NODES_FILE
    route: str = "R1"
    extra_ids: frozenset[str] = frozenset()
    model_overrides: dict[str, str] = field(default_factory=dict)
    policy_evidence: bool = True
    llm_gate: GateCheck | None = None


class SpineState(TypedDict, total=False):
    run_id: str
    thread_id: str
    user_id: str
    user_role: str
    run_mode: str
    graph: str
    phase: str
    input: dict[str, Any]
    task: dict[str, Any]
    tainted: bool
    notes: list[dict[str, Any]]
    tool_results: Annotated[list[dict[str, Any]], operator.add]
    alerts: Annotated[list[dict[str, Any]], operator.add]
    audit: Annotated[list[dict[str, Any]], operator.add]
    bundle: dict[str, Any]
    view: dict[str, Any]
    proposal: dict[str, Any] | None
    narrative: dict[str, Any]
    rationale: dict[str, Any]
    approval: dict[str, Any] | None
    status: str
    execution: dict[str, Any]


Node = Callable[[SpineState, Runtime[SpineDeps]], Awaitable[dict[str, Any]]]


def emit(event: str, payload: dict[str, Any], classification: Classification = Classification.C1) -> None:
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    writer({"event": event, "payload": payload, "classification": classification.value})


def node(name: str, *, llm: bool = False) -> Callable[[Node], Node]:
    """K12 span and K4 step/agent events around a node."""

    def wrap(fn: Node) -> Node:
        @wraps(fn)
        async def inner(state: SpineState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
            emit("agent_start" if llm else "step", {"node": name, "status": "start"})
            with sgw_span(
                f"agent.{name}",
                run_id=state.get("run_id"),
                classification=Classification.C1,
                user_role=state.get("user_role", "unknown"),
                run_mode=RunMode(state.get("run_mode", RunMode.REPLAY.value)),
                node=name,
            ):
                out = await fn(state, runtime)
            emit("agent_end" if llm else "step", {"node": name, "status": "end"})
            return out

        return inner

    return wrap


def _mark_path(out: dict[str, Any]) -> None:
    trace.get_current_span().set_attribute("sgw.llm_path", out["path"])


def _audit(kind: str, **fields: Any) -> list[dict[str, Any]]:
    return [{"kind": kind, **fields}]


def _bundle(state: SpineState) -> EvidenceBundle:
    return EvidenceBundle.model_validate(state["bundle"])


def _view(state: SpineState) -> EvidenceView:
    return EvidenceView.model_validate(state["view"])


def _ids(state: SpineState, deps: SpineDeps) -> frozenset[str]:
    """Ids of the run's evidence bundle (its E-refs and the entities they are about), the asset and
    document registry, and the closed code vocabulary."""
    bundle = _bundle(state)
    return known_ids(bundle.entity_ids() | {i.id for i in bundle.items}, deps.extra_ids)


@node("load_context")
async def load_context(state: SpineState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    raw = dict(state.get("input") or {})
    advisory = str(raw.get("advisory", "N+1"))
    if advisory not in runtime.context.member_table.get("advisories", {}):
        raise ValueError(f"advisory {advisory!r} has no member table")
    return {
        "phase": "pre-landfall assessment (D1 event type, D2 crew pre-positioning, PS-17 chain)",
        "status": "running",
        "audit": _audit("run_start", graph=state.get("graph", "assess"), user_id=state.get("user_id")),
    }


def _clean(text: str) -> str:
    return ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", text))


@node("input_guard")
async def input_guard(state: SpineState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    """Untrusted text never reaches a privileged node: notes are normalised, kept as quarantined evidence and
    taint the run (DC-38, SEC-01/03). Input keys outside the graph's schema (a forged `approved`, `role` or
    `tier`) are dropped and audited (SEC-21)."""
    raw = dict(state.get("input") or {})
    ignored = sorted(set(raw) - ALLOWED_INPUT)
    notes = [
        {"text": _clean(str(n.get("text", ""))), "source": str(n.get("source", "fsm"))[:64]}
        for n in raw.get("notes") or []
        if isinstance(n, Mapping)
    ]
    audit = _audit("input_guard", notes=len(notes), ignored_keys=ignored)
    if notes:
        audit += _audit("taint", reason="untrusted free text in run input", notes=len(notes))
    clean = {k: raw[k] for k in ALLOWED_INPUT if k in raw}
    clean["notes"] = notes
    return {"input": clean, "notes": notes, "tainted": bool(notes), "audit": audit}


def _ctx(state: SpineState, deps: SpineDeps) -> dict[str, Any]:
    raw = state.get("input") or {}
    return {
        "member_table": deps.member_table,
        "advisory": str(raw.get("advisory", "N+1")),
        "event_type_inputs": raw.get("event_type_inputs"),
        "region_id": raw.get("region_id", "SC-45003"),
    }


def collect_evidence(state: SpineState, runtime: Runtime[SpineDeps]) -> list[Send]:
    """Fan-out: one deterministic tool call per planned item; code, not a model, picks the calls."""
    calls = es.plan_calls(_ctx(state, runtime.context))
    return [
        Send("call_tool", {**state, "task": {"tool": name, "args": args, "n": i}})
        for i, (name, args) in enumerate(calls)
    ]


@node("call_tool")
async def call_tool(state: SpineState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    task = state["task"]
    name, args = str(task["tool"]), dict(task["args"])
    emit("tool_start", {"tool": name, "args": args, "call": task["n"]})
    try:
        results = es.call_tool(name, args, _ctx(state, runtime.context))
    except es.UnknownTool as exc:
        alert = {"code": "SEC-13", "kind": "unregistered_tool", "tool": exc.name[:64]}
        emit("tool_end", {"tool": name, "call": task["n"], "status": "refused"})
        return {"alerts": [alert], "audit": _audit("security_alert", alert=alert)}
    emit("tool_end", {"tool": name, "call": task["n"], "status": "ok", "results": len(results)})
    return {"tool_results": results, "audit": _audit("tool_call", tool=name, args=args, results=len(results))}


@node("fuse")
async def fuse(state: SpineState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    deps = runtime.context
    results = sorted(state.get("tool_results") or [], key=lambda r: json.dumps(r, sort_keys=True))
    items = es.build_items(results, _ctx(state, deps), state.get("notes") or [])
    bundle = EvidenceBundle(run_id=state["run_id"], items=items)
    view = build_view(bundle, route=deps.route)
    values = slot_values(bundle)
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
                for i in items
            ],
            "prompt_classes": [c.value for c in view.classes],
        },
        Classification.C2,
    )
    return {
        "bundle": bundle.model_dump(mode="json"),
        "view": view.model_dump(mode="json"),
        "audit": _audit("evidence", items=len(items), prompt_classes=view.header_value()),
    }


@lru_cache(maxsize=1)
def crews_by_yard() -> dict[str, list[str]]:
    named = json.loads(NETWORK_FILE.read_text(encoding="utf-8"))["named"]["crews"]
    out: dict[str, list[str]] = {}
    for crew, info in sorted(named.items()):
        out.setdefault(str(info["yard"]), []).append(crew)
    return out


@node("optimise")
async def optimise(state: SpineState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    """D2 crew pre-positioning. Until WP-16's SAA optimiser is on main this is the named baseline rule:
    stage the yard crews of record at the two detail yards before the crews clock (evidence-backed only)."""
    bundle = _bundle(state)
    clock = next(
        (
            i
            for i in bundle.items
            if i.kind == "decision_clock" and CREWS_CASE in i.entity_ids and i.trust not in UNTRUSTED
        ),
        None,
    )
    if clock is None:
        return {"proposal": None, "audit": _audit("optimise", result="no crews clock, no proposal")}
    crews = sorted(c for y in CREWS_YARDS for c in crews_by_yard().get(y, []))
    request = ProposalCreate(
        decision_case_id=CREWS_CASE,
        action_type=ActionType.PREPOSITION_CREWS,
        params={"crew_ids": crews, "plan_source": "baseline_rule_pending_wp16"},
        target_ids=list(CREWS_YARDS),
        evidence_ids=[clock.id],
    )
    preview = policy_preview(request, state.get("user_id", "unknown"))
    out: dict[str, Any] = {
        "proposal": {**request.model_dump(mode="json"), "tier": preview.tier},
        "audit": _audit("optimise", result="baseline_rule", targets=list(CREWS_YARDS), tier=preview.tier),
    }
    if runtime.context.policy_evidence:
        item = policy_item(len(bundle.items) + 1, preview, clock.as_of)
        bundle = EvidenceBundle(run_id=bundle.run_id, items=[*bundle.items, item])
        out["bundle"] = bundle.model_dump(mode="json")
        out["view"] = build_view(bundle, route=runtime.context.route).model_dump(mode="json")
    return out


def policy_preview(request: ProposalCreate, proposed_by: str) -> PolicyClassification:
    """The approval policy's tier for this action (WP-09a's reference twin); policy_gate drafts through the
    port and refuses to go on if the store's tier differs, so text never shows a stale tier."""
    return ReferencePolicy().classify(
        {
            "action": "propose",
            "subject": {"user_id": proposed_by},
            "proposal": {
                "action_type": request.action_type.value,
                "proposed_by": proposed_by,
                "initiator_kind": "agent",
                "target_ids": list(request.target_ids),
            },
            "facts": {},
            "context": {"degraded_mode": "normal"},
        }
    )


def policy_item(n: int, c: PolicyClassification, as_of: Any) -> EvidenceItem:
    return EvidenceItem(
        id=f"E{n}",
        kind="approval_policy",
        label="Approval tier and approver functions for the proposed action (approval policy, code)",
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


def _emit_text(outcome: dict[str, Any], kind: str) -> None:
    for sentence in re.split(r"(?<=[.;])\s+", outcome["rendered"]):
        if sentence:
            emit("text_delta", {"node": outcome["node"], "text": sentence + " "}, Classification.C2)
    emit(
        "artifact",
        {
            "kind": kind,
            "path": outcome["path"],
            "reason": outcome.get("reason"),
            "rendered": outcome["rendered"],
            "slots": outcome["slots_shown"],
        },
        Classification.C2,
    )


@node("narrate", llm=True)
async def narrate_node(state: SpineState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    deps = runtime.context
    out = (
        await narrate(
            client=gated(deps.llm, deps.llm_gate),
            config=node_config("narrate", deps.nodes_file),
            bundle=_bundle(state),
            view=_view(state),
            ids=_ids(state, deps),
            phase=state.get("phase", "assessment"),
            run_id=state.get("run_id"),
            model_override=deps.model_overrides.get("narrate"),
        )
    ).as_state()
    _mark_path(out)
    return {
        "narrative": out,
        "alerts": out["alerts"],
        "audit": _audit("narrate", path=out["path"], reason=out["reason"], violations=out["violations"]),
    }


@node("draft_rationale", llm=True)
async def rationale_node(state: SpineState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    proposal = state.get("proposal")
    if not proposal:
        return {"rationale": {}}
    deps = runtime.context
    out = (
        await draft_rationale(
            client=gated(deps.llm, deps.llm_gate),
            config=node_config("draft_rationale", deps.nodes_file),
            bundle=_bundle(state),
            view=_view(state),
            ids=_ids(state, deps),
            proposal=proposal,
            run_id=state.get("run_id"),
            model_override=deps.model_overrides.get("draft_rationale"),
        )
    ).as_state()
    _mark_path(out)
    emit(
        "artifact",
        {
            "kind": "rationale",
            "path": out["path"],
            "rendered": out["rendered"],
            "structured": out["structured"],
        },
        Classification.C2,
    )
    return {
        "rationale": out,
        "alerts": out["alerts"],
        "audit": _audit(
            "draft_rationale", path=out["path"], reason=out["reason"], violations=out["violations"]
        ),
    }


@node("verify")
async def verify_node(state: SpineState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    """Defence in depth: re-verify every text that will be shown and re-derive the values it shows."""
    view, ids, values = _view(state), _ids(state, runtime.context), slot_values(_bundle(state))
    problems: list[str] = []
    for key in ("narrative", "rationale"):
        out: dict[str, Any] = dict(state.get(key) or {})  # type: ignore[call-overload]
        if not out:
            continue
        problems += [f"{key}: {p}" for p in verify(out["text"], view.fields(), ids)]
        if used_values(out["text"], values) != out["slots_shown"]:
            problems.append(f"{key}: slot values differ from the evidence")
    structured = (state.get("rationale") or {}).get("structured")
    if structured and (state.get("rationale") or {}).get("path") == "llm":
        problems += [
            f"rationale: {p}" for p in rationale_problems(RationaleOut.model_validate(structured), view, ids)
        ]
    if problems:
        return {"status": "blocked", "audit": _audit("verify", passed=False, problems=problems)}
    if state.get("narrative"):
        _emit_text(state["narrative"], "brief")
    r = state.get("rationale") or {}
    if r:
        emit(
            "artifact",
            {
                "kind": "rationale",
                "path": r["path"],
                "rendered": r["rendered"],
                "structured": r["structured"],
            },
            Classification.C2,
        )
    return {"audit": _audit("verify", passed=True)}


def proposal_facts(cited: Sequence[EvidenceItem]) -> dict[str, bool]:
    """Policy facts from the evidence a proposal cites. Evidence only from untrusted free text (notes,
    tickets, alert text, extracted field claims) raises a T2 action to T3 (`untrusted_evidence_only`,
    STM 4.5). The one rule for every graph; the extractor reuses it."""
    return {"untrusted_evidence_only": bool(cited) and all(i.trust in UNTRUSTED for i in cited)}


@node("policy_gate")
async def policy_gate(state: SpineState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    proposal = state.get("proposal")
    if not proposal or state.get("status") == "blocked":
        return {"approval": None, "status": state.get("status", "no_action") if proposal else "no_action"}
    bundle = _bundle(state).by_id()
    cited = [bundle[e] for e in proposal["evidence_ids"] if e in bundle]
    facts = proposal_facts(cited)
    rationale = (state.get("rationale") or {}).get("rendered", "")
    request = ProposalCreate.model_validate({k: v for k, v in proposal.items() if k != "tier"})
    try:
        drafted = runtime.context.proposals.draft(
            request,
            proposed_by=state.get("user_id", "unknown"),
            rationale=rationale,
            run_id=state["run_id"],
            facts=facts,
            tainted=bool(state.get("tainted")),
        )
    except PolicyDenied as exc:
        return {
            "approval": None,
            "status": "blocked",
            "audit": _audit("policy_gate", allowed=False, deny=list(exc.deny)),
        }
    payload = drafted.payload.model_dump(mode="json")
    tainted = bool(state.get("tainted"))
    if payload["tier"] != proposal["tier"]:
        return {
            "approval": None,
            "status": "blocked",
            "audit": _audit(
                "policy_gate",
                allowed=False,
                deny=["tier_differs_from_shown_text"],
                proposal_id=payload["proposal_id"],
                shown=proposal["tier"],
                store=payload["tier"],
            ),
        }
    emit("approval_required", {**payload, "tainted": tainted})
    return {
        "approval": {**payload, "escalators": list(drafted.escalators), "tainted": tainted},
        "status": "awaiting_approval",
        "audit": _audit(
            "policy_gate",
            allowed=True,
            proposal_id=payload["proposal_id"],
            tier=payload["tier"],
            tainted=bool(state.get("tainted")),
        ),
    }


def after_gate(state: SpineState) -> str:
    return "approval" if state.get("approval") else "audit"


@node("approval")
async def approval(state: SpineState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    """Pause until people act. The resume value is a wake-up signal only: it is audited and never read as an
    approval; `execute` asks the approval store."""
    claim = interrupt({"reason": "approval_required", "approval": state.get("approval")})
    return {"audit": _audit("resume", claim_ignored=str(claim)[:200])}


@node("execute")
async def execute(state: SpineState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    approval_ = state.get("approval") or {}
    pid = str(approval_.get("proposal_id", ""))
    store_state, version, action_hash = runtime.context.proposals.approval_state(pid)
    bound = version == approval_.get("proposal_version") and action_hash == approval_.get("action_hash")
    if store_state in EXECUTED_STATES and bound:
        effect = runtime.context.proposals.record_effect(pid, state["run_id"])
        return {
            "status": "executed",
            "execution": {"effect_id": effect, "simulated": True},
            "audit": _audit("execute", proposal_id=pid, effect_id=effect),
        }
    status = "awaiting_approval" if store_state in ("proposed", "in_review", "draft") else "blocked"
    return {
        "status": status,
        "execution": {},
        "audit": _audit("execute_refused", proposal_id=pid, store_state=store_state, bound=bound),
    }


def after_execute(state: SpineState) -> str:
    """A proposal still waiting in the store sends the run back to the interrupt; only the store's state,
    never the resume value, moves the run on."""
    return "approval" if state.get("status") == "awaiting_approval" else "audit"


@node("audit")
async def audit(state: SpineState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    return {"audit": _audit("run_end", status=state.get("status"), alerts=len(state.get("alerts") or []))}
