"""Agent runs read model (D-087 Health "AI runs", WP-27 Runs tab).

- runs: K1 `agent_run` rows (graph, mode, K1 status, times, taint, class) with tokens, cost, node and model
  lists aggregated from the gateway's `llm_call` rows of the run (`agent_run` token columns are not written
  by the run store, so `llm_call` is the one source);
- steps of one run: graph node tasks from the LangGraph checkpoint writes of the run's checkpoint thread
  (`<thread_id>:<run_id>`, `run_task.RunTask.config`) with the checkpoint time, every LLM call, and the
  copilot team's analyst lanes, tool calls and checks from the run's audit writes (worker, tool, status, at
  most two flat id arguments, timings), merged in time order. Never read: prompts, outputs, other state
  values, request or payload hashes.

Visibility: a user sees their own runs; platform, command, executive, data and audit see every run."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from sgw.contracts.api_models import AgentRunDetail, AgentRunStep, AgentRunSummary
from sgw.contracts.vocab import ApprovalFunction

ALL_RUNS_FUNCTIONS = frozenset(
    {
        ApprovalFunction.PLATFORM,
        ApprovalFunction.COMMAND,
        ApprovalFunction.EXECUTIVE,
        ApprovalFunction.DATA,
        ApprovalFunction.AUDIT,
    }
)
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MLFLOW_UI_ENV = "SGW_MLFLOW_UI_URL"
PULL_PREFIX = "~__pregel_pull, "
INTERNAL_NODES = frozenset({"__start__", "__end__"})

_RUNS = """
SELECT r.run_id, r.thread_id, r.graph, r.graph_version, r.user_id, r.run_mode::text AS run_mode, r.status,
       r.started_at, r.ended_at, r.tainted, r.classification::text AS classification, r.trace_id,
       count(c.call_id) AS llm_calls,
       count(c.call_id) FILTER (WHERE c.billed) AS billed_calls,
       coalesce(sum(c.input_tokens + c.cache_creation_input_tokens + c.cache_read_input_tokens), 0)
           AS tokens_in,
       coalesce(sum(c.output_tokens), 0) AS tokens_out,
       coalesce(sum(c.cost_usd_micros), 0) AS cost_usd_micros,
       coalesce(array_agg(c.node ORDER BY c.ts, c.call_id) FILTER (WHERE c.call_id IS NOT NULL), '{}')
           AS nodes,
       coalesce(array_agg(DISTINCT c.model) FILTER (WHERE c.call_id IS NOT NULL), '{}') AS models
FROM agent_run r LEFT JOIN llm_call c ON c.run_id = r.run_id
WHERE (%(user_id)s::text IS NULL OR r.user_id = %(user_id)s)
  AND (%(run_id)s::text IS NULL OR r.run_id = %(run_id)s)
  AND (%(graph)s::text IS NULL OR r.graph = %(graph)s)
  AND (%(status)s::text IS NULL OR r.status = %(status)s)
GROUP BY r.run_id
ORDER BY r.started_at DESC, r.run_id
LIMIT %(limit)s
"""

GRAPH_STEPS = """
SELECT w.task_path, min(w.checkpoint_id) AS checkpoint_id, (cp.checkpoint->>'ts')::timestamptz AS at
FROM lg.checkpoint_writes w
JOIN lg.checkpoints cp
  ON cp.thread_id = w.thread_id AND cp.checkpoint_ns = w.checkpoint_ns AND cp.checkpoint_id = w.checkpoint_id
WHERE w.thread_id = %s AND w.checkpoint_ns = '' AND w.task_path LIKE '~\\_\\_pregel\\_pull, %%'
GROUP BY w.checkpoint_id, w.task_path, cp.checkpoint
ORDER BY w.checkpoint_id, w.task_path
"""

_LLM_STEPS = """
SELECT node, ts, model, mode, decision,
       input_tokens + cache_creation_input_tokens + cache_read_input_tokens AS tokens_in,
       cache_read_input_tokens AS cache_read_tokens,
       output_tokens AS tokens_out, cost_usd_micros, latency_ms
FROM llm_call WHERE run_id = %s ORDER BY ts, call_id
"""

AUDIT_WRITES = """
SELECT type, blob FROM lg.checkpoint_writes
WHERE thread_id = %s AND checkpoint_ns = '' AND channel = 'audit'
ORDER BY checkpoint_id, task_path, idx
"""
WORKER_NODE_PREFIX = "ask_worker_"
MAX_ARGS = 2


def step_node(task_path: str) -> str | None:
    """The graph node of a checkpoint write (`~__pregel_pull, <node>`); None for start, end and subtasks."""
    node = str(task_path).removeprefix(PULL_PREFIX)
    return None if node in INTERNAL_NODES or "," in node else node


def _when(raw: Any) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def flat_args(raw: Any) -> dict[str, str | int | bool] | None:
    """At most `MAX_ARGS` argument values, scalars or short id lists, for the trace (no free text)."""
    if not isinstance(raw, dict):
        return None
    out: dict[str, str | int | bool] = {}
    for key, value in sorted(raw.items()):
        if len(out) >= MAX_ARGS or key.startswith("_") or key == "query":
            continue
        if isinstance(value, bool | int) or isinstance(value, str) and len(value) <= 64:
            out[key] = value
        elif isinstance(value, list) and value and all(isinstance(v, str) for v in value):
            out[key] = ", ".join(value[:3]) + ("…" if len(value) > 3 else "")
    return out or None


def audit_steps(rows: list[dict[str, Any]]) -> list[AgentRunStep]:
    """The team's lanes, tool calls and the answer check from the run's audit rows."""
    steps: list[AgentRunStep] = []
    for row in rows:
        kind = row.get("kind")
        if kind == "worker":
            steps.append(
                AgentRunStep(
                    seq=0,
                    kind="worker",
                    node=f"{WORKER_NODE_PREFIX}{row['worker']}",
                    at=_when(row.get("at")),
                    worker=str(row["worker"]),
                    status="ok" if row.get("path") in ("llm", "not_in_documents") else "error",
                    decision="fallback" if row.get("path") == "code" else None,
                    latency_ms=row.get("ms"),
                )
            )
        elif kind == "tool_call" and row.get("worker"):
            steps.append(
                AgentRunStep(
                    seq=0,
                    kind="tool_call",
                    node=f"{WORKER_NODE_PREFIX}{row['worker']}",
                    at=_when(row.get("at")),
                    worker=str(row["worker"]),
                    tool=str(row["tool"]),
                    status=str(row.get("status") or "ok"),
                    args=flat_args(row.get("args")),
                    latency_ms=row.get("ms"),
                )
            )
        elif kind == "verify":
            steps.append(
                AgentRunStep(
                    seq=0,
                    kind="graph_step",
                    node="verify",
                    at=_when(row.get("at")),
                    decision=str(row.get("decision") or "pass"),
                )
            )
    return steps


def decode_audit(kind: str, blob: bytes) -> list[dict[str, Any]]:
    """One `audit` channel write of the LangGraph checkpointer (a list of audit rows)."""
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    value = JsonPlusSerializer().loads_typed((kind, bytes(blob)))
    return [r for r in value or [] if isinstance(r, dict)]


async def _audit_rows(conn: AsyncConnection[Any], thread: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in await _rows(conn, AUDIT_WRITES, (thread,)):
        out += decode_audit(w["type"], w["blob"])
    return out


def sees_all(function: ApprovalFunction) -> bool:
    return function in ALL_RUNS_FUNCTIONS


def clamp_limit(limit: int | None) -> int:
    return DEFAULT_LIMIT if limit is None else max(1, min(MAX_LIMIT, limit))


def _trace_url(trace_id: str | None) -> str | None:
    base = os.environ.get(MLFLOW_UI_ENV, "").rstrip("/")
    return f"{base}/#/traces/{trace_id}" if base and trace_id else None


def _summary(r: dict[str, Any]) -> AgentRunSummary:
    started: datetime = r["started_at"]
    ended: datetime | None = r["ended_at"]
    return AgentRunSummary.model_validate(
        {
            **{k: r[k] for k in ("run_id", "thread_id", "graph", "graph_version", "user_id", "run_mode")},
            **{
                k: r[k] for k in ("status", "started_at", "ended_at", "tainted", "classification", "trace_id")
            },
            "duration_ms": None if ended is None else int((ended - started).total_seconds() * 1000),
            "llm_calls": int(r["llm_calls"]),
            "billed_calls": int(r["billed_calls"]),
            "tokens_in": int(r["tokens_in"]),
            "tokens_out": int(r["tokens_out"]),
            "cost_usd_micros": int(r["cost_usd_micros"]),
            "nodes": list(r["nodes"]),
            "models": sorted(r["models"]),
            "trace_url": _trace_url(r["trace_id"]),
        }
    )


async def _rows(conn: AsyncConnection[Any], sql: str, args: Any) -> list[dict[str, Any]]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, args)
        return list(await cur.fetchall())


async def runs(
    conn: AsyncConnection[Any],
    *,
    user_id: str | None,
    graph: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    run_id: str | None = None,
) -> list[AgentRunSummary]:
    """`user_id` None lists every user's runs."""
    args = {
        "user_id": user_id,
        "graph": graph,
        "status": status,
        "limit": clamp_limit(limit),
        "run_id": run_id,
    }
    return [_summary(r) for r in await _rows(conn, _RUNS, args)]


async def run_detail(
    conn: AsyncConnection[Any], run_id: str, *, user_id: str | None
) -> AgentRunDetail | None:
    found = await runs(conn, user_id=user_id, run_id=run_id, limit=1)
    if not found:
        return None
    run = found[0]
    thread = f"{run.thread_id}:{run.run_id}"
    graph_rows = await _rows(conn, GRAPH_STEPS, (thread,))
    llm_rows = await _rows(conn, _LLM_STEPS, (run_id,))
    team_rows = await _audit_rows(conn, thread) if run.graph == "copilot" else []
    steps: list[tuple[datetime | None, int, AgentRunStep]] = []
    for g in graph_rows:
        node = step_node(g["task_path"])
        if node is None:
            continue
        steps.append((g["at"], 0, AgentRunStep(seq=0, kind="graph_step", node=node, at=g["at"])))
    for c in llm_rows:
        step = AgentRunStep(
            seq=0,
            kind="llm_call",
            node=c["node"],
            at=c["ts"],
            model=c["model"],
            mode=c["mode"],
            decision=c["decision"],
            tokens_in=int(c["tokens_in"]),
            tokens_out=int(c["tokens_out"]),
            cost_usd_micros=int(c["cost_usd_micros"]),
            latency_ms=c["latency_ms"],
            cache_read_tokens=int(c["cache_read_tokens"] or 0),
            worker=str(c["node"]).removeprefix(WORKER_NODE_PREFIX)
            if str(c["node"]).startswith(WORKER_NODE_PREFIX)
            else None,
        )
        steps.append((c["ts"], 1, step))
    for t in audit_steps(team_rows):
        steps.append((t.at, 2, t))
    ordered = sorted(steps, key=lambda s: (s[0] is None, s[0] or run.started_at, s[1]))
    return AgentRunDetail(
        run=run, steps=[s.model_copy(update={"seq": n}) for n, (_, _, s) in enumerate(ordered, start=1)]
    )
