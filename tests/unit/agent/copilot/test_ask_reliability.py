"""Ask AI reliability: one prompt per advisory (the replay key does not follow the running clock), search
at the true scenario time, live tool frames, the never-break fallback and the deterministic `link` step."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sgw.agent.copilot import graph as copilot_graph
from sgw.agent.copilot.investigate import investigate
from sgw.agent.copilot.link import references
from sgw.agent.copilot.tools import CopilotTools, advisory_in_force, clock_context
from sgw.agent.nodes.llm import node_config
from sgw.agent.nodes.ports import InMemoryProposalPort
from sgw.agent.nodes.run_task import RunTask
from sgw.contracts.api_models import Message
from sgw.contracts.tools import InjectedContext, SearchProceduresArgs
from sgw.contracts.vocab import RunMode
from sgw.contracts.wire import WireEvent

from ..agent_testkit import DownLlm
from ..agent_testkit import platform_member_table as member_table
from .copilot_testkit import (
    ETR_SOURCE,
    ETR_TEXT,
    FakeSearch,
    Script,
    cite,
    ctx,
    etr_hits,
    final,
    route,
    text,
    use,
)

N_ISSUED = datetime(2024, 9, 26, 9, tzinfo=UTC)
N1_ISSUED = datetime(2024, 9, 26, 15, tzinfo=UTC)
PS17 = "What does the latest advisory mean for PS-17's deadline?"


def at(h: int, m: int = 0, day: int = 26) -> datetime:
    return datetime(2024, 9, day, h, m, tzinfo=UTC)


def test_the_clock_context_is_the_issue_time_of_the_advisory_in_force() -> None:
    table = member_table()
    assert advisory_in_force(table, at(15, 5)) == ("N+1", N1_ISSUED)
    assert advisory_in_force(table, at(18, day=28)) == ("N+1", N1_ISSUED)
    assert advisory_in_force(table, at(10)) == ("N", N_ISSUED)
    assert advisory_in_force(table, at(8)) == ("N", N_ISSUED)
    shifted = clock_context(ctx(at(15, 5)), table)
    assert shifted.as_of == N1_ISSUED and shifted.user_id == ctx().user_id


async def _first_request(as_of: datetime) -> dict[str, Any]:
    llm = Script(investigate=[final(text("This is not in the documents."))])
    await investigate(
        PS17,
        ctx(as_of),
        llm=llm,
        config=node_config("investigate"),
        member_table=member_table(),
        search=FakeSearch(),
    )
    return llm.requests[0].body()


async def test_one_advisory_gives_one_prompt_however_the_clock_runs() -> None:
    first = await _first_request(at(15, 5))
    assert json.dumps(first) == json.dumps(await _first_request(at(23, 40)))
    assert json.dumps(first) == json.dumps(await _first_request(at(18, day=28)))
    assert json.dumps(first) != json.dumps(await _first_request(at(10)))
    turn = first["messages"][0]["content"][0]["text"]
    assert turn.startswith("Decision clocks: advisory issued 2024-09-26T15:00Z\n")


class TimedSearch(FakeSearch):
    def __init__(self) -> None:
        super().__init__(etr_hits())
        self.at: list[datetime] = []

    def __call__(self, args: SearchProceduresArgs, c: InjectedContext) -> Any:
        self.at.append(c.as_of)
        return super().__call__(args, c)


async def test_search_and_citations_use_the_true_scenario_time() -> None:
    search = TimedSearch()
    llm = Script(
        investigate=[
            use("search_procedures", {"query": "revise global ETR"}),
            final(text("Revise a published global ETR past the set margin.", [cite(ETR_SOURCE, ETR_TEXT)])),
        ]
    )
    a = await investigate(
        "When do I revise?",
        ctx(at(18, day=28)),
        llm=llm,
        config=node_config("investigate"),
        member_table=member_table(),
        search=search,
    )
    assert search.at == [at(18, day=28)] and a.path == "llm"


def test_tool_calls_are_observed_as_they_start_and_end() -> None:
    heard: list[tuple[str, str, int, str]] = []
    tools = CopilotTools(
        ctx=ctx(),
        member_table=member_table(),
        search=None,
        observer=lambda phase, call, n: heard.append((phase, call["tool"], n, call["status"])),
    )
    tools.run("get_water_status", {})
    tools.run("draft_proposal", {})
    assert heard == [
        ("start", "get_water_status", 0, "ok"),
        ("end", "get_water_status", 0, "ok"),
        ("start", "draft_proposal", 1, "ok"),
        ("end", "draft_proposal", 1, "refused"),
    ]


def _task(llm: Any, question: str, as_of: str = "2024-09-26T15:05:00Z") -> RunTask:
    deps = copilot_graph.CopilotDeps(
        llm=llm,
        proposals=InMemoryProposalPort(),
        member_table=member_table(),
        search=FakeSearch([]),
        engine="single",
    )
    return RunTask(
        run_id="run-r26",
        thread_id="thr-r26",
        graph_id="copilot",
        graph=copilot_graph.build(),
        deps=deps,
        user_id="ic_01",
        user_role="command",
        run_mode=RunMode.REPLAY,
        run_input={"question": question, "as_of": as_of},
    )


def _answer(t: RunTask) -> dict[str, Any]:
    (payload,) = [
        f.payload for f in t.frames if f.type is WireEvent.ARTIFACT and f.payload.get("role") == "assistant"
    ]
    return payload


async def test_tool_frames_stream_while_the_loop_runs() -> None:
    llm = Script(
        route_intent=[route("metric", ["PS-17"])],
        investigate=[
            use("get_water_status", {}),
            final(text("PS-38 has GEN-PS38-COPPERLEAF; PS-17 has none.")),
        ],
    )
    t = _task(llm, "Which stations have a generator?")
    await t.run()
    kinds = [(f.type, (f.payload or {}).get("node")) for f in t.frames]
    start = kinds.index((WireEvent.TOOL_START, None))
    end = kinds.index((WireEvent.TOOL_END, None))
    investigate_end = max(i for i, k in enumerate(kinds) if k == (WireEvent.AGENT_END, "investigate"))
    assert start < end < investigate_end


async def test_an_llm_outage_answers_from_the_entities_the_question_names() -> None:
    t = _task(DownLlm(), PS17)
    await t.run()
    a = _answer(t)
    assert a["path"] == "m2" and a["write_attempts"] == 0
    assert "DC-D3-PS17-POWER" in a["text"] and "decide by Sep 26, 23:29 ET; before next advisory" in a["text"]
    refs = {(r["kind"], r["id"]) for r in a["references"]}
    assert {("decision", "DC-D3-PS17-POWER"), ("asset", "PS-17")} <= refs
    tools = [f.payload["tool"] for f in t.frames if f.type is WireEvent.TOOL_START]
    assert tools.count("get_decision_case") >= 2 and tools[-1] == "search_procedures"
    assert copilot_graph.answer_reason(a) == "llm_unavailable"


async def test_an_outage_names_a_hospital_case_by_its_title_word() -> None:
    t = _task(DownLlm(), "Which decisions keep Tallowbranch hospital supplied with water?")
    await t.run()
    assert "DC-D3-HSP-TALLOWBRANCH-WATER" in _answer(t)["text"]


async def test_an_outage_finds_a_yard_case_by_its_place_name() -> None:
    t = _task(DownLlm(), "Which crews are staged at the Sandhill yard?")
    await t.run()
    a = _answer(t)
    assert "DC-D2-CREWS-AIK" in a["text"]
    assert ("yard", "STG-AIK-SANDHILL-YARD") not in {(r["kind"], r["id"]) for r in a["references"]}
    assert ("decision", "DC-D2-CREWS-AIK") in {(r["kind"], r["id"]) for r in a["references"]}


async def test_fallback_drops_passages_that_share_no_word_with_the_question() -> None:
    deps_search = FakeSearch()
    t = _task(DownLlm(), "What is the current status of the vegetation budget?")
    t.deps.search = deps_search
    await t.run()
    a = _answer(t)
    assert deps_search.calls and a["path"] == "not_in_documents"


async def test_not_available_only_without_any_entity_or_search_hit() -> None:
    t = _task(DownLlm(), "What is the current status of the vegetation budget?")
    await t.run()
    a = _answer(t)
    assert a["path"] == "not_in_documents" and a["references"] == []
    assert copilot_graph.answer_reason(a) == "llm_unavailable"


def test_references_are_made_only_for_ids_of_this_run_and_in_text_order() -> None:
    body = (
        "PS-17 needs DC-D3-PS17-POWER before the latest advisory window closes in Aiken; "
        "DC-D9-FORGED and PS-99 are not real. WZ-PS17-CEDARFALL is the zone, STG-AIK-SANDHILL-YARD the yard, "
        "CRW-KESTREL-02 the crew. DOM 14.206 says so; DOM 99.999 does not."
    )
    refs = references(
        body,
        evidence_ids=["PS-17"],
        citations=[{"doc_id": "DOM 14.206", "section": "6.2.4 Revising a published ETR"}],
        member_table=member_table(),
        as_of=at(15, 5),
        region_ids=["SC-45003"],
    )
    assert [(r["kind"], r["id"]) for r in refs] == [
        ("asset", "PS-17"),
        ("decision", "DC-D3-PS17-POWER"),
        ("advisory", "2024-09-26T15:00:00Z"),
        ("county", "45003"),
        ("zone", "WZ-PS17-CEDARFALL"),
        ("yard", "STG-AIK-SANDHILL-YARD"),
        ("crew", "CRW-KESTREL-02"),
        ("clause", "DOM 14.206"),
    ]
    labels = {r["id"]: r["label"] for r in refs}
    assert labels["PS-17"] == "Cedarfall pump station"
    assert labels["DC-D3-PS17-POWER"] == "Hook up the portable generator at PS-17"
    assert (
        labels["45003"] == "Aiken County" and labels["2024-09-26T15:00:00Z"] == "Advisory of Sep 26, 11:00 ET"
    )
    assert labels["CRW-KESTREL-02"] == "Kestrel 02 crew"


def test_references_are_an_optional_message_field() -> None:
    schema = Message.model_json_schema()
    assert "references" not in schema.get("required", [])
    m = Message.model_validate(
        {
            "message_id": "r.1",
            "role": "assistant",
            "text": "PS-17",
            "created_at": "2024-09-26T15:05:00Z",
            "references": [{"kind": "asset", "id": "PS-17", "label": "Cedarfall pump station"}],
        }
    )
    assert m.references[0].kind == "asset"
