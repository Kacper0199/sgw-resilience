"""Model choice for the team nodes (working-rules §4): the plan and two workers (Water, Policy) on Haiku and
Sonnet, on `team_dev.yaml`, code graders only. Plan: passes when it holds every gold worker and at most one
extra. Workers: the worker answered on the model path (no fallback), its text passed the checks (no digits,
no unknown ids), it named every required id, made no refused call, and policy answers cite a passage. Search
runs live and is recorded (`--live-search`) or replays the recording, so a keyless rerun gives the same
grades (`test_team_eval_replay.py`).
Run: `uv run python -m sgw.agent.copilot.team_eval --gateway <url> [--live-search] --out <json>`."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from sgw.agent.copilot.graph import default_period
from sgw.agent.copilot.plan import NODE as PLAN
from sgw.agent.copilot.plan import known_ids, make_plan
from sgw.agent.copilot.runner import LocalToolRunner
from sgw.agent.copilot.search import RecordedSearch, SearchFn
from sgw.agent.copilot.tools import clock_context
from sgw.agent.copilot.workers import BY_NAME, WORKERS, WorkerTask, run_worker
from sgw.agent.nodes.llm import GatewayClient, GatewayTags, LlmClient, node_config
from sgw.agent.route.intent import NODE as ROUTE
from sgw.agent.route.intent import route_intent
from sgw.contracts.llm_nodes import NodeConfig
from sgw.contracts.tools import InjectedContext
from sgw.contracts.vocab import ApprovalFunction, Classification, RunMode
from sgw.models.clocks.advisory import TWIN_TABLE

HERE = Path(__file__).resolve().parent
DEV = HERE / "team_dev.yaml"
REPO = HERE.parents[3]
DATA = REPO / "tests" / "unit" / "agent" / "copilot" / "data"
RECORDED_SEARCH = DATA / "team_search_recorded.json"
EVAL_NODES = DATA / "team_eval_nodes.yaml"
MODELS = ("haiku", "sonnet")


def load() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(DEV.read_text(encoding="utf-8"))
    return data


def ctx_at(raw: str) -> InjectedContext:
    return InjectedContext(
        as_of=datetime.fromisoformat(raw.replace("Z", "+00:00")),
        user_id="ic_01",
        user_role=ApprovalFunction.COMMAND,
        region_ids=["SC-45003"],
        run_mode=RunMode.REPLAY,
        classification_ceiling=Classification.C1,
    )


def member_table() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(TWIN_TABLE.read_text(encoding="utf-8"))
    return data


def grade_plan(item: Mapping[str, Any], workers: Sequence[str]) -> bool:
    gold = set(item["gold"])
    return gold <= set(workers) and len(set(workers) - gold) <= 1


def grade_worker(item: Mapping[str, Any], finding: Mapping[str, Any]) -> dict[str, Any]:
    text = str(finding["text"])
    refused = sum(c["status"] == "refused" for c in finding["tool_calls"])
    named = all(i in text for i in item.get("required") or [])
    cited = bool(finding["citations"]) or not item.get("cite")
    return {
        "path": finding["path"],
        "reason": finding["reason"],
        "violations": finding["violations"],
        "named_required": named,
        "cited": cited,
        "refused_calls": refused,
        "llm_calls": finding["llm_calls"],
        "text": text,
        "passed": finding["path"] == "llm" and not finding["violations"] and named and cited and refused == 0,
    }


MEASURED_PROMPT = "v1"


def measured(node: str) -> NodeConfig:
    """The node as this eval measured it: on the v1 prompts (the R27 model choice); the freeze prompts are
    measured by the Ask eval (`sgw.agent.copilot_eval.run`)."""
    return node_config(node).model_copy(update={"prompt_version": MEASURED_PROMPT})


async def run_all(llm: LlmClient, search: SearchFn) -> dict[str, Any]:
    data = load()
    ctx = ctx_at(str(data["as_of"]))
    table = member_table()
    clock = clock_context(ctx, table)
    stamp = clock.as_of.strftime("%Y-%m-%dT%H:%MZ")
    known = known_ids(table, clock.as_of)
    rows: list[dict[str, Any]] = []
    for model in MODELS:
        for item in data["plan"]:
            r = await route_intent(
                item["question"], llm=llm, config=node_config(ROUTE), run_id=f"team-{item['id']}"
            )
            plan = await make_plan(
                item["question"],
                r.model_dump(mode="json"),
                llm=llm,
                config=measured(PLAN),
                workers=list(WORKERS),
                member_table=table,
                as_of=clock.as_of,
                stamp=stamp,
                period=default_period(),
                known=known,
                run_id=f"team-{item['id']}",
                model_override=model,
            )
            workers = [t.worker for t in [*plan.tasks, *plan.followup]]
            rows.append(
                {
                    "id": item["id"],
                    "node": PLAN,
                    "model": model,
                    "path": plan.path,
                    "workers": [t.worker for t in plan.tasks],
                    "followup": [t.worker for t in plan.followup],
                    "passed": plan.path == "llm" and grade_plan(item, workers),
                }
            )
        for item in data["workers"]:
            spec = BY_NAME[item["worker"]]
            finding = await run_worker(
                spec,
                WorkerTask(spec.name, item["task"], tuple(item.get("entity_ids") or ())),
                ctx,
                llm=llm,
                config=measured(spec.node),
                member_table=table,
                runner=LocalToolRunner(),
                search=search,
                period=default_period(),
                run_id=f"team-{item['id']}",
                model_override=model,
                timeout_s=120.0,
            )
            rows.append(
                {
                    "id": item["id"],
                    "node": spec.node,
                    "model": model,
                    **grade_worker(item, finding.as_state()),
                }
            )
    return {"set": "team_dev", "summary": summarise(rows), "rows": rows}


def summarise(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for r in rows:
        key = f"{r['node']}:{r['model']}"
        s = out.setdefault(key, {"n": 0, "passed": 0})
        s["n"] += 1
        s["passed"] += int(bool(r["passed"]))
    return out


def main() -> None:
    from sgw.agent.tools.personas import EXTRA

    EXTRA["on"] = False
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", required=True)
    ap.add_argument("--purpose", default="eval")
    ap.add_argument("--wave", default="R27")
    ap.add_argument("--live-search", action="store_true")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    from sgw.agent.copilot.search import DbSearch, RecordingSearch

    recorder: RecordingSearch | None = None
    search: SearchFn
    if a.live_search:
        import psycopg

        dsn = os.environ["SGW_DATABASE_URL"]
        recorder = RecordingSearch(DbSearch(lambda: psycopg.connect(dsn, autocommit=True)))
        search = recorder
    else:
        search = RecordedSearch(RECORDED_SEARCH)
    client = GatewayClient(a.gateway, tags=GatewayTags(purpose=a.purpose, wave=a.wave))
    report = asyncio.run(run_all(client, search))
    if recorder is not None:
        recorder.save(RECORDED_SEARCH, merge=False)
    if a.out:
        a.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
