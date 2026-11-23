"""Ask AI eval v1 (AX §4): the copilot end to end on `evals/ask/ask_v1.yaml`, the single loop (A)
against the team (C), and the team's nodes on Haiku and Sonnet.

Code graders per item: `success` (expected kind of answer: a checked model answer, or the platform answer
for list questions code answers by design; every `required` id and one `any_of` id in the
answer text; a checked citation when `cite`; no `forbidden` text; no write attempt), `grounded` (the answer
names an id or a citation of this run's evidence), `routing` (team: every gold worker planned), `fallback`
(an LLM step answered by code), latency and cost per turn (usage priced at list prices, `budget.cost`).
Node comparison: the plan on every item and each gold worker on its single-domain items, Haiku against Sonnet.

Live: `--gateway <record gateway> --live` reads search, the R27 read models and the decision clocks from
`SGW_DATABASE_URL` and records search and tool results under `evals/ask/`; keyless: the replay gateway on
`evals/ask/llm/` with the recorded search and tools gives the same grades (`test_ask_eval_replay.py`).
The eval measures the R29 freeze, so it runs the team on the node prompts of that freeze
(`evals/ask/llm_nodes_r29.yaml`, the main node file at bed5da2) whatever the live node file says.
Run: `uv run python -m sgw.agent.copilot_eval.run --gateway <url> [--live] [--split dev] --out <json>`."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from sgw.agent.copilot import graph as copilot_graph
from sgw.agent.copilot.budget import cost
from sgw.agent.copilot.plan import NODE as PLAN
from sgw.agent.copilot.plan import known_ids, make_plan
from sgw.agent.copilot.runner import RecordedToolRunner, ToolRunner
from sgw.agent.copilot.search import RecordedSearch, SearchFn
from sgw.agent.copilot.tools import clock_context
from sgw.agent.copilot.workers import BY_NAME, WorkerTask, offered, run_worker
from sgw.agent.nodes.llm import MODEL_IDS, LlmClient, LlmRequest, LlmResponse, node_config
from sgw.agent.nodes.ports import InMemoryProposalPort
from sgw.agent.nodes.run_task import RunTask
from sgw.contracts.identities import load_users
from sgw.contracts.tools import InjectedContext
from sgw.contracts.vocab import ApprovalFunction, Classification, RunMode
from sgw.contracts.wire import WireEvent
from sgw.models.clocks.advisory import TWIN_TABLE

REPO = Path(__file__).resolve().parents[4]
ASK = REPO / "evals" / "ask"
ITEMS = ASK / "ask_v1.yaml"
LLM_DIR = ASK / "llm"
SEARCH = ASK / "search.json"
TOOLS_FILE = ASK / "tools.json"
EVAL_NODES = ASK / "eval_nodes.yaml"
FROZEN_NODES = ASK / "llm_nodes_r29.yaml"
USERS = REPO / "data" / "seed" / "users.yaml"
ALIASES = {model_id: alias for alias, model_id in MODEL_IDS.items()}
ENGINES = ("single", "team")
POLICY_CODE = "team_policy_code"
NODE_MODELS = ("haiku", "sonnet")


def load(split: str | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = yaml.safe_load(ITEMS.read_text(encoding="utf-8"))["items"]
    return [i for i in items if split is None or i["split"] == split]


def functions() -> dict[str, str]:
    return {u.user_id: u.function.value for u in load_users(USERS).users}


def member_table() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(TWIN_TABLE.read_text(encoding="utf-8"))
    return data


def _utc(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


@dataclass
class Meter:
    """Wraps the LLM client: every call's node, model and priced usage."""

    inner: LlmClient
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def create(self, request: LlmRequest) -> LlmResponse:
        response = await self.inner.create(request)
        alias = ALIASES.get(response.model, request.model_override or request.config.model.value)
        self.calls.append({"node": request.node, "model": alias, "usd": cost(alias, response.usage)})
        return response

    def take(self) -> list[dict[str, Any]]:
        out, self.calls = self.calls, []
        return out


def code_answer(answer: Mapping[str, Any]) -> bool:
    """A list question answered from the decision queue by design (`graph.code_first`): the platform answer
    with no failure reason; a fallback always carries one."""
    return answer["path"] == "m2" and copilot_graph.answer_reason(dict(answer)) is None


def grade(
    item: Mapping[str, Any], answer: Mapping[str, Any], workers: Sequence[str] | None
) -> dict[str, Any]:
    text = str(answer["text"])
    refused = answer.get("reason") == "out_of_scope"
    if item["expect"] == "refuse":
        kind_ok = refused or answer["path"] == "not_in_documents"
    else:
        kind_ok = answer["path"] == "llm" or code_answer(answer)
    required = all(i in text for i in item.get("required") or [])
    any_of = not item.get("any_of") or any(i in text for i in item["any_of"])
    cited = bool(answer.get("citations")) or not item.get("cite")
    clean = not any(f in text for f in item.get("forbidden") or [])
    grounded = bool(answer.get("references") or answer.get("citations"))
    success = (
        kind_ok and required and any_of and cited and clean and int(answer.get("write_attempts") or 0) == 0
    )
    gold = set(item.get("gold") or [])
    return {
        "path": answer["path"],
        "reason": copilot_graph.answer_reason(dict(answer)),
        "success": success,
        "grounded": grounded or item["expect"] == "refuse",
        "routing": gold <= set(workers) if gold and workers is not None else None,
        "required_named": required and any_of,
        "cited": cited,
    }


async def ask_once(
    item: Mapping[str, Any],
    engine: str,
    *,
    llm: Meter,
    search: SearchFn,
    runner: ToolRunner,
    users: Mapping[str, str],
) -> dict[str, Any]:
    deps = copilot_graph.CopilotDeps(
        llm=llm,
        proposals=InMemoryProposalPort(),
        member_table=member_table(),
        search=search,
        engine="team" if engine == POLICY_CODE else engine,
        runner=runner,
        code_only=frozenset({"policy"}) if engine == POLICY_CODE else frozenset(),
        nodes_file=FROZEN_NODES,
    )
    task = RunTask(
        run_id=f"ask-eval-{item['id']}",
        thread_id=f"ask-eval-{item['id']}",
        graph_id=copilot_graph.GRAPH_ID,
        graph=copilot_graph.build(),
        deps=deps,
        user_id=str(item["user"]),
        user_role=users[str(item["user"])],
        run_mode=RunMode.REPLAY,
        run_input={"question": item["question"], "as_of": item["as_of"]},
    )
    started = time.monotonic()
    await task.run()
    seconds = time.monotonic() - started
    state = await task.state()
    (answer,) = [
        f.payload
        for f in task.frames
        if f.type is WireEvent.ARTIFACT and (f.payload or {}).get("role") == "assistant"
    ]
    plan = [a for a in state.get("audit") or [] if a.get("kind") == "plan"]
    lanes = [a for a in state.get("audit") or [] if a.get("kind") == "worker"]
    calls = llm.take()
    return {
        "id": item["id"],
        "engine": engine,
        **grade(item, answer, [w for p in plan for w in [*p["workers"], *p["followup"]]] if plan else None),
        "workers": [f"{a['worker']}:{a['path']}" for a in lanes],
        "fallback": any(a["path"] == "code" for a in lanes)
        or (answer["path"] == "m2" and item["expect"] == "answer"),
        "llm_calls": len(calls),
        "usd": round(sum(c["usd"] for c in calls), 6),
        "seconds": round(seconds, 2),
        "text": str(answer["text"])[:600],
    }


async def nodes(
    items: Sequence[Mapping[str, Any]],
    *,
    llm: Meter,
    search: SearchFn,
    runner: ToolRunner,
    users: Mapping[str, str],
) -> list[dict[str, Any]]:
    """The plan on every item and each gold worker of a single-domain item, on Haiku and on Sonnet."""
    table = member_table()
    period = copilot_graph.default_period()
    rows: list[dict[str, Any]] = []
    for model in NODE_MODELS:
        for item in items:
            role = users[str(item["user"])]
            ctx = ctx_for(item, role)
            clock = clock_context(ctx, table)
            workers = offered(role, runner)
            if item["expect"] == "answer":
                plan = await make_plan(
                    item["question"],
                    {"intent": None, "entity_ids": []},
                    llm=llm,
                    config=node_config(PLAN, FROZEN_NODES),
                    workers=workers,
                    member_table=table,
                    as_of=clock.as_of,
                    stamp=clock.as_of.strftime("%Y-%m-%dT%H:%MZ"),
                    period=period,
                    known=known_ids(table, clock.as_of),
                    run_id=f"ask-node-{item['id']}",
                    model_override=model,
                )
                planned = {t.worker for t in [*plan.tasks, *plan.followup]}
                gold = set(item["gold"])
                rows.append(
                    {
                        "id": item["id"],
                        "node": PLAN,
                        "model": model,
                        "passed": plan.path == "llm" and gold <= planned and len(planned - gold) <= 1,
                        "planned": sorted(planned),
                        "usd": round(sum(c["usd"] for c in llm.take()), 6),
                    }
                )
            if item["expect"] == "answer" and len(item["gold"]) == 1:
                spec = BY_NAME[item["gold"][0]]
                finding = await run_worker(
                    spec,
                    WorkerTask(spec.name, item["question"], ()),
                    ctx,
                    llm=llm,
                    config=node_config(spec.node, FROZEN_NODES),
                    member_table=table,
                    runner=runner,
                    search=search,
                    period=period,
                    run_id=f"ask-node-{item['id']}",
                    model_override=model,
                    timeout_s=120.0,
                )
                text = finding.text
                rows.append(
                    {
                        "id": item["id"],
                        "node": spec.node,
                        "model": model,
                        "passed": finding.path in ("llm", "not_in_documents")
                        and not finding.violations
                        and all(i in text for i in item.get("required") or [])
                        and (bool(finding.citations) or not item.get("cite")),
                        "path": finding.path,
                        "reason": finding.reason,
                        "violations": finding.violations[:3],
                        "usd": round(sum(c["usd"] for c in llm.take()), 6),
                    }
                )
    return rows


def ctx_for(item: Mapping[str, Any], role: str) -> InjectedContext:
    return InjectedContext(
        as_of=_utc(str(item["as_of"])),
        user_id=str(item["user"]),
        user_role=ApprovalFunction(role),
        region_ids=["SC-45003"],
        run_mode=RunMode.REPLAY,
        classification_ceiling=Classification.C1,
    )


def _share(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    values = [r[key] for r in rows if r.get(key) is not None]
    return round(sum(bool(v) for v in values) / len(values), 3) if values else None


def summarise(turns: Sequence[Mapping[str, Any]], node_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    engines: dict[str, Any] = {}
    for engine in (*ENGINES, POLICY_CODE):
        rows = [t for t in turns if t["engine"] == engine]
        if not rows:
            continue
        secs = sorted(t["seconds"] for t in rows)
        engines[engine] = {
            "n": len(rows),
            "success": _share(rows, "success"),
            "grounded": _share(rows, "grounded"),
            "routing": _share(rows, "routing"),
            "fallback": _share(rows, "fallback"),
            "usd_per_turn": round(statistics.mean(t["usd"] for t in rows), 4),
            "llm_calls_per_turn": round(statistics.mean(t["llm_calls"] for t in rows), 2),
            "seconds_p50": round(statistics.median(secs), 2),
            "seconds_p95": secs[min(len(secs) - 1, int(round(0.95 * (len(secs) - 1))))],
        }
    by_node: dict[str, dict[str, Any]] = {}
    for r in node_rows:
        s = by_node.setdefault(f"{r['node']}:{r['model']}", {"n": 0, "passed": 0, "usd": 0.0})
        s["n"] += 1
        s["passed"] += int(bool(r["passed"]))
        s["usd"] = round(s["usd"] + r["usd"], 6)
    on = [t for t in turns if t["engine"] == "team" and t.get("policy_item")]
    off = [t for t in turns if t["engine"] == POLICY_CODE]
    policy = {
        "items": len(off),
        "success_model_step": _share(on, "success"),
        "success_code_only": _share(off, "success"),
        "usd_model_step": round(statistics.mean(t["usd"] for t in on), 4) if on else None,
        "usd_code_only": round(statistics.mean(t["usd"] for t in off), 4) if off else None,
    }
    return {"engines": engines, "nodes": by_node, "policy_analyst": policy}


async def run_all(
    llm: LlmClient,
    *,
    search: SearchFn,
    runner: ToolRunner,
    split: str | None = "dev",
    engines: Sequence[str] = ENGINES,
    with_nodes: bool = True,
) -> dict[str, Any]:
    meter = Meter(llm)
    users = functions()
    items = load(split)
    turns = [
        await ask_once(item, engine, llm=meter, search=search, runner=runner, users=users)
        for engine in engines
        for item in items
    ]
    policy_items = [i for i in items if "policy" in (i.get("gold") or [])]
    turns += [
        await ask_once(item, POLICY_CODE, llm=meter, search=search, runner=runner, users=users)
        for item in policy_items
    ]
    for t in turns:
        if t["engine"] == "team" and t["id"] in {i["id"] for i in policy_items}:
            t["policy_item"] = True
    node_rows = await nodes(items, llm=meter, search=search, runner=runner, users=users) if with_nodes else []
    return {
        "set": "ask_v1",
        "split": split,
        "summary": summarise(turns, node_rows),
        "turns": turns,
        "nodes": node_rows,
        "limits": [
            "items written by the AI builder, not an independent eval author",
            "every item reads the at-n1 bookmark database; n is small (dev 20)",
            "latency measured on the live recording run; a replay rerun is not a latency measurement",
        ],
    }


def main() -> None:
    from sgw.agent.tools.personas import EXTRA

    EXTRA["on"] = False
    from sgw.agent.copilot.search import DbSearch, RecordingSearch
    from sgw.agent.nodes.llm import GatewayClient, GatewayTags

    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", required=True)
    ap.add_argument("--live", action="store_true", help="search and read models on SGW_DATABASE_URL")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--purpose", default="eval")
    ap.add_argument("--wave", default="R27")
    ap.add_argument("--no-nodes", action="store_true")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    client = GatewayClient(a.gateway, tags=GatewayTags(purpose=a.purpose, wave=a.wave))
    recorder_search: RecordingSearch | None = None
    recorder_tools: Any = None
    search: SearchFn
    runner: ToolRunner
    if a.live:
        import psycopg

        from sgw.agent.copilot.runner import PlatformToolRunner, RecordingToolRunner
        from sgw.agent.tools.reads import DbReads

        dsn = os.environ["SGW_DATABASE_URL"]
        recorder_search = RecordingSearch(DbSearch(lambda: psycopg.connect(dsn, autocommit=True)))
        recorder_tools = RecordingToolRunner(PlatformToolRunner(DbReads(dsn)))
        search, runner = recorder_search, recorder_tools
    else:
        search, runner = RecordedSearch(SEARCH), RecordedToolRunner(TOOLS_FILE)
    report = asyncio.run(
        run_all(client, search=search, runner=runner, split=a.split or None, with_nodes=not a.no_nodes)
    )
    if recorder_search is not None:
        recorder_search.save(SEARCH)
        recorder_tools.save(TOOLS_FILE)
    if a.out:
        a.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
