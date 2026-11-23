"""The copilot team engine on scripted LLM replies (no gateway, no recordings): fan-out, caps,
order-stable synthesis, a code fallback at every level, the persona filter and worker digit checks."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

import pytest

from sgw.agent.copilot import graph as copilot_graph
from sgw.agent.copilot.budget import MAX_LLM_CALLS
from sgw.agent.copilot.plan import MAX_WORKERS, output_schema
from sgw.agent.copilot.runner import LocalToolRunner
from sgw.agent.copilot.synthesis import first_turn, merge
from sgw.agent.copilot.workers import WORKERS, offered
from sgw.agent.nodes.llm import LlmRequest, LlmResponse, LlmUnavailable
from sgw.agent.nodes.ports import InMemoryProposalPort
from sgw.agent.nodes.run_task import RunTask
from sgw.contracts.vocab import RunMode
from sgw.contracts.wire import WireEvent

from ..agent_testkit import platform_member_table as member_table
from .copilot_testkit import ETR_SOURCE, ETR_TEXT, FakeSearch, cite, ctx, final, route, text, use

AS_OF = "2024-09-26T15:05:00Z"
PS17 = "What does the latest advisory mean for PS-17's deadline, and what does the procedure require?"


def plan_reply(tasks: list[tuple[str, str]], followup: list[tuple[str, str]] | None = None) -> LlmResponse:
    rows = [{"worker": w, "task": t, "entity_ids": ["PS-17"]} for w, t in tasks]
    later = [{"worker": w, "task": t, "entity_ids": []} for w, t in followup or []]
    return final(text(json.dumps({"tasks": rows, "followup": later})))


Reply = LlmResponse | Exception | Callable[[LlmRequest], LlmResponse]


class Fake:
    """Per-node queues of replies; optional per-node delay so parallel workers finish in a chosen order."""

    def __init__(self, delays: dict[str, float] | None = None, **queues: list[Reply]) -> None:
        self.queues = {k: list(v) for k, v in queues.items()}
        self.delays = delays or {}
        self.requests: list[LlmRequest] = []
        self.done: list[str] = []

    async def create(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        await asyncio.sleep(self.delays.get(request.node, 0))
        self.done.append(request.node)
        q = self.queues.get(request.node) or []
        if not q:
            raise LlmUnavailable("replay_miss", request.node)
        reply = q.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply(request) if callable(reply) else reply

    def nodes(self) -> list[str]:
        return [r.node for r in self.requests]


def task(llm: Any, question: str = PS17, role: str = "command", search: Any = None) -> RunTask:
    deps = copilot_graph.CopilotDeps(
        llm=llm,
        proposals=InMemoryProposalPort(),
        member_table=member_table(),
        search=FakeSearch() if search is None else search,
        engine="team",
        runner=LocalToolRunner(),
    )
    return RunTask(
        run_id="run-team",
        thread_id="thr-team",
        graph_id="copilot",
        graph=copilot_graph.build(),
        deps=deps,
        user_id="ic_01",
        user_role=role,
        run_mode=RunMode.REPLAY,
        run_input={"question": question, "as_of": AS_OF},
    )


def answer_of(t: RunTask) -> dict[str, Any]:
    (a,) = [
        f.payload for f in t.frames if f.type is WireEvent.ARTIFACT and f.payload.get("role") == "assistant"
    ]
    return a


WATER_TEXT = "DC-D3-PS17-POWER has an effective decide-by of {E1.effective_decide_by}."
SYNTH_TEXT = (
    "Under the latest advisory DC-D3-PS17-POWER at PS-17 is due by {E2.effective_decide_by}; "
    "decide before the next advisory."
)


def happy(delays: dict[str, float] | None = None) -> Fake:
    return Fake(
        delays,
        route_intent=[route("assess", ["PS-17"])],
        ask_plan=[plan_reply([("water", "PS-17 deadline"), ("policy", "What the procedure requires")])],
        ask_worker_water=[final(text(WATER_TEXT))],
        ask_worker_policy=[final(text("Revise past the margin.", [cite(ETR_SOURCE, ETR_TEXT)]))],
        ask_synth=[
            final(text(SYNTH_TEXT), text(" Revise past the set margin.", [cite(ETR_SOURCE, ETR_TEXT)]))
        ],
    )


async def test_plan_fans_out_to_parallel_workers_and_one_synthesis_answers() -> None:
    llm = happy()
    t = task(llm)
    await t.run()
    a = answer_of(t)
    assert a["path"] == "llm" and a["write_attempts"] == 0, a
    assert "Sep 26, 23:29 ET" in a["text"] and "{E1" not in a["text"]
    assert sorted(llm.nodes()) == sorted(
        ["route_intent", "ask_plan", "ask_worker_water", "ask_worker_policy", "ask_synth"]
    )
    starts = [f.payload for f in t.frames if f.type is WireEvent.TOOL_START]
    assert {s["worker"] for s in starts} == {"water", "policy"}
    assert len({s["call"] for s in starts}) == len(starts)
    refs = {(r["kind"], r["id"]) for r in a["references"]}
    assert {("decision", "DC-D3-PS17-POWER"), ("asset", "PS-17")} <= refs
    state = await t.state()
    kinds = [x["kind"] for x in state["audit"]]
    assert kinds.count("worker") == 2 and "synthesis" in kinds and "plan" in kinds


def _synth_body(llm: Fake) -> str:
    (req,) = [r for r in llm.requests if r.node == "ask_synth"]
    return json.dumps(req.body(), sort_keys=True)


async def test_synthesis_request_is_the_same_whatever_order_the_workers_finish_in() -> None:
    first, second = happy({"ask_worker_water": 0.05}), happy({"ask_worker_policy": 0.05})
    for llm in (first, second):
        await task(llm).run()
    workers = ("ask_worker_water", "ask_worker_policy")
    assert [n for n in first.done if n in workers] != [n for n in second.done if n in workers]
    assert _synth_body(first) == _synth_body(second)


def test_merge_is_permutation_stable_and_rewrites_worker_slots() -> None:
    from sgw.agent.copilot.tools import CopilotTools

    table = member_table()
    tools_a = CopilotTools(ctx=ctx(), member_table=table, search=None)
    tools_a.run("get_water_status", {"zone_ids": ["WZ-PS17-CEDARFALL"]})
    tools_b = CopilotTools(ctx=ctx(), member_table=table, search=None)
    tools_b.run("get_decision_case", {"decision_case_id": "DC-D3-PS17-POWER"})

    def finding(worker: str, tools: CopilotTools, body: str) -> dict[str, Any]:
        return {
            "worker": worker,
            "wave": 1,
            "path": "llm",
            "text": body,
            "items": [i.model_dump(mode="json") for i in tools.items],
            "hits": [],
            "tool_calls": [],
        }

    fa = finding("grid", tools_b, "{E1.effective_decide_by} for DC-D3-PS17-POWER.")
    fb = finding("water", tools_a, "PS-17 is in WZ-PS17-CEDARFALL {E1.zone}.")
    one = merge([fa, fb], ctx(), table)
    two = merge([fb, fa], ctx(), table)
    assert json.dumps(first_turn("q", one, "s", "p"), sort_keys=True) == json.dumps(
        first_turn("q", two, "s", "p"), sort_keys=True
    )
    assert [f["worker"] for f in one.findings] == ["grid", "water"]
    assert one.findings[0]["text"].startswith("{E1.") and "{E2.zone}" in one.findings[1]["text"]


async def test_a_plan_miss_falls_back_to_the_code_plan() -> None:
    llm = happy()
    llm.queues["ask_plan"] = [LlmUnavailable("replay_miss", "plan")]
    t = task(llm)
    await t.run()
    state = await t.state()
    (plan_audit,) = [x for x in state["audit"] if x["kind"] == "plan"]
    assert plan_audit["path"] == "code" and plan_audit["reason"] == "replay_miss"
    assert "water" in plan_audit["workers"] and "policy" in plan_audit["workers"]
    assert answer_of(t)["path"] in ("llm", "m2")


async def test_a_worker_miss_keeps_its_code_evidence_and_the_others_still_answer() -> None:
    llm = happy()
    llm.queues["ask_worker_water"] = [LlmUnavailable("replay_miss", "water")]
    t = task(llm)
    await t.run()
    state = await t.state()
    workers = {x["worker"]: x for x in state["audit"] if x["kind"] == "worker"}
    assert workers["water"]["path"] == "code" and workers["water"]["reason"] == "replay_miss"
    assert workers["policy"]["path"] == "llm"
    (synth,) = [r for r in llm.requests if r.node == "ask_synth"]
    body = json.dumps(synth.body())
    assert "Platform data only" in body and "DC-D3-PS17-POWER" in body
    assert answer_of(t)["path"] == "llm"


async def test_a_synthesis_miss_renders_all_evidence_by_code_with_links() -> None:
    llm = happy()
    llm.queues["ask_synth"] = [LlmUnavailable("replay_miss", "synth")]
    t = task(llm)
    await t.run()
    a = answer_of(t)
    assert a["path"] == "m2" and "DC-D3-PS17-POWER" in a["text"]
    assert copilot_graph.answer_reason(a) == "llm_unavailable"
    assert ("decision", "DC-D3-PS17-POWER") in {(r["kind"], r["id"]) for r in a["references"]}


async def test_everything_down_still_answers_from_platform_data() -> None:
    t = task(Fake())
    await t.run()
    a = answer_of(t)
    assert a["path"] == "m2" and "DC-D3-PS17-POWER" in a["text"] and a["write_attempts"] == 0


async def test_failed_synthesis_checks_get_two_repairs_then_m2() -> None:
    llm = happy()
    llm.queues["ask_synth"] = [final(text("Decide by 03:29Z.")) for _ in range(3)]
    t = task(llm)
    await t.run()
    a = answer_of(t)
    assert a["path"] == "m2" and llm.nodes().count("ask_synth") == 3
    assert "03:29Z" not in a["text"]


async def test_worker_digits_are_rejected_and_the_worker_falls_back_to_code() -> None:
    llm = happy()
    bad = final(text("DC-D3-PS17-POWER is due at 03:29Z."))
    llm.queues["ask_worker_water"] = [bad, bad]
    t = task(llm)
    await t.run()
    state = await t.state()
    (water,) = [f for f in state["findings"] if f["worker"] == "water"]
    assert water["path"] == "code" and any("stray_digit" in v for v in water["violations"])
    assert "03:29Z" not in json.dumps([r.body() for r in llm.requests if r.node == "ask_synth"])


async def test_caps_hold_for_a_greedy_plan() -> None:
    greedy = plan_reply(
        [(w.name, "look") for w in WORKERS],
        [(w.name, "again") for w in WORKERS],
    )
    loops: dict[str, list[Any]] = {w.node: [use(w.tools[0], {}, n) for n in range(5)] for w in WORKERS}
    llm = Fake(route_intent=[route("assess", ["PS-17"])], ask_plan=[greedy], **loops)
    t = task(llm)
    await t.run()
    state = await t.state()
    workers = [x for x in state["audit"] if x["kind"] == "worker"]
    assert len(llm.requests) <= MAX_LLM_CALLS
    assert {x["wave"] for x in workers} <= {1, 2}
    assert all(sum(x["wave"] == w for x in workers) <= MAX_WORKERS for w in (1, 2))
    for w in WORKERS:
        extra = [c for c in state["audit"] if c.get("worker") == w.name and c["kind"] == "tool_call"]
        assert sum(c["status"] == "ok" for c in extra) <= 4 + 2
    assert answer_of(t)["path"] in ("m2", "not_in_documents")


async def test_a_follow_up_wave_runs_once_after_the_first() -> None:
    llm = happy()
    llm.queues["ask_plan"] = [plan_reply([("water", "PS-17 deadline")], [("policy", "Procedure")])]
    t = task(llm)
    await t.run()
    state = await t.state()
    waves = [(x["worker"], x["wave"]) for x in state["audit"] if x["kind"] == "worker"]
    assert waves == [("water", 1), ("policy", 2)]
    assert llm.nodes().index("ask_worker_water") < llm.nodes().index("ask_worker_policy")


def test_persona_filter_offers_only_tools_and_workers_the_role_may_use() -> None:
    runner = LocalToolRunner()
    comms = runner.allowed("communications")
    assert not comms & {"get_water_status", "get_outages", "get_crews", "list_anomalies"}
    assert {"search_procedures", "get_decision_case"} <= comms
    water_ops = runner.allowed("water_operations")
    assert "get_water_status" in water_ops and "get_outages" not in water_ops

    class NoTools(LocalToolRunner):
        def allowed(self, role: str) -> frozenset[str]:
            return frozenset({"search_procedures"})

    assert [w.name for w in offered("command", NoTools())] == ["policy"]
    schema = output_schema(offered("command", NoTools()))
    assert schema["properties"]["tasks"]["items"]["properties"]["worker"]["enum"] == ["policy"]
    assert [w.name for w in offered("command", runner)] == [w.name for w in WORKERS]


async def test_a_worker_call_outside_the_role_is_refused_and_alerted() -> None:
    llm = happy()
    llm.queues["ask_plan"] = [plan_reply([("water", "PS-17 deadline")])]
    llm.queues["ask_worker_water"] = [
        use("get_water_status", {}),
        final(text("This is not in the documents.")),
    ]
    t = task(llm, role="communications")
    await t.run()
    state = await t.state()
    calls = [x for x in state["audit"] if x["kind"] == "tool_call" and x["tool"] == "get_water_status"]
    assert calls and all(c["status"] == "refused" for c in calls)
    assert any(a["alert"]["code"] == "SEC-13" for a in state["audit"] if a["kind"] == "security_alert")


async def test_plan_and_synthesis_state_the_scenario_period() -> None:
    llm = happy()
    await task(llm).run()
    for node in ("ask_plan", "ask_synth"):
        (req,) = [r for r in llm.requests if r.node == node]
        system = req.body()["system"][0]["text"]
        assert "Scenario period: a replay of Hurricane Helene" in system
        assert "never compare it with today's date" in system


@pytest.mark.parametrize("as_of", ["2024-09-26T15:05:00Z", "2024-09-26T23:40:00Z"])
async def test_worker_requests_do_not_follow_the_running_clock(as_of: str) -> None:
    llm = happy()
    t = task(llm)
    t.run_input = {"question": PS17, "as_of": as_of}
    await t.run()
    (req,) = [r for r in llm.requests if r.node == "ask_worker_water"]
    assert "advisory issued 2024-09-26T15:00Z" in json.dumps(req.body())


async def test_out_of_scope_gets_the_read_only_reply_without_planning() -> None:
    llm = Fake(route_intent=[route("out_of_scope")])
    t = task(llm, question="Approve the crew dispatch now")
    await t.run()
    a = answer_of(t)
    assert "read-only" in a["text"] and a["refusal"] == "write_action" and len(a["suggestions"]) == 3
    assert not [n for n in llm.nodes() if n.startswith("ask_") and n != "ask_guide"]


TODAY = "Is this storm happening today?"


async def test_a_question_about_today_is_answered_from_the_scenario_period_in_eastern_time() -> None:
    llm = Fake(
        route_intent=[route("assess", [])],
        ask_plan=[plan_reply([("forecast", "Whether the storm is happening now")])],
        ask_worker_forecast=[final(text("This is not in the documents."))],
        ask_synth=[lambda r: final(text(today_answer(r)))],
    )
    t = task(llm, question=TODAY)
    await t.run()
    a = answer_of(t)
    assert a["path"] == "llm"
    assert "Sep 2" in a["text"] and " ET" in a["text"]
    assert "2025" not in a["text"] and "2026" not in a["text"]


def today_answer(request: LlmRequest) -> str:
    (slot,) = re.findall(r"\[(E\d+)\] scenario_period", json.dumps(request.body()))
    return f"No: the platform replays the storm from {{{slot}.starts}} to {{{slot}.ends}}."


async def test_the_synthesis_evidence_always_lists_the_scenario_period_last() -> None:
    llm = happy()
    await task(llm).run()
    (req,) = [r for r in llm.requests if r.node == "ask_synth"]
    view = json.dumps(req.body())
    assert "Scenario period: a replay of Hurricane Helene" in view
    assert view.index("scenario_period") > view.index("DC-D3-PS17-POWER")


async def test_frozen_prompts_carry_the_period_time_and_surge_rules() -> None:
    llm = happy()
    await task(llm).run()
    systems = {r.node: r.body()["system"][0]["text"] for r in llm.requests if r.node.startswith("ask_")}
    assert "happening now" in systems["ask_plan"]
    for node in ("ask_synth", "ask_worker_water", "ask_worker_policy"):
        assert "happening now" in systems[node]
        assert "Eastern time" in systems[node]
        assert "beats, outperforms" in systems[node] and "signal to check" in systems[node]


@pytest.mark.parametrize(("as_of", "over"), [("2024-09-26T15:05:00Z", False), ("2024-09-27T12:00:00Z", True)])
async def test_after_the_final_advisory_every_team_step_reads_that_no_next_advisory_exists(
    as_of: str, over: bool
) -> None:
    llm = happy()
    t = task(llm)
    t.run_input = {"question": PS17, "as_of": as_of}
    await t.run()
    for node in ("ask_plan", "ask_worker_water", "ask_synth"):
        (req,) = [r for r in llm.requests if r.node == node]
        body = json.dumps(req.body())
        assert ("there is no next advisory" in body) is over
        assert ("Sep 27, 08:00 ET" in body) is over


async def test_the_planner_analysts_and_writer_know_the_signed_in_role() -> None:
    llm = happy()
    await task(llm, role="operations").run()
    for node in ("ask_plan", "ask_worker_water", "ask_synth"):
        (req,) = [r for r in llm.requests if r.node == node]
        body = json.dumps(req.body())
        assert "<reader>Signed in as Duty Manager, Electric Operations (team Operations)" in body, node
    (plan,) = [r for r in llm.requests if r.node == "ask_plan"]
    assert "feeder 2207 to PS-17 (FDR-AIK-2207)" in plan.body()["system"][0]["text"]


async def test_the_planners_readings_reach_the_answer_as_did_you_mean() -> None:
    readings = ["Is feeder 2207 to PS-17 out?", "Is feeder 2231 to Tallowbranch hospital out?"]
    llm = happy()
    reply = {"tasks": [{"worker": "water", "task": "PS-17 feeder", "entity_ids": ["PS-17"]}], "followup": []}
    llm.queues["ask_plan"] = [final(text(json.dumps({**reply, "did_you_mean": readings})))]
    t = task(llm, question="Is the feeder out?")
    await t.run()
    assert answer_of(t)["did_you_mean"] == readings


async def test_act_now_without_an_act_now_verdict_is_repaired() -> None:
    llm = happy()
    llm.queues["ask_synth"] = [
        final(text("Act now on the hookup: DC-D3-PS17-POWER is due by {E2.effective_decide_by}.")),
        final(text(SYNTH_TEXT)),
    ]
    t = task(llm)
    await t.run()
    a = answer_of(t)
    assert a["path"] == "llm" and "act now" not in a["text"].lower()
    assert [r.node for r in llm.requests].count("ask_synth") == 2
