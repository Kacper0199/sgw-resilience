"""The Ask AI demo matrix: every demo question at every demo bookmark, run through the same graph and deps
as an API copilot run, to record it (`--gateway` in record mode) or to prove it replays (the coverage test).

Questions: the four starters the web offers (`web/src/features/ask/starters.json`) and the question of each
copilot bookmark run. Times: each bookmark's scenario time and run time. The member table is the API's;
search is the API's database search and the team's analysts read the platform read models of the
bookmark's database, as the API does after `sgw demo goto` (search recorded to `search_recorded.json`, read
models per bookmark under `demo_tools/`, both replayed in the test), so the request bodies are the API's.
Run: `uv run python -m sgw.agent.copilot.demo --gateway <url> --engine team --engine single` with
`SGW_ADMIN_DATABASE_URL` set: each bookmark's template is copied to a scratch database and read there."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

from sgw.agent.copilot import graph as copilot_graph
from sgw.agent.copilot.runner import LocalToolRunner, ToolRunner
from sgw.agent.copilot.search import DEMO_SEARCH, SearchFn
from sgw.agent.nodes.llm import GatewayClient, GatewayTags, LlmClient, LlmRequest, LlmResponse, LlmUnavailable
from sgw.agent.nodes.ports import InMemoryProposalPort
from sgw.agent.nodes.run_task import RunTask
from sgw.contracts.vocab import RunMode
from sgw.contracts.wire import WireEvent
from sgw.demo.bookmarks import BOOKMARKS
from sgw.models.clocks.advisory import TWIN_TABLE

REPO = Path(__file__).resolve().parents[4]
STARTERS_FILE = REPO / "web" / "src" / "features" / "ask" / "starters.json"
RECORDED_SEARCH = DEMO_SEARCH
RECORDED_TOOLS = REPO / "tests" / "unit" / "agent" / "copilot" / "data" / "demo_tools"
SCRATCH_DATABASE = "sgw_wp29_demo_ask"
ASKER = ("ic_01", "command")
PRESENTERS = (
    ("ops_dm_01", "operations"),
    ("admin_01", "platform"),
    ("wtr_lead_01", "water_operations"),
    ("exec_01", "executive"),
)
PRESENTER_MOMENTS = ("at-n1", "morning-after", "notices-lifted")
DEADLINE_QUESTIONS = tuple(f"What do I need to decide in the next {n} hours?" for n in (2, 3, 6))
DEADLINE_MOMENTS = ("morning-after", "notices-lifted")
PHASE_SETS = ("before_landfall", "after_landfall")
PACK_BASE_MOMENT = "before-n"


def _utc(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def starters_for(at: datetime) -> list[str]:
    """The web's four starters for the storm phase at `at` (`web/src/features/ask/starters.ts`)."""
    from sgw.api.scenario_phase import phase_at

    sets: dict[str, list[str]] = json.loads(STARTERS_FILE.read_text(encoding="utf-8"))
    return sets["before_landfall" if phase_at("helene", at) == "before_landfall" else "after_landfall"]


def key_run_questions() -> list[str]:
    return [str(b.run_input["question"]) for b in BOOKMARKS if b.run_graph == copilot_graph.GRAPH_ID]


def demo_questions(at: datetime | None = None) -> list[str]:
    """The questions offered at `at` (its phase's starters and the copilot bookmark's question); every phase's
    when `at` is None."""
    if at is None:
        sets: dict[str, list[str]] = json.loads(STARTERS_FILE.read_text(encoding="utf-8"))
        starters = [q for k in PHASE_SETS for q in sets[k]]
    else:
        starters = starters_for(at)
    return list(dict.fromkeys([*starters, *key_run_questions()]))


def demo_matrix() -> list[tuple[str, datetime, str]]:
    """(bookmark id, scenario time, question) for every question offered at every demo bookmark."""
    out: list[tuple[str, datetime, str]] = []
    for b in BOOKMARKS:
        for at in dict.fromkeys([_utc(b.scenario_time), _utc(b.run_at)]):
            out += [(b.id, at, q) for q in demo_questions(at)]
    return out


def presenter_matrix() -> list[tuple[str, datetime, str, tuple[str, str]]]:
    """The four starters for the presenter personas at the moments they load and present from (the team
    offers each role its own analysts, so their requests differ from the incident commander's)."""
    return [
        (b.id, _utc(b.scenario_time), q, asker)
        for b in BOOKMARKS
        if b.id in PRESENTER_MOMENTS
        for asker in PRESENTERS
        for q in starters_for(_utc(b.scenario_time))
    ]


def deadline_matrix() -> list[tuple[str, datetime, str, tuple[str, str]]]:
    """ "What do I need to decide in the next N hours?" at the after-storm moments, for the incident commander
    and the presenters (K3 P-K3-03)."""
    return [
        (b.id, _utc(b.scenario_time), q, asker)
        for b in BOOKMARKS
        if b.id in DEADLINE_MOMENTS
        for asker in (ASKER, *PRESENTERS)
        for q in DEADLINE_QUESTIONS
    ]


def team_rows() -> list[tuple[str, datetime, str, tuple[str, str]]]:
    """Every row the team answers: the matrix, the presenters' starters and the deadline family, each once."""
    rows = [(b, at, q, ASKER) for b, at, q in demo_matrix()] + presenter_matrix() + deadline_matrix()
    return list(dict.fromkeys(rows))


def exercise_starters() -> list[str]:
    """The four starters the web offers on a scenario pack (`EXERCISE_STARTERS` in `starters.ts`)."""
    sets: dict[str, list[str]] = json.loads(STARTERS_FILE.read_text(encoding="utf-8"))
    return list(sets["exercise"])


def pack_moments() -> list[tuple[str, str, datetime]]:
    """(scenario, moment id, scenario time) of every moment of every scenario pack, in the pack's order."""
    from sgw.scenarios import packs

    return [(name, m.moment_id, m.at) for name in packs.names() for m in packs.load(name).moments]


def pack_matrix() -> list[tuple[str, datetime, str, tuple[str, str]]]:
    """The exercise starters for the incident commander and every presenter at each pack moment: presenters
    load the pack and jump between its moments, and every one of them may open Ask there (defect 4)."""
    return [
        (moment, at, q, asker)
        for _, moment, at in pack_moments()
        for asker in (ASKER, *PRESENTERS)
        for q in exercise_starters()
    ]


def pack_of(moment: str) -> str:
    """The scenario a pack moment belongs to; Helene for a demo bookmark."""
    return next((name for name, m, _ in pack_moments() if m == moment), "helene")


@dataclass
class DemoTurn:
    bookmark: str
    as_of: datetime
    question: str
    route_path: str
    code_first: bool
    path: str
    reason: str | None
    text: str
    tools: list[str]
    references: list[dict[str, str]]

    @property
    def replayed(self) -> bool:
        """Answered as designed: a question code answers (`graph.code_first`, no model call), or both LLM
        steps from a recording: the router's and the answer's (a checked model answer, or the model's own
        not-in-the-documents)."""
        if self.code_first:
            return self.reason is None
        return self.route_path == "llm" and self.reason in (None, "model_not_in_documents")


def member_table() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(TWIN_TABLE.read_text(encoding="utf-8"))
    return data


async def ask(
    bookmark: str,
    as_of: datetime,
    question: str,
    *,
    llm: LlmClient,
    search: SearchFn,
    engine: str,
    runner: ToolRunner | None = None,
    asker: tuple[str, str] = ASKER,
    scenario: str = "helene",
) -> DemoTurn:
    """One demo turn through the API's graph; on a scenario pack with the scenario and period line the API
    passes there (`graph.with_clock`)."""
    pack = scenario != "helene"
    deps = copilot_graph.CopilotDeps(
        llm=llm,
        proposals=InMemoryProposalPort(),
        member_table=member_table(),
        search=search,
        engine=engine,
        runner=runner or LocalToolRunner(),
        scenario=scenario,
        period=copilot_graph.period_line(scenario) if pack else None,
    )
    task = RunTask(
        run_id=f"demo-{bookmark}",
        thread_id=f"demo-{bookmark}",
        graph_id=copilot_graph.GRAPH_ID,
        graph=copilot_graph.build(),
        deps=deps,
        user_id=asker[0],
        user_role=asker[1],
        run_mode=RunMode.REPLAY,
        run_input={"question": question, "as_of": as_of.isoformat()},
    )
    await task.run()
    state = await task.state()
    (answer,) = [
        f.payload
        for f in task.frames
        if f.type is WireEvent.ARTIFACT and (f.payload or {}).get("role") == "assistant"
    ]
    return DemoTurn(
        bookmark=bookmark,
        as_of=as_of,
        question=question,
        route_path=str((state.get("route") or {}).get("path")),
        code_first=any(a.get("kind") == "platform_answer" for a in state.get("audit") or []),
        path=str(answer["path"]),
        reason=copilot_graph.answer_reason(answer),
        text=str(answer["text"]),
        tools=[str(f.payload["tool"]) for f in task.frames if f.type is WireEvent.TOOL_START],
        references=list(answer.get("references") or []),
    )


def recorded_tools(bookmark: str) -> Path:
    return RECORDED_TOOLS / f"{bookmark}.json"


def recorded_runner(bookmark: str) -> ToolRunner:
    from sgw.agent.copilot.runner import RecordedToolRunner

    return RecordedToolRunner(recorded_tools(bookmark))


async def run_matrix(
    llm: LlmClient,
    search: SearchFn,
    engine: str,
    runner_for: Callable[[str], ToolRunner] = recorded_runner,
    bookmarks: Collection[str] | None = None,
) -> list[DemoTurn]:
    rows = team_rows() if engine == "team" else [(b, at, q, ASKER) for b, at, q in demo_matrix()]
    return [
        await ask(b, at, q, llm=llm, search=search, engine=engine, runner=runner_for(b), asker=asker)
        for b, at, q, asker in rows
        if bookmarks is None or b in bookmarks
    ]


async def run_pack_matrix(
    llm: LlmClient,
    search: SearchFn,
    runner_for: Callable[[str], ToolRunner] = recorded_runner,
    moments: Collection[str] | None = None,
) -> list[DemoTurn]:
    """The exercise starters at the pack moments, on the team (the API's engine)."""
    return [
        await ask(
            m,
            at,
            q,
            llm=llm,
            search=search,
            engine="team",
            runner=runner_for(m),
            asker=asker,
            scenario=pack_of(m),
        )
        for m, at, q, asker in pack_matrix()
        if moments is None or m in moments
    ]


class NoLlm:
    """Every model call unavailable: the team's code path, whose searches the no-recording test replays."""

    async def create(self, request: LlmRequest) -> LlmResponse:
        raise LlmUnavailable("replay_miss", request.node)


def _same(runner: ToolRunner, _bookmark: str) -> ToolRunner:
    return runner


def _dsn(admin_url: str, database: str) -> str:
    from psycopg.conninfo import make_conninfo

    return make_conninfo(admin_url, dbname=database)


def scenario_jobs_after_load(dsn: str, at: datetime) -> None:
    """What the demo API does after `sgw demo goto`: the advisory queue, and with `SGW_ZONE_RULES` /
    `SGW_SCENARIO_INJECTS` on the zone rules and the exercise injects, at the moment's scenario time, so the
    recorded read models are the ones the demo stack's Ask reads (`sgw.api.scenario_jobs.after_load`, the
    same jobs `sgw demo goto` runs)."""
    from sgw.api import scenario_jobs
    from sgw.models.clocks import zone_cases

    if not (zone_cases.enabled() or zone_cases.injects_enabled()):
        return
    scenario_jobs.after_load(dsn, at)


async def record(
    llm: LlmClient,
    admin_url: str,
    database: str,
    engines: list[str],
    bookmarks: Collection[str] | None,
) -> list[tuple[str, DemoTurn]]:
    """Each bookmark's template copied to `database` (as `sgw demo goto` does for the API), then every demo
    question there on each engine, and once more on the team's code path (no model); search and the bookmark's
    read models are recorded for the tests. Run it with the demo stack's flags (`SGW_ZONE_RULES=1
    SGW_SCENARIO_INJECTS=1`) so each moment holds what the stack's scenario jobs raise there."""
    import psycopg

    from sgw.agent.copilot.runner import PlatformToolRunner, RecordingToolRunner
    from sgw.agent.copilot.search import DbSearch, RecordingSearch
    from sgw.agent.tools.reads import DbReads
    from sgw.demo.bookmarks import bookmark as find_bookmark
    from sgw.demo.snapshots import goto

    dsn = _dsn(admin_url, database)
    search = RecordingSearch(DbSearch(lambda: psycopg.connect(dsn, autocommit=True)))
    turns: list[tuple[str, DemoTurn]] = []
    for b in dict.fromkeys(row[0] for row in demo_matrix()):
        if bookmarks and b not in bookmarks:
            continue
        found = find_bookmark(b)
        goto(admin_url, found, database)
        scenario_jobs_after_load(dsn, _utc(found.scenario_time))
        tools = RecordingToolRunner(PlatformToolRunner(DbReads(dsn)))
        for engine in engines:
            for t in await run_matrix(llm, search, engine, partial(_same, tools), {b}):
                turns.append((engine, t))
        await run_matrix(NoLlm(), search, "team", partial(_same, tools), {b})
        RECORDED_TOOLS.mkdir(parents=True, exist_ok=True)
        tools.save(recorded_tools(b))
    search.save(RECORDED_SEARCH)
    return turns


def pack_jobs(dsn: str, at: datetime, scenario: str) -> None:
    """What the demo API does after Load scenario and after each clock jump on a pack: the pack's injects
    and the expiry at the moment's time (`sgw.api.scenario_jobs.run_pack`, approval rules from
    `ReferencePolicy`, as `after_load` does for Helene)."""
    from sgw.api import scenario_jobs
    from sgw.approval.ledger import default_sink
    from sgw.approval.policy import ReferencePolicy
    from sgw.approval.service import ApprovalService

    service = ApprovalService(ReferencePolicy(), scenario_clock=lambda: at, ledger=default_sink())
    scenario_jobs.run_pack(dsn, at, service, scenario)


async def record_packs(
    llm: LlmClient, admin_url: str, database: str, moments: Collection[str] | None
) -> list[tuple[str, DemoTurn]]:
    """Each pack as a presenter runs it: Load scenario copies the quiet Helene template and runs the
    pack's jobs at its first moment; each later moment is a clock jump that runs them again on the same
    database. The exercise starters are asked at every moment (and once more with no model), the pack
    reads and search recorded like the Helene matrix."""
    import psycopg

    from sgw.agent.copilot.runner import PlatformToolRunner, RecordingToolRunner
    from sgw.agent.copilot.search import DbSearch, RecordingSearch
    from sgw.agent.tools.reads import PackReads
    from sgw.demo.bookmarks import bookmark as find_bookmark
    from sgw.demo.snapshots import goto

    dsn = _dsn(admin_url, database)
    search = RecordingSearch(DbSearch(lambda: psycopg.connect(dsn, autocommit=True)))
    turns: list[tuple[str, DemoTurn]] = []
    loaded: str | None = None
    for scenario, moment, at in pack_moments():
        if loaded != scenario:
            goto(admin_url, find_bookmark(PACK_BASE_MOMENT), database)
            loaded = scenario
        pack_jobs(dsn, at, scenario)
        if moments and moment not in moments:
            continue
        tools = RecordingToolRunner(PlatformToolRunner(PackReads(dsn, scenario)))
        for t in await run_pack_matrix(llm, search, partial(_same, tools), {moment}):
            turns.append(("team", t))
        await run_pack_matrix(NoLlm(), search, partial(_same, tools), {moment})
        RECORDED_TOOLS.mkdir(parents=True, exist_ok=True)
        tools.save(recorded_tools(moment))
    search.save(RECORDED_SEARCH)
    return turns


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", required=True)
    ap.add_argument("--admin-url-env", default="SGW_ADMIN_DATABASE_URL")
    ap.add_argument("--database", default=SCRATCH_DATABASE)
    ap.add_argument("--purpose", default="record")
    ap.add_argument("--wave", default="R29")
    ap.add_argument("--engine", action="append", choices=sorted(copilot_graph.ENGINES))
    ap.add_argument("--bookmark", action="append")
    ap.add_argument("--packs", action="store_true", help="the scenario packs' moments instead of Helene's")
    a = ap.parse_args()
    client = GatewayClient(a.gateway, tags=GatewayTags(purpose=a.purpose, wave=a.wave))
    admin = os.environ[a.admin_url_env]
    turns = asyncio.run(
        record_packs(client, admin, a.database, a.bookmark)
        if a.packs
        else record(client, admin, a.database, a.engine or ["team"], a.bookmark)
    )
    for engine, t in turns:
        mark = "hit" if t.replayed else "MISS"
        print(f"{mark} {engine:<6} {t.bookmark:<14} {t.as_of:%m-%d %H:%M} {t.path:<16} {t.question[:60]}")
    print(f"{sum(t.replayed for _, t in turns)}/{len(turns)} answered by the model")


if __name__ == "__main__":
    main()
