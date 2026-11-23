"""Ask (copilot) routes: `listMessages`, `listThreadRuns` and `putRunFeedback` (the `copilot` graph is
registered in `runs.GRAPHS`).

A copilot turn is an ordinary run: `POST /api/threads/{id}/runs` with `graph: "copilot"` and `input:
{"question": ..., "as_of": ...}`; its frames stream on `/api/threads/{id}/events`. `listMessages` returns
the thread's user and assistant messages from the `message` artifacts of its runs: the frames of runs this
API process still holds, otherwise the persisted run rows and checkpoints, so history survives a restart.
Assistant messages carry the answer path, the reason when it is not checked model text, the checked
citations as structured rows (document titles from the corpus `document` table) and the tool calls.
`listThreadRuns` is the same history per run for the Runs tab, with graph steps from the checkpoint writes
and the owner's feedback. At most the owner's last 50 runs of the thread are read. Only the thread's owner
sees them (others get 404). Search for the copilot uses the API's database (`SGW_DATABASE_URL`)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request, Response
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from sgw.agent.copilot import graph as copilot_graph
from sgw.agent.nodes.run_store import k1_status
from sgw.api.deps import CurrentUser, DbConn, Writer
from sgw.api.errors import NotFound
from sgw.api.readmodels import agent_runs
from sgw.api.readmodels.http import read_span
from sgw.api.routers import runs
from sgw.contracts.api_models import (
    Message,
    MessageCitation,
    MessageLink,
    MessagePhoto,
    MessageReference,
    MessageToolCall,
    RunFeedback,
    ThreadRun,
    ThreadRunStep,
)
from sgw.contracts.wire import WireEvent

router = APIRouter(tags=["agent"])
MAX_RUNS = 50
TITLES = "SELECT doc_id, title FROM document WHERE doc_id = ANY(%s)"
FEEDBACK = "SELECT run_id, rating FROM agent_run_feedback WHERE run_id = ANY(%s) AND user_id = %s"
SAVE_FEEDBACK = """
INSERT INTO agent_run_feedback (run_id, user_id, rating, note) VALUES (%s, %s, %s, %s)
ON CONFLICT (run_id) DO UPDATE SET rating = EXCLUDED.rating, note = EXCLUDED.note, updated_at = now()
"""


def _citations(rows: list[dict[str, Any]], titles: dict[str, str]) -> list[MessageCitation]:
    return [
        MessageCitation(
            **{k: r[k] for k in copilot_graph.CITATION_KEYS if k in r}, title=titles.get(str(r.get("doc_id")))
        )
        for r in rows
    ]


def _tools(calls: list[dict[str, Any]]) -> list[MessageToolCall]:
    return [
        MessageToolCall(tool=str(c["tool"]), args=dict(c.get("args") or {}), status=str(c.get("status")))
        for c in calls
    ]


def _references(rows: Any) -> list[MessageReference]:
    return [MessageReference.model_validate(r) for r in rows or []]


def _extras(source: dict[str, Any]) -> dict[str, Any]:
    """Deep links, inline photos, suggested questions and the refusal kind, when the run carried them."""
    return {
        "links": [MessageLink.model_validate(r) for r in source.get("links") or []],
        "photos": [MessagePhoto.model_validate(r) for r in source.get("photos") or []],
        "suggestions": [str(q) for q in source.get("suggestions") or []],
        "did_you_mean": [str(q) for q in source.get("did_you_mean") or []],
        "refusal": source.get("refusal"),
    }


def _frame_tools(frames: list[Any]) -> list[dict[str, Any]]:
    calls: dict[int, dict[str, Any]] = {}
    for f in frames:
        p = f.payload or {}
        if f.type is WireEvent.TOOL_START:
            n = int(p.get("call", len(calls)))
            calls[n] = {"tool": p["tool"], "args": p.get("args"), "status": "running"}
        elif f.type is WireEvent.TOOL_END and int(p.get("call", -1)) in calls:
            calls[int(p["call"])]["status"] = p.get("status", "ok")
    return [calls[k] for k in sorted(calls)]


def _messages_from_frames(run_id: str, frames: list[Any], titles: dict[str, str]) -> list[Message]:
    out: list[Message] = []
    for f in frames:
        payload = f.payload or {}
        if f.type is not WireEvent.ARTIFACT or payload.get("kind") != "message":
            continue
        assistant = payload["role"] == "assistant"
        cited = list(payload.get("citation_details") or []) if assistant else []
        out.append(
            Message(
                message_id=f"{run_id}.{f.seq}",
                role=payload["role"],
                text=str(payload["text"]),
                created_at=f.ts,
                evidence_ids=list(payload.get("evidence_ids") or []),
                run_id=run_id,
                path=payload.get("path") if assistant else None,
                reason=copilot_graph.answer_reason(payload) if assistant else None,
                citations=_citations(cited, titles),
                tool_calls=_tools(_frame_tools(frames)) if assistant else [],
                references=_references(payload.get("references")) if assistant else [],
                **(_extras(payload) if assistant else {}),
            )
        )
    return out


def _messages_from_state(
    run_id: str, values: dict[str, Any], started: datetime, ended: datetime | None, titles: dict[str, str]
) -> list[Message]:
    out: list[Message] = []
    if values.get("question"):
        out.append(
            Message(
                message_id=f"{run_id}.q",
                role="user",
                text=values["question"],
                created_at=started,
                run_id=run_id,
            )
        )
    answer = values.get("answer") or {}
    if answer.get("rendered"):
        out.append(
            Message(
                message_id=f"{run_id}.a",
                role="assistant",
                text=answer["rendered"],
                created_at=ended or started,
                evidence_ids=list(answer.get("evidence_ids") or []),
                run_id=run_id,
                path=answer.get("path"),
                reason=copilot_graph.answer_reason(answer),
                citations=_citations(list(answer.get("citations") or []), titles),
                tool_calls=_tools(list(answer.get("tool_calls") or [])),
                references=_references(answer.get("references")),
                **_extras(answer),
            )
        )
    return out


async def _rows(conn: AsyncConnection[Any], sql: str, args: Any) -> list[dict[str, Any]]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, args)
        return list(await cur.fetchall())


def _doc_ids(values: dict[str, Any]) -> set[str]:
    return {str(c.get("doc_id")) for c in (values.get("answer") or {}).get("citations") or []}


def _frame_doc_ids(frames: list[Any]) -> set[str]:
    return {
        str(c.get("doc_id"))
        for f in frames
        if f.type is WireEvent.ARTIFACT
        for c in (f.payload or {}).get("citation_details") or []
    }


async def _titles(request: Request, doc_ids: set[str]) -> dict[str, str]:
    """Corpus titles of the cited documents; a connection is taken only when something was cited."""
    api = getattr(request.app.state, "sgw", None)
    if not doc_ids or api is None:
        return {}
    async with api.pool.connection() as conn:
        return {r["doc_id"]: r["title"] for r in await _rows(conn, TITLES, (sorted(doc_ids),))}


async def _copilot_values(runtime: runs.AgentRuntime, thread_id: str, run_id: str) -> dict[str, Any]:
    graph = copilot_graph.build(runtime.checkpointer)
    snap = await graph.aget_state({"configurable": {"thread_id": f"{thread_id}:{run_id}"}})
    return dict(snap.values or {})


HISTORY_RUNS = 3


async def conversation(runtime: runs.AgentRuntime, thread_id: str, user_id: str) -> list[dict[str, Any]]:
    """The owner's last `HISTORY_RUNS` finished copilot turns of the thread, oldest first, for follow-ups
    ("or the link", "and for PS-23?"): question, answer text and the gate's topics. Read by the server from
    its own run store, so a client cannot write the history the copilot sees."""
    timed = await runtime.store.thread_runs(thread_id, user_id, copilot_graph.GRAPH_ID, HISTORY_RUNS + 1)
    out: list[dict[str, Any]] = []
    for t in sorted(timed, key=lambda t: (t.started_at, t.row.run_id))[-HISTORY_RUNS:]:
        live = runtime.live.get(t.row.run_id)
        values = await (live.state() if live else _copilot_values(runtime, thread_id, t.row.run_id))
        answer = values.get("answer") or {}
        gate = values.get("gate") or {}
        if not values.get("question") or not answer.get("rendered"):
            continue
        out.append(
            {
                "question": values["question"],
                "answer": answer["rendered"],
                "topics": list(gate.get("topics") or []),
                "kind": gate.get("kind") or (values.get("route") or {}).get("intent"),
            }
        )
    return out


@router.get("/api/threads/{thread_id}/messages", operation_id="listMessages", response_model=list[Message])
async def list_messages(
    thread_id: str, user: CurrentUser, runtime: runs.Runtime, request: Request
) -> list[Message]:
    """The owner's last `MAX_RUNS` copilot runs in the thread, oldest first: live frames when this process
    holds the run, else the persisted run row (its start and end times) and the checkpointed state."""
    await runs._owned_thread(runtime, thread_id, user.user_id)
    timed = await runtime.store.thread_runs(thread_id, user.user_id, copilot_graph.GRAPH_ID, MAX_RUNS)
    found: list[tuple[Any, Any, dict[str, Any] | None]] = []
    doc_ids: set[str] = set()
    for t in timed:
        task = runtime.live.get(t.row.run_id)
        if task is not None:
            found.append((t, task, None))
            doc_ids |= _frame_doc_ids(task.frames)
            continue
        values = await _copilot_values(runtime, thread_id, t.row.run_id)
        found.append((t, None, values))
        doc_ids |= _doc_ids(values)
    titles = await _titles(request, doc_ids)
    messages: list[Message] = []
    for t, live, state in found:
        if live is not None:
            messages += _messages_from_frames(live.run_id, live.frames, titles)
        else:
            messages += _messages_from_state(t.row.run_id, state or {}, t.started_at, t.ended_at, titles)
    return messages


@router.get(
    "/api/threads/{thread_id}/runs",
    operation_id="listThreadRuns",
    response_model=list[ThreadRun],
)
async def list_thread_runs(
    thread_id: str, user: CurrentUser, runtime: runs.Runtime, conn: DbConn
) -> list[ThreadRun]:
    """Every graph's runs of the owner in this thread, newest first (at most `MAX_RUNS`)."""
    await runs._owned_thread(runtime, thread_id, user.user_id)
    with read_span("threads.runs", user):
        timed = [
            t
            for graph in runs.GRAPHS
            for t in await runtime.store.thread_runs(thread_id, user.user_id, graph, MAX_RUNS)
        ]
        timed.sort(key=lambda t: (t.started_at, t.row.run_id), reverse=True)
        timed = timed[:MAX_RUNS]
        ratings = {
            r["run_id"]: r["rating"]
            for r in await _rows(conn, FEEDBACK, ([t.row.run_id for t in timed], user.user_id))
        }
        out: list[ThreadRun] = []
        for t in timed:
            values: dict[str, Any] = {}
            if t.row.graph == copilot_graph.GRAPH_ID:
                live = runtime.live.get(t.row.run_id)
                values = await (live.state() if live else _copilot_values(runtime, thread_id, t.row.run_id))
            answer = values.get("answer") or {}
            status = k1_status(t.row.status)
            steps = await _rows(conn, agent_runs.GRAPH_STEPS, (f"{thread_id}:{t.row.run_id}",))
            out.append(
                ThreadRun(
                    run_id=t.row.run_id,
                    graph=t.row.graph,
                    status=status,  # type: ignore[arg-type]
                    started_at=t.started_at,
                    ended_at=t.ended_at,
                    question=values.get("question"),
                    path=answer.get("path"),
                    reason=copilot_graph.answer_reason(answer) if answer else None,
                    tool_calls=_tools(list(answer.get("tool_calls") or [])),
                    steps=[
                        ThreadRunStep(node=node, status="done", at=s["at"])
                        for s in steps
                        if (node := agent_runs.step_node(s["task_path"])) is not None
                    ],
                    feedback=ratings.get(t.row.run_id),
                )
            )
    return out


@router.post(
    "/api/threads/{thread_id}/runs/{run_id}/feedback",
    operation_id="putRunFeedback",
    status_code=204,
)
async def put_run_feedback(
    thread_id: str, run_id: str, body: RunFeedback, user: Writer, runtime: runs.Runtime, conn: DbConn
) -> Response:
    """The run owner's rating; stored with the run (`agent_run_feedback`), a new rating replaces the old."""
    await runs._owned_thread(runtime, thread_id, user.user_id)
    row = await runtime.store.run(run_id)
    if row is None or row.thread_id != thread_id or row.user_id != user.user_id:
        raise NotFound("run not found", code="RUN_NOT_FOUND")
    with read_span("threads.feedback", user):
        await conn.execute(SAVE_FEEDBACK, (run_id, user.user_id, body.rating, body.note))
    return Response(status_code=204)
