"""Replay coverage of the Ask AI demo: every demo question (the web starters and the copilot bookmark's
question) at every demo bookmark chain-hits the committed fixtures offline, on both engines, through the
API's graph, member table, recorded search and each bookmark's recorded read models. Every LLM call of a
turn (router, plan, analysts, synthesis) must be served by a recording: the gateway counts no miss. A
changed prompt, starter, tool, case catalog or member table changes a request hash and fails here instead
of in front of the audience; re-record with `sgw.agent.copilot.demo`."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from sgw.agent.copilot import demo
from sgw.agent.copilot import graph as copilot_graph
from sgw.agent.copilot.search import RecordedSearch
from sgw.agent.nodes.llm import GatewayClient, GatewayTags
from sgw.demo.bookmarks import BOOKMARKS

from ..agent_testkit import replay_gateway

JARGON = re.compile(r"\bN(?:\+1)?\b")
NOTHING_DUE = "Nothing is due in the next"


def test_the_web_offers_four_plain_starters_per_phase_and_no_advisory_question_after_landfall() -> None:
    before = demo.starters_for(datetime(2024, 9, 26, 15, 5, tzinfo=UTC))
    after = demo.starters_for(datetime(2024, 9, 27, 12, 0, tzinfo=UTC))
    for starters in (before, after):
        assert len(starters) == 4 and len(set(starters)) == 4
        assert not [q for q in starters if JARGON.search(q)]
    assert not [q for q in after if "latest advisory" in q]


def test_list_questions_are_answered_by_code_and_explanations_by_the_ai() -> None:
    assert copilot_graph.code_first("What do I need to decide in the next 3 hours?")
    assert copilot_graph.code_first("Which decisions keep Tallowbranch hospital supplied with water?")
    assert not copilot_graph.code_first("When do I have to revise a global ETR that is already out?")
    assert not copilot_graph.code_first("What does the latest advisory mean for PS-17's deadline?")


def test_the_matrix_covers_every_bookmark_and_every_question() -> None:
    matrix = demo.demo_matrix()
    assert {b for b, _, _ in matrix} == {b.id for b in BOOKMARKS}
    assert {q for _, _, q in matrix} == set(demo.demo_questions())


def counters(url: str) -> dict[str, int]:
    return {k: int(v) for k, v in httpx.get(f"{url}/healthz", timeout=5).json()["counters"].items()}


@pytest.mark.parametrize("engine", ["team", "single"])
async def test_every_demo_question_chain_hits_at_every_demo_bookmark(engine: str) -> None:
    search = RecordedSearch(demo.RECORDED_SEARCH)
    with replay_gateway() as url:
        llm = GatewayClient(url, tags=GatewayTags(purpose="test", wave="R29"))
        before = counters(url)
        turns = await demo.run_matrix(llm, search, engine)
        after = counters(url)
    missed = [(t.bookmark, t.as_of.isoformat(), t.question, t.reason) for t in turns if not t.replayed]
    assert missed == []
    assert after["replay_misses"] == before["replay_misses"]
    assert after["replay_hits"] > before["replay_hits"]
    answered = [t for t in turns if t.path == "llm"]
    assert answered and all(t.references for t in answered)


def test_the_presenters_ask_the_four_starters_at_the_moments_they_present_from() -> None:
    rows = demo.presenter_matrix()
    assert {u for _, _, _, (u, _) in rows} == {"ops_dm_01", "admin_01", "wtr_lead_01", "exec_01"}
    assert {b for b, _, _, _ in rows} == {"at-n1", "morning-after", "notices-lifted"}
    assert len(rows) == 4 * 3 * 4


def test_the_deadline_questions_are_asked_after_the_storm_by_every_demo_persona() -> None:
    rows = demo.deadline_matrix()
    assert {b for b, _, _, _ in rows} == {"morning-after", "notices-lifted"}
    assert {u for _, _, _, (u, _) in rows} == {"ic_01", "ops_dm_01", "admin_01", "wtr_lead_01", "exec_01"}
    assert len(rows) == 2 * 3 * 5


def test_the_default_engine_is_the_team() -> None:
    assert copilot_graph.default_engine() == "team"


async def test_the_team_never_breaks_on_any_demo_question_even_with_no_recording(tmp_path: Path) -> None:
    search = RecordedSearch(demo.RECORDED_SEARCH)
    with replay_gateway(tmp_path) as url:
        llm = GatewayClient(url, tags=GatewayTags(purpose="test", wave="R27"))
        turns = await demo.run_matrix(llm, search, "team")
    assert len(turns) == len(demo.team_rows())
    broken = [
        (t.bookmark, t.question[:30], t.path, t.reason)
        for t in turns
        if t.path != "m2" or not (t.references or NOTHING_DUE in t.text)
    ]
    assert broken == []


def test_the_exercise_starters_are_asked_by_every_presenter_at_every_pack_moment() -> None:
    rows = demo.pack_matrix()
    assert {b for b, _, _, _ in rows} == {"ian-day-before", "ian-landfall", "ian-morning-after"}
    assert {u for _, _, _, (u, _) in rows} == {"ic_01", "ops_dm_01", "admin_01", "wtr_lead_01", "exec_01"}
    assert {q for _, _, q, _ in rows} == set(demo.exercise_starters())
    assert len(rows) == 3 * 5 * 4
    assert not set(demo.exercise_starters()) & set(demo.demo_questions())


async def test_every_exercise_starter_chain_hits_at_every_pack_moment(tmp_path: Path) -> None:
    search = RecordedSearch(demo.RECORDED_SEARCH)
    with replay_gateway() as url:
        llm = GatewayClient(url, tags=GatewayTags(purpose="test", wave="R35"))
        before = counters(url)
        turns = await demo.run_pack_matrix(llm, search)
        after = counters(url)
    missed = [(t.bookmark, t.question, t.reason) for t in turns if not t.replayed]
    assert missed == []
    assert after["replay_misses"] == before["replay_misses"]
    with replay_gateway(tmp_path) as url:
        llm = GatewayClient(url, tags=GatewayTags(purpose="test", wave="R35"))
        unrecorded = await demo.run_pack_matrix(llm, search)
    assert [(t.bookmark, t.question[:30]) for t in unrecorded if t.path != "m2"] == []
