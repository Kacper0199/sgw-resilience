"""After-action drafts: runs of the `after_action` graph read back like sitrep drafts.

The graph ends with `report` in its run state: the verified summary (`narrative.rendered`, LLM or the
M2 template), the code-formatted after-action Markdown and the SC 103-314 draft; it never files anything.
Drafts are read from K1 `agent_run` and the LangGraph checkpoint of each run (`<thread_id>:<run_id>`).
Starting a draft appends `after_action_drafted` to the audit chain. Drafts are C2."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from sgw.approval import audit
from sgw.contracts.api_models import AfterActionDraft
from sgw.contracts.vocab import ApprovalFunction, Classification

GRAPH = "after_action"
DRAFTED_KIND = "after_action_drafted"
DRAFTER_FUNCTIONS = frozenset({ApprovalFunction.COMMAND, ApprovalFunction.AUDIT})
DRAFTER_ROLES = frozenset({"auditor"})
ALL_DRAFT_FUNCTIONS = frozenset(
    {ApprovalFunction.COMMAND, ApprovalFunction.EXECUTIVE, ApprovalFunction.PLANNING, ApprovalFunction.AUDIT}
)
LIMIT = 10
STATUS = {"running": "running", "paused": "running", "error": "error", "cancelled": "error"}

StateReader = Callable[[str], Awaitable[dict[str, Any]]]

_RUNS = """
SELECT run_id, thread_id, user_id, status, started_at FROM agent_run
WHERE graph = 'after_action' AND (%(user_id)s::text IS NULL OR user_id = %(user_id)s)
ORDER BY started_at DESC, run_id LIMIT %(limit)s
"""


def may_draft(function: ApprovalFunction, roles: frozenset[str] | set[str] | tuple[str, ...]) -> bool:
    return function in DRAFTER_FUNCTIONS or bool(DRAFTER_ROLES.intersection(roles))


def sees_all(function: ApprovalFunction) -> bool:
    return function in ALL_DRAFT_FUNCTIONS


def runs(conn: psycopg.Connection[Any], *, user_id: str | None) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        return list(cur.execute(_RUNS, {"user_id": user_id, "limit": LIMIT}).fetchall())


def _as_of(report: dict[str, Any]) -> datetime | None:
    raw = str(dict(report.get("review") or {}).get("as_of") or "")
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC) if raw else None


def draft(run: dict[str, Any], values: dict[str, Any]) -> AfterActionDraft:
    report = dict(values.get("report") or {})
    narrative = dict(values.get("narrative") or {})
    markdown = report.get("after_action_markdown")
    ready = isinstance(markdown, str) and bool(markdown)
    status = STATUS.get(str(run["status"]), "draft" if ready else "blocked")
    return AfterActionDraft(
        run_id=run["run_id"],
        thread_id=run["thread_id"],
        drafted_by=run["user_id"],
        started_at=run["started_at"],
        as_of_utc=_as_of(report) if ready else None,
        status=status,  # type: ignore[arg-type]
        path=narrative.get("path") if ready else None,
        summary=narrative.get("rendered") if ready else None,
        markdown=markdown if ready else None,
        usable=report.get("usable") if ready else None,
        classification=Classification.C2,
    )


async def drafts(
    conn: psycopg.Connection[Any], read_state: StateReader, *, user_id: str | None
) -> list[AfterActionDraft]:
    out = []
    for r in runs(conn, user_id=user_id):
        values = await read_state(f"{r['thread_id']}:{r['run_id']}") if r["status"] == "done" else {}
        out.append(draft(r, values))
    return out


def record_drafted(
    conn: psycopg.Connection[Any], *, run_id: str, thread_id: str, actor_id: str, at: datetime
) -> int:
    with conn.transaction():
        record = audit.append(
            conn,
            kind=DRAFTED_KIND,
            actor_type="user",
            actor_id=actor_id,
            subject=run_id,
            payload={"run_id": run_id, "thread_id": thread_id, "graph": GRAPH, "as_of_utc": at.isoformat()},
            occurred_at=at,
        )
    return record.seq
