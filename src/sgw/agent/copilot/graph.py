"""`copilot` graph (K5 GRAPHS: workflow W9), two engines behind one graph id and API:
- `team` (AX F5): load_context -> route (N1) -> plan -> parallel workers (Send fan-out, at most
  three, an optional second wave) -> gather -> synthesise -> link -> respond -> audit;
- `single` (the R26 loop, the cut line, and the default until the team is recorded): load_context ->
  route -> investigate (N4) -> link -> respond -> audit.
Every LLM step has a code fallback: plan miss -> code plan; worker miss -> its code-fetched evidence;
synthesis miss or failed checks -> M2 over all evidence. Caps (`budget.py`): calls, USD, waves, wall clock.

Read-only end to end: no node drafts, proposes, approves or executes anything, and the graph has no
approval interrupt. The user turn is untrusted (guarded, taints the run when text is withheld); passages
marked `[field record, unverified]` also taint it. Only checked, rendered text leaves the graph, as a
`message` artifact. Input keys other than `question` and `as_of` are dropped and audited. `as_of` is the
scenario time the user is looking at (default: the scenario clock); role, ceiling and region come from the
run, never from the input. Tool calls stream as `tool_start`/`tool_end` while the loop runs. `link` turns the
ids the answer names into typed references (K3 `Message.references`), by code."""

from __future__ import annotations

import operator
import os
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime
from functools import wraps
from typing import Annotated, Any, TypedDict, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send

from sgw.agent.copilot.budget import (
    MAX_LLM_CALLS,
    MAX_TURN_USD,
    MAX_WAVES,
    SYNTH_CALLS,
    TURN_TIMEOUT_S,
    TYPICAL_STEP_USD,
    spent,
    steps_within,
    worst_case,
)
from sgw.agent.copilot.clock_state import advisories_over
from sgw.agent.copilot.guide import NODE as GUIDE
from sgw.agent.copilot.guide import (
    GuideInput,
    answer_links,
    guide_answer,
    helpful_not_found,
    not_found_text,
    scenario_questions,
)
from sgw.agent.copilot.investigate import NODE as INVESTIGATE
from sgw.agent.copilot.investigate import READ_ONLY, CopilotAnswer, investigate
from sgw.agent.copilot.link import evidence_refs, references
from sgw.agent.copilot.plain import (
    CODE_FIRST,
    PlainInput,
    decision_refs,
    framing,
    plain_answer,
    plain_title,
    reroutes,
)
from sgw.agent.copilot.plan import NODE as PLAN
from sgw.agent.copilot.plan import Plan, known_ids, make_plan
from sgw.agent.copilot.runner import LocalToolRunner, ToolRunner, default_runner
from sgw.agent.copilot.search import SearchFn, env_search
from sgw.agent.copilot.synthesis import NODE as SYNTH
from sgw.agent.copilot.synthesis import merge, synthesise
from sgw.agent.copilot.tools import CopilotTools, clock_context
from sgw.agent.copilot.workers import BY_NAME, WORKER_ORDER, WorkerSpec, WorkerTask, offered, run_worker
from sgw.agent.extract.guard import WITHHELD, guard_untrusted
from sgw.agent.nodes.llm import node_config
from sgw.agent.nodes.spine import SpineDeps, emit
from sgw.agent.rag.tool import UNVERIFIED
from sgw.agent.route.followup import NODE as CONTEXTUALISE
from sgw.agent.route.followup import standalone
from sgw.agent.route.gate import NODE as TRIAGE
from sgw.agent.route.gate import GateResult, triage, vague
from sgw.agent.route.intent import NODE as ROUTE
from sgw.agent.route.intent import Intent, RouteResult, route_intent
from sgw.common.telemetry import sgw_span
from sgw.contracts.api_models import AnswerReason, ScenarioPeriod
from sgw.contracts.tools import InjectedContext
from sgw.contracts.vocab import ApprovalFunction, Classification, RunMode

GRAPH_ID = "copilot"
ALLOWED_INPUT = frozenset({"question", "as_of", "history"})
MAX_HISTORY = 3
DEFAULT_AS_OF = datetime(2024, 9, 26, 15, 0, tzinfo=UTC)
MAX_QUESTION = 2000


ENGINES = frozenset({"team", "single"})
ENGINE_ENV = "SGW_COPILOT_ENGINE"


def default_engine() -> str:
    """`team` since the R29 freeze: the Ask eval prefers it (`data/artefacts/evals/ask_eval_v1.json`).
    `SGW_COPILOT_ENGINE=single` selects the single loop."""
    engine = os.environ.get(ENGINE_ENV, "team")
    return engine if engine in ENGINES else "team"


def period_line(scenario: str) -> str:
    """DX's scenario period sentence (`sgw.api.scenario_info`), which the plan, workers and synthesis read."""
    from sgw.api.scenario_info import scenario_period

    return scenario_period(scenario).statement


def scenario_period(scenario: str) -> ScenarioPeriod:
    from sgw.api.scenario_info import scenario_period as period

    return period(scenario)


def default_period() -> str:
    return period_line("helene")


@dataclass
class CopilotDeps(SpineDeps):
    search: SearchFn | None = None
    scenario_now: Callable[[], datetime] | None = None
    engine: str = field(default_factory=default_engine)
    runner: ToolRunner = field(default_factory=default_runner)
    period: str | None = None
    scenario: str = "helene"
    code_only: frozenset[str] = frozenset()


def with_clock(deps: SpineDeps, request: Any) -> CopilotDeps:
    """The run's deps plus the API's scenario clock, so `as_of` can never run ahead of the scenario."""
    api = getattr(getattr(getattr(request, "app", None), "state", None), "sgw", None)
    clock = getattr(api, "clock", None)
    base = {f.name: getattr(deps, f.name) for f in fields(SpineDeps)}
    sdef = getattr(clock, "definition", None)
    return CopilotDeps(
        **base,
        search=getattr(deps, "search", None),
        scenario_now=clock.now if clock is not None else getattr(deps, "scenario_now", None),
        period=period_line(sdef.name) if sdef is not None else None,
        scenario=sdef.name if sdef is not None else "helene",
        runner=default_runner(sdef.name if sdef is not None else "helene"),
    )


class CopilotState(TypedDict, total=False):
    run_id: str
    thread_id: str
    user_id: str
    user_role: str
    run_mode: str
    graph: str
    input: dict[str, Any]
    question: str
    as_of: str
    route: dict[str, Any]
    gate: dict[str, Any]
    history: list[dict[str, Any]]
    standalone: str
    answer: dict[str, Any]
    engine: str
    started: float
    plan: dict[str, Any]
    task: dict[str, Any]
    findings: Annotated[list[dict[str, Any]], operator.add]
    tainted: bool
    alerts: Annotated[list[dict[str, Any]], operator.add]
    audit: Annotated[list[dict[str, Any]], operator.add]
    status: str


Node = Callable[[CopilotState, Runtime[SpineDeps]], Awaitable[dict[str, Any]]]


def node(name: str, *, llm: bool = False) -> Callable[[Node], Node]:
    """K12 span and K4 step/agent events around a copilot node (same shape as the spine's)."""

    def wrap(fn: Node) -> Node:
        @wraps(fn)
        async def inner(state: CopilotState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
            emit("agent_start" if llm else "step", {"node": name, "status": "start"})
            with sgw_span(
                f"agent.copilot.{name}",
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


def _as_of(raw: Any) -> datetime:
    if raw is None:
        return DEFAULT_AS_OF
    value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("as_of needs a UTC offset")
    return value.astimezone(UTC)


def _ctx(state: CopilotState) -> InjectedContext:
    role = state.get("user_role", "operations")
    function = (
        ApprovalFunction(role) if role in {f.value for f in ApprovalFunction} else ApprovalFunction.OPERATIONS
    )
    return InjectedContext(
        as_of=datetime.fromisoformat(state["as_of"]),
        user_id=state.get("user_id", "unknown"),
        user_role=function,
        region_ids=["SC-45003"],
        run_mode=RunMode(state.get("run_mode", RunMode.REPLAY.value)),
        classification_ceiling=Classification.C1,
    )


@node("load_context")
async def load_context(state: CopilotState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    raw = dict(state.get("input") or {})
    ignored = sorted(set(raw) - ALLOWED_INPUT)
    question = " ".join(str(raw.get("question", "")).split())[:MAX_QUESTION]
    if not question:
        raise ValueError("the copilot needs a question")
    scenario_now = getattr(runtime.context, "scenario_now", None)
    now = scenario_now() if scenario_now is not None else None
    asked = raw.get("as_of")
    as_of = _as_of(asked) if asked is not None else (now or DEFAULT_AS_OF)
    clamped = now is not None and as_of > now
    if clamped:
        as_of = now
    emit("artifact", {"kind": "message", "role": "user", "text": question})
    return {
        "question": question,
        "history": _history(raw.get("history")),
        "as_of": as_of.isoformat(),
        "engine": getattr(runtime.context, "engine", "single"),
        "started": time.monotonic(),
        "status": "running",
        "tainted": False,
        "audit": [
            {
                "kind": "run_start",
                "graph": GRAPH_ID,
                "user_id": state.get("user_id"),
                "ignored_keys": ignored,
                "as_of_clamped_to_scenario_clock": clamped,
            }
        ],
    }


def _history(raw: Any) -> list[dict[str, Any]]:
    """Earlier turns of the same conversation, set by the API from the thread (never by the client): the
    question, the answer text and the gate's topics, newest last."""
    out: list[dict[str, Any]] = []
    for turn in list(raw or [])[-MAX_HISTORY:]:
        if not isinstance(turn, dict):
            continue
        out.append(
            {
                "question": " ".join(str(turn.get("question") or "").split())[:400],
                "answer": " ".join(str(turn.get("answer") or "").split())[:600],
                "topics": [str(t)[:60] for t in list(turn.get("topics") or [])[:5]],
                "kind": str(turn.get("kind") or "")[:20],
            }
        )
    return out


def r33_node(name: str, deps: Any) -> Any:
    """The R33 nodes (follow-up, wide gate, guide) from the run's nodes file, else from the default one:
    eval node files written before R33 do not name them."""
    try:
        return node_config(name, deps.nodes_file)
    except KeyError:
        return node_config(name)


def _asked(state: CopilotState) -> str:
    """The question the copilot answers: the user's turn, or its standalone form for a follow-up."""
    return str(state.get("standalone") or state["question"])


@node("route_intent", llm=True)
async def route(state: CopilotState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    deps = runtime.context
    history = state.get("history") or []
    asked, how = await standalone(
        state["question"],
        history,
        llm=deps.llm,
        config=r33_node(CONTEXTUALISE, deps),
        run_id=state.get("run_id"),
        model_override=deps.model_overrides.get(CONTEXTUALISE),
    )
    state = {**state, "standalone": asked} if how != "same" else state
    r = await route_intent(
        asked,
        llm=deps.llm,
        config=node_config(ROUTE, deps.nodes_file),
        run_id=state.get("run_id"),
        model_override=deps.model_overrides.get(ROUTE),
    )
    rerouted = reroutes(asked, r)
    audit: list[dict[str, Any]] = [
        {"kind": "route", "intent": r.intent.value, "path": r.path, "entities": r.entity_ids}
    ]
    if rerouted is not None:
        audit.append({"kind": "reroute", "from": r.intent.value, "to": rerouted.value, "reason": r.reason})
        r = r.model_copy(update={"intent": rerouted})
    if r.tainted:
        audit.append(
            {
                "kind": "taint",
                "reason": "instruction-like text withheld from the user turn",
                "flags": r.guard_reasons,
            }
        )
    g = await triage(
        guard_untrusted(asked).shown,
        r,
        llm=deps.llm,
        config=r33_node(TRIAGE, deps),
        run_id=state.get("run_id"),
        model_override=deps.model_overrides.get(TRIAGE),
        raw=f"{state['question']}\n{asked}" if asked != state["question"] else asked,
        own=state["question"] if asked != state["question"] else None,
    )
    out: dict[str, Any] = {"tainted": r.tainted}
    if how != "same":
        out["standalone"] = asked
        audit.append({"kind": "followup", "how": how})
    if g is not None:
        audit.append({"kind": "gate", "gate": g.kind, "path": g.path, "reason": g.reason, "topics": g.topics})
        if g.intent is not None:
            r = r.model_copy(update={"intent": g.intent})
        out["gate"] = g.model_dump(mode="json")
    return {**out, "route": r.model_dump(mode="json", exclude={"usage"}), "audit": audit}


@node("investigate", llm=True)
async def investigate_node(state: CopilotState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    deps = runtime.context
    r = RouteResult.model_validate(state["route"])
    if r.intent is Intent.OUT_OF_SCOPE:
        answer = CopilotAnswer(
            state["question"], "not_in_documents", READ_ONLY, READ_ONLY, reason="out_of_scope"
        )
        return {"answer": answer.as_state()}
    search: SearchFn | None = getattr(deps, "search", None) or env_search()
    shown = guard_untrusted(state["question"]).shown.replace(WITHHELD, "").strip()
    answer = await investigate(
        shown,
        _ctx(state),
        llm=deps.llm,
        config=node_config(INVESTIGATE, deps.nodes_file),
        member_table=deps.member_table,
        search=search,
        run_id=state.get("run_id"),
        model_override=deps.model_overrides.get(INVESTIGATE),
        entities=r.entity_ids,
        intent=r.intent.value,
        observer=tool_frame,
    )
    audit = [
        {"kind": "tool_call", "tool": c["tool"], "args": c["args"], "status": c["status"]}
        for c in answer.tool_calls
    ]
    audit += [{"kind": "security_alert", "alert": a} for a in answer.alerts]
    if answer.violations:
        audit.append({"kind": "verifier_rejected", "violations": answer.violations[:20]})
    return {
        "answer": answer.as_state(),
        "tainted": bool(state.get("tainted")) or answer.tainted,
        "alerts": answer.alerts,
        "audit": audit,
    }


def _period(deps: Any, state: CopilotState) -> str:
    base = str(getattr(deps, "period", None) or default_period())
    after = phase_line(str(getattr(deps, "scenario", "helene")), _as_of(state["as_of"]))
    return f"{base}\n{after}" if after else base


def phase_line(scenario: str, at: datetime) -> str:
    """Once the final advisory is out (R30 phase model): the scenario time, the phase and that no next
    advisory exists. Empty before then, so storm-night requests stay as they were."""
    from sgw.agent.copilot.investigate import reader_time
    from sgw.api.scenario_phase import PHASE_LABEL, final_advisory_utc, phase_at

    final = final_advisory_utc(scenario)
    if final is None or at < final:
        return ""
    return (
        f"Scenario time now: {reader_time(at)}, phase: {PHASE_LABEL[phase_at(scenario, at)]}. The advisories"
        " are over: there is no next advisory, so never name one or say that a decision can wait for one."
        ' Write the verdict decide_now as "decide now", never "decide before the next advisory". A decide-by'
        " earlier than the scenario time has passed: say that it has passed. Each decision clock now shows"
        " its deadline (passed or open) and what became of the decision (decided_on_time, decided_late,"
        " decided, missed, waiting, expired, closed, draft, no_proposal): report that in plain words, not the"
        " advisory verdict."
    )


def _stamp(state: CopilotState, deps: Any) -> str:
    return clock_context(_ctx(state), deps.member_table).as_of.strftime("%Y-%m-%dT%H:%MZ")


def _runner(deps: Any) -> ToolRunner:
    runner: ToolRunner = getattr(deps, "runner", None) or LocalToolRunner()
    return runner


def _shown(question: str) -> str:
    return guard_untrusted(question).shown.replace(WITHHELD, "").strip()


def after_route(state: CopilotState) -> str:
    gate = state.get("gate")
    if gate and GateResult.model_validate(gate).guided:
        return "guide"
    if RouteResult.model_validate(state["route"]).intent is Intent.OUT_OF_SCOPE:
        return "out_of_scope"
    return "plan" if state.get("engine") == "team" else "investigate"


@node("out_of_scope")
async def out_of_scope(state: CopilotState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    answer = CopilotAnswer(state["question"], "not_in_documents", READ_ONLY, READ_ONLY, reason="out_of_scope")
    return {"answer": answer.as_state()}


@node("guide", llm=True)
async def guide_node(state: CopilotState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    deps = runtime.context
    g = GateResult.model_validate(state["gate"])
    ctx = _ctx(state)
    inp = GuideInput(
        question=_shown(_asked(state)),
        gate=g,
        function=ctx.user_role.value,
        period=_period(deps, state),
        history=state.get("history") or [],
        before_landfall=before_landfall(str(getattr(deps, "scenario", "helene")), ctx.as_of),
        decisions=await pointed_decisions(state, deps, ctx.as_of)
        if g.refusal in (None, "write_action")
        else (),
        scenario=str(getattr(deps, "scenario", "helene")),
    )
    answer, facts = await guide_answer(
        inp,
        llm=deps.llm,
        config=r33_node(GUIDE, deps),
        run_id=state.get("run_id"),
        model_override=deps.model_overrides.get(GUIDE),
    )
    a = answer.as_state()
    a.update(
        links=facts.links,
        photos=facts.photos,
        suggestions=facts.suggestions,
        did_you_mean=[] if g.refusal else g.did_you_mean,
        refusal=g.refusal,
        topics=g.topics,
        ref_pool=[
            {"kind": "photo", "id": p["photo_id"], "label": p["caption"], "match": p["photo_id"]}
            for p in facts.photos
        ],
    )
    return {
        "answer": a,
        "audit": [{"kind": "guide", "gate": g.kind, "reason": answer.reason, "links": len(facts.links)}],
    }


@node("plan", llm=True)
async def plan_node(state: CopilotState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    deps = runtime.context
    ctx = _ctx(state)
    workers = offered(ctx.user_role.value, _runner(deps))
    clock = clock_context(ctx, deps.member_table)
    p = await make_plan(
        _shown(_asked(state)),
        state["route"],
        llm=deps.llm,
        config=node_config(PLAN, deps.nodes_file),
        workers=workers,
        member_table=deps.member_table,
        as_of=clock.as_of,
        stamp=_stamp(state, deps),
        period=_period(deps, state),
        known=known_ids(deps.member_table, clock.as_of),
        run_id=state.get("run_id"),
        model_override=deps.model_overrides.get(PLAN),
        function=ctx.user_role.value,
        scenario=str(getattr(deps, "scenario", "helene")),
    )
    p = overview_plan(
        p,
        _shown(_asked(state)),
        workers,
        overview=is_overview(state, keywords=False),
        notices=advisories_over(str(getattr(deps, "scenario", "helene")), clock.as_of),
    )
    audit = [
        {
            "kind": "plan",
            "path": p.path,
            "reason": p.reason,
            "workers": [t.worker for t in p.tasks],
            "followup": [t.worker for t in p.followup],
        }
    ]
    return {"plan": p.as_state(), "audit": audit}


DECISION_CASE = re.compile(r"\bDC-[A-Z0-9]+(?:-[A-Z0-9]+)+\b")


async def pointed_decisions(state: CopilotState, deps: Any, at: datetime) -> list[dict[str, str]]:
    """The decision a navigation turn points at: named in the (rewritten) question, else the first one the
    previous answer named; with the proposal the Decisions page opens (`/?d=<proposal>`)."""
    ids = DECISION_CASE.findall(_asked(state))
    history = state.get("history") or []
    if not ids and history:
        ids = DECISION_CASE.findall(str(history[-1].get("answer") or ""))[:1]
    if not ids:
        return []
    proposals, _ = await decisions_now(_runner(deps), at)
    out: list[dict[str, str]] = []
    for case in dict.fromkeys(ids):
        mine = [p for p in proposals if p.decision_case_id == case and p.state.value != "draft"]
        if mine:
            p = mine[-1]
            out.append({"id": case, "title": plain_title(p.title), "href": f"/?d={p.proposal_id}"})
    return out[:2]


def before_landfall(scenario: str, at: datetime) -> bool:
    """No field damage photos exist before landfall (the Crews page says the same)."""
    from sgw.api.scenario_phase import phase_at

    try:
        return phase_at(scenario, at) == "before_landfall"
    except (KeyError, ValueError):
        return False


def is_overview(state: CopilotState, keywords: bool = True) -> bool:
    """A question about the whole situation: the gate's or router's reading, or its keywords."""
    from sgw.agent.route.gate import keyword_kind

    gate = state.get("gate") or {}
    if gate.get("kind") == "overview" or (state.get("route") or {}).get("intent") == "sitrep":
        return True
    return keywords and keyword_kind(_shown(_asked(state))) == "overview"


NOTICES_TASK = (
    " Include the boil-water notices on the decision board: notices lifted, lifts proposed with their"
    " deadlines, and notices still in force."
)


def overview_plan(
    p: Plan, question: str, workers: Sequence[WorkerSpec], overview: bool = False, notices: bool = False
) -> Plan:
    """A question about the whole situation always gets the grid and the water analysts the role may use,
    so the answer has the county customers-out total and the water service (R34; the planner skipped them).
    `overview` is the gate's or router's reading ("what happend overnight"); with `notices` (after the final
    advisory, when the boil-water notices and their lifts are the water news) the water task asks for them."""
    from sgw.agent.copilot.plan import MAX_WORKERS
    from sgw.agent.route.gate import keyword_kind

    if not (overview or keyword_kind(question) == "overview") or not p.tasks:
        return p
    offered_names = {w.name for w in workers}
    have = [t.worker for t in p.tasks]
    needed = [
        WorkerTask(w, question, (), 1) for w in ("grid", "water") if w in offered_names and w not in have
    ]
    if notices:
        needed = [
            replace(t, question=t.question + NOTICES_TASK) if t.worker == "water" else t for t in needed
        ]
        p = replace(
            p,
            tasks=[
                replace(t, question=t.question + NOTICES_TASK)
                if t.worker == "water" and NOTICES_TASK not in t.question
                else t
                for t in p.tasks
            ],
        )
    if not needed:
        return p
    tasks = [*needed, *p.tasks][:MAX_WORKERS]
    kept = {t.worker for t in tasks}
    return replace(p, tasks=tasks, followup=[t for t in p.followup if t.worker not in kept])


def _calls_used(state: CopilotState) -> int:
    route_call = 1 if (state.get("route") or {}).get("reason") != "only_instructions" else 0
    plan_call = 1 if (state.get("plan") or {}).get("reason") not in ("no_worker_for_role",) else 0
    return route_call + plan_call + sum(int(f.get("llm_calls", 0)) for f in state.get("findings") or [])


def _spent(state: CopilotState, deps: Any) -> float:
    total = 0.0
    for f in state.get("findings") or []:
        alias = node_config(BY_NAME[f["worker"]].node, deps.nodes_file).model.value
        total += spent(alias, f.get("usage") or [])
    return total


def _sends(state: CopilotState, tasks: list[dict[str, Any]], deps: Any) -> list[Send]:
    if not tasks:
        return []
    calls_left = MAX_LLM_CALLS - _calls_used(state) - SYNTH_CALLS
    synth = node_config(SYNTH, deps.nodes_file)
    pool = MAX_TURN_USD - _spent(state, deps) - worst_case(synth) - TYPICAL_STEP_USD
    out: list[Send] = []
    for raw in tasks:
        config = node_config(BY_NAME[raw["worker"]].node, deps.nodes_file)
        steps = min(calls_left // len(tasks), steps_within(config, pool / len(tasks), TYPICAL_STEP_USD, 3))
        out.append(Send("worker", {**state, "task": {**raw, "max_steps": max(steps, 0)}}))
    return out


def fan_out(state: CopilotState, runtime: Runtime[SpineDeps]) -> list[Send] | str:
    sends = _sends(state, list((state.get("plan") or {}).get("tasks") or []), runtime.context)
    return sends or "synthesise"


@node("worker", llm=True)
async def worker_node(state: CopilotState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    deps = runtime.context
    raw = state["task"]
    task = WorkerTask.from_state(raw)
    spec = BY_NAME[task.worker]
    rank = WORKER_ORDER.index(spec.name)

    def frame(phase: str, call: dict[str, Any], n: int) -> None:
        number = 1000 * task.wave + 100 * rank + n
        if phase == "start":
            emit(
                "tool_start",
                {"tool": call["tool"], "args": call["args"], "call": number, "worker": spec.name},
            )
        else:
            emit(
                "tool_end",
                {"tool": call["tool"], "call": number, "status": call["status"], "worker": spec.name},
            )

    emit("step", {"node": f"worker:{spec.name}", "status": "start"})
    finding = await run_worker(
        spec,
        task,
        _ctx(state),
        llm=deps.llm,
        config=node_config(spec.node, deps.nodes_file),
        member_table=deps.member_table,
        runner=_runner(deps),
        search=getattr(deps, "search", None) or env_search(),
        period=_period(deps, state),
        max_steps=0 if spec.name in getattr(deps, "code_only", ()) else int(raw.get("max_steps", 0)),
        observer=frame,
        run_id=state.get("run_id"),
        model_override=deps.model_overrides.get(spec.node),
    )
    emit("step", {"node": f"worker:{spec.name}", "status": "end"})
    audit: list[dict[str, Any]] = [
        {
            "kind": "worker",
            "worker": spec.name,
            "wave": task.wave,
            "path": finding.path,
            "reason": finding.reason,
            "at": finding.at,
            "ms": finding.ms,
            "llm_calls": finding.llm_calls,
        }
    ]
    audit += [
        {
            "kind": "tool_call",
            "worker": spec.name,
            "tool": c["tool"],
            "args": c["args"],
            "status": c["status"],
            "at": c.get("at"),
            "ms": c.get("ms"),
        }
        for c in finding.tool_calls
    ]
    audit += [{"kind": "security_alert", "alert": a} for a in finding.alerts]
    return {"findings": [finding.as_state()], "alerts": finding.alerts, "audit": audit}


@node("gather")
async def gather(state: CopilotState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    done = sorted({(int(f["wave"]), str(f["worker"])) for f in state.get("findings") or []})
    return {"audit": [{"kind": "gather", "findings": [f"{w}:{n}" for w, n in done]}]}


def second_wave(state: CopilotState, runtime: Runtime[SpineDeps]) -> list[Send] | str:
    findings = state.get("findings") or []
    if any(int(f["wave"]) >= MAX_WAVES for f in findings):
        return "synthesise"
    ran = {str(f["worker"]) for f in findings}
    follow = [t for t in (state.get("plan") or {}).get("followup") or [] if t["worker"] not in ran]
    if time.monotonic() - float(state.get("started") or 0) > TURN_TIMEOUT_S / 2:
        return "synthesise"
    return _sends(state, follow, runtime.context) or "synthesise"


@node("synthesise", llm=True)
async def synthesise_node(state: CopilotState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    deps = runtime.context
    ctx = _ctx(state)
    clock = clock_context(ctx, deps.member_table)
    findings = state.get("findings") or []
    merged = merge(
        findings, clock, deps.member_table, scenario_period(str(getattr(deps, "scenario", "helene")))
    )
    config = node_config(SYNTH, deps.nodes_file)
    calls = min(SYNTH_CALLS, MAX_LLM_CALLS - _calls_used(state))
    if _spent(state, deps) + worst_case(config) > MAX_TURN_USD:
        calls = 0
    if time.monotonic() - float(state.get("started") or 0) > TURN_TIMEOUT_S:
        calls = 0
    answer, used, _ = await synthesise(
        _shown(_asked(state)),
        merged,
        ctx,
        llm=deps.llm,
        config=config,
        stamp=_stamp(state, deps),
        period=_period(deps, state),
        max_calls=calls,
        run_id=state.get("run_id"),
        model_override=deps.model_overrides.get(SYNTH),
    )
    if answer.path == "m2":
        answer = await plain_fallback(state, deps, ctx, merged.tools, answer)
    elif answer.path == "llm" and is_overview(state):
        from sgw.agent.copilot.language import language_of
        from sgw.agent.copilot.notices import notice_line

        line = notice_line(merged.tools.items, answer.rendered, language_of(_shown(_asked(state))))
        if line:
            answer.text = f"{answer.text.rstrip()} {line}"
            answer.rendered = f"{answer.rendered.rstrip()} {line}"
    ordered_findings = merged.findings
    answer.tool_calls = [
        {**c, "worker": f["worker"]} for f in ordered_findings for c in f.get("tool_calls") or []
    ]
    answer.write_attempts = sum(int(f.get("write_attempts", 0)) for f in ordered_findings)
    answer.evidence_ids = [i.id for i in merged.tools.items]
    answer.sources = [g.hit.chunk_id for g in merged.tools.hits]
    answer.entity_ids = sorted({e for i in merged.tools.items for e in i.entity_ids})
    answer.ref_pool = evidence_refs(merged.tools.items) + answer.ref_pool
    answer.steps = _calls_used(state) + used
    answer.tainted = any(g.tainted for g in merged.tools.hits) or any(c.unverified for c in answer.citations)
    if UNVERIFIED in answer.rendered:
        answer.tainted = True
    audit: list[dict[str, Any]] = [
        {"kind": "synthesis", "path": answer.path, "reason": answer.reason, "llm_calls": answer.steps},
        {
            "kind": "verify",
            "at": datetime.now(UTC).isoformat(),
            "decision": "fail"
            if answer.reason == "checks_failed"
            else ("pass" if answer.path in ("llm", "not_in_documents") else "fallback"),
            "checks": ["digits", "ids", "citations", "authority", "grounding"],
        },
    ]
    if answer.violations:
        audit.append({"kind": "verifier_rejected", "violations": answer.violations[:20]})
    return {
        "answer": answer.as_state(),
        "tainted": bool(state.get("tainted")) or answer.tainted,
        "audit": audit,
    }


def _reads(runner: Any) -> Any:
    return getattr(runner, "reads", None) or getattr(getattr(runner, "inner", None), "reads", None)


async def decisions_now(runner: Any, at: datetime) -> tuple[list[Any], dict[str, datetime]]:
    """The decisions read the Decisions page shows at `at`, with the scenario time each decision took
    effect; empty when the runner has no database (replay files, tests)."""
    import asyncio

    from sgw.agent.copilot.clock_state import authority_times

    reads = _reads(runner)
    if reads is None:
        return [], {}
    proposals = list(await reads.decisions(at, None))
    dsn = getattr(reads, "dsn", None)
    ids = [p.proposal_id for p in proposals]
    decided = await asyncio.to_thread(authority_times, dsn, ids, at) if dsn else {}
    return proposals, decided


async def missed_now(runner: Any, at: datetime) -> list[Any]:
    """The decisions whose deadline passed with no proposal at `at` (Decisions > Closed); none without a
    database."""
    read = getattr(_reads(runner), "missed_cases", None)
    return list(await read(at)) if read is not None else []


LIST_QUESTION = re.compile(r"^\s*which decisions\b", re.IGNORECASE)


def code_first(question: str) -> bool:
    """Questions whose answer is a list of decisions with their times, states and signers ("What do I need to
    decide in the next three hours?", "Which decisions keep the hospital supplied?"): the decision queue read
    by code answers them exactly at any state, with plain titles; model prose added nothing there but errors
    (R32 review: raw ids, invented signer gaps, drafts, internal codes). Explanations stay with the AI."""
    from sgw.agent.copilot.plain import about_decisions, window

    asked = " ".join(question.split())
    return bool(LIST_QUESTION.match(asked)) or (window(asked) is not None and about_decisions(asked, None))


def after_load(state: CopilotState) -> str:
    return "platform_answer" if code_first(state["question"]) else "route_intent"


@node("platform_answer")
async def platform_answer(state: CopilotState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    deps = runtime.context
    ctx = _ctx(state)
    tools = CopilotTools(
        ctx=clock_context(ctx, deps.member_table), member_table=deps.member_table, search=None, search_ctx=ctx
    )
    start = CopilotAnswer(state["question"], "m2", "", "", reason=CODE_FIRST)
    answer = await plain_fallback(state, deps, ctx, tools, start)
    answer.reason = None
    return {"answer": answer.as_state(), "audit": [{"kind": "platform_answer", "path": answer.path}]}


async def plain_fallback(
    state: CopilotState, deps: Any, ctx: InjectedContext, tools: Any, answer: CopilotAnswer
) -> CopilotAnswer:
    """The M2 answer as a short plain answer (`plain.py`); a decisions read that fails or does not parse
    leaves the clock evidence's own state."""
    route = state.get("route") or {}
    try:
        proposals, decided = await decisions_now(_runner(deps), ctx.as_of)
    except Exception:
        proposals, decided = [], {}
    try:
        missed = await missed_now(_runner(deps), ctx.as_of) if proposals else []
    except Exception:
        missed = []
    spec = PlainInput(
        question=_shown(_asked(state)),
        intent=route.get("intent"),
        entities=list(route.get("entity_ids") or []),
        now=ctx.as_of,
        lead=framing(answer.reason, (state.get("plan") or {}).get("path") == "llm"),
        member_table=deps.member_table,
        proposals=proposals,
        decided_at=decided,
        scenario=str(getattr(deps, "scenario", "helene")),
        missed=missed,
    )
    try:
        plain, cases = plain_answer(spec, tools, answer.reason)
    except Exception:
        spec.proposals, spec.decided_at, spec.missed = [], {}, []
        plain, cases = plain_answer(spec, tools, answer.reason)
    plain.violations = answer.violations
    plain.ref_pool = decision_refs(cases)
    return plain


def tool_frame(phase: str, call: dict[str, Any], n: int) -> None:
    if phase == "start":
        emit("tool_start", {"tool": call["tool"], "args": call["args"], "call": n})
    else:
        emit("tool_end", {"tool": call["tool"], "call": n, "status": call["status"]})


@node("link")
async def link_node(state: CopilotState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    a = dict(state["answer"])
    ctx = _ctx(state)
    if a.get("path") == "not_in_documents" and not a.get("refusal"):
        asked = _shown(_asked(state))
        a.update(helpful_not_found(asked, ctx.user_role.value, state.get("history") or []))
        if a.get("reason") == "model_not_in_documents":
            deps = runtime.context
            written = await not_found_text(
                asked,
                ctx.user_role.value,
                a,
                a.get("tool_calls") or [],
                period=_period(deps, state),
                llm=deps.llm,
                config=r33_node(GUIDE, deps),
                run_id=state.get("run_id"),
                model_override=deps.model_overrides.get(GUIDE),
                scenario=str(getattr(deps, "scenario", "helene")),
            )
            if written:
                a["text"] = a["rendered"] = written
    a["references"] = references(
        a["rendered"],
        evidence_ids=[] if a.get("path") == "not_in_documents" else a.get("entity_ids") or [],
        pool=a.get("ref_pool") or [],
        citations=a.get("citations") or [],
        member_table=runtime.context.member_table,
        as_of=ctx.as_of,
        region_ids=ctx.region_ids,
    )
    gate = GateResult.model_validate(state["gate"]) if state.get("gate") else None
    planned = (state.get("plan") or {}).get("did_you_mean") or []
    unclear = vague(_shown(_asked(state))) or a.get("path") == "not_in_documents"
    if planned and unclear and not a.get("refusal"):
        a["did_you_mean"] = list(planned)
    elif gate is not None and gate.kind == "readings" and gate.did_you_mean:
        a["did_you_mean"] = gate.did_you_mean
    scenario = str(getattr(runtime.context, "scenario", "helene"))
    a["links"] = answer_links(
        a, (state.get("route") or {}).get("intent"), ctx.user_role.value, _shown(_asked(state)), scenario
    )
    for key in ("suggestions", "did_you_mean"):
        if a.get(key):
            a[key] = scenario_questions(a[key], scenario)
    return {"answer": a}


ANSWER_REASONS = frozenset({"model_not_in_documents", "out_of_scope", "step_cap", "checks_failed"})
CITATION_KEYS = ("n", "citation_id", "doc_id", "version", "section", "pages", "cited_text", "unverified")


def answer_reason(answer: dict[str, Any]) -> AnswerReason | None:
    """Why an answer is not checked model text, in the K3 `Message.reason` vocabulary: the investigator's own
    reasons pass through; every LLM-unavailable reason (gateway errors, replay without a recording, the
    kill switch, refusal, max tokens) becomes `llm_unavailable`; a checked model answer has none."""
    reason = answer.get("reason")
    if answer.get("path") == "llm" or not reason:
        return None
    return cast(AnswerReason, reason if reason in ANSWER_REASONS else "llm_unavailable")


def citation_row(citation: dict[str, Any]) -> dict[str, Any]:
    return {k: citation[k] for k in CITATION_KEYS if k in citation}


@node("respond")
async def respond(state: CopilotState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    a = state["answer"]
    emit(
        "artifact",
        {
            "kind": "message",
            "role": "assistant",
            "text": a["rendered"],
            "path": a["path"],
            "citations": [c["citation_id"] for c in a["citations"]],
            "citation_details": [citation_row(c) for c in a["citations"]],
            "reason": answer_reason(a),
            "evidence_ids": a["evidence_ids"],
            "references": a.get("references") or [],
            "links": a.get("links") or [],
            "photos": a.get("photos") or [],
            "suggestions": a.get("suggestions") or [],
            "did_you_mean": a.get("did_you_mean") or [],
            "refusal": a.get("refusal"),
            "slots_shown": a["slots_shown"],
            "tainted": bool(state.get("tainted")),
            "write_attempts": a["write_attempts"],
        },
        Classification.C1,
    )
    return {"status": "ended"}


@node("audit")
async def audit(state: CopilotState, runtime: Runtime[SpineDeps]) -> dict[str, Any]:
    a = state.get("answer") or {}
    return {
        "audit": [
            {
                "kind": "run_end",
                "graph": GRAPH_ID,
                "path": a.get("path"),
                "tainted": bool(state.get("tainted")),
                "write_attempts": a.get("write_attempts", 0),
                "steps": a.get("steps", 0),
            }
        ]
    }


def build(checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    g: Any = StateGraph(CopilotState, context_schema=SpineDeps)
    g.add_node("load_context", load_context)
    g.add_node("route_intent", route)
    g.add_node("investigate", investigate_node)
    g.add_node("out_of_scope", out_of_scope)
    g.add_node("plan", plan_node)
    g.add_node("worker", worker_node)
    g.add_node("gather", gather)
    g.add_node("synthesise", synthesise_node)
    g.add_node("link", link_node)
    g.add_node("respond", respond)
    g.add_node("audit", audit)
    g.add_edge(START, "load_context")
    g.add_conditional_edges("load_context", after_load, ["route_intent", "platform_answer"])
    g.add_node("platform_answer", platform_answer)
    g.add_edge("platform_answer", "link")
    g.add_conditional_edges(
        "route_intent",
        after_route,
        {"out_of_scope": "out_of_scope", "plan": "plan", "investigate": "investigate", "guide": "guide"},
    )
    g.add_conditional_edges("plan", fan_out, ["worker", "synthesise"])
    g.add_edge("worker", "gather")
    g.add_conditional_edges("gather", second_wave, ["worker", "synthesise"])
    g.add_edge("synthesise", "link")
    g.add_edge("out_of_scope", "link")
    g.add_node("guide", guide_node)
    g.add_edge("guide", "link")
    g.add_edge("investigate", "link")
    g.add_edge("link", "respond")
    g.add_edge("respond", "audit")
    g.add_edge("audit", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())
