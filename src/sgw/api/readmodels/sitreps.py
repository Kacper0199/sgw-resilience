"""Sitrep drafts and their promotion (W7: T1 draft -> promoted by a person in the command function).

The `sitrep` graph ends with a verified draft in its run state (`report`: tier, path, rendered text,
slots shown) and never promotes. Drafts are read from finished `sitrep` runs in K1 `agent_run` and the
LangGraph checkpoint of each run (`<thread_id>:<run_id>`); promotion is one `sitrep_promoted` record in the
audit chain (the run id as subject, the text's SHA-256 in the payload). Nothing is stored twice and the draft
text is never edited. Drafts are C2 (the graph emits them as C2 artifacts)."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from sgw.api.audit_log import AUDIT_LOCK_KEY
from sgw.approval import audit
from sgw.contracts.api_models import SitrepDraft
from sgw.contracts.vocab import ApprovalFunction, Classification, Tier

PROMOTED_KIND = "sitrep_promoted"
ALL_DRAFT_FUNCTIONS = frozenset(
    {ApprovalFunction.COMMAND, ApprovalFunction.EXECUTIVE, ApprovalFunction.PLANNING}
)
PROMOTER_FUNCTIONS = frozenset({ApprovalFunction.COMMAND})
LIMIT = 20

StateReader = Callable[[str], Awaitable[dict[str, Any]]]

_RUNS = """
SELECT run_id, thread_id, user_id, started_at FROM agent_run
WHERE graph = 'sitrep' AND status = 'done' AND (%(user_id)s::text IS NULL OR user_id = %(user_id)s)
  AND (%(run_id)s::text IS NULL OR run_id = %(run_id)s)
ORDER BY started_at DESC, run_id LIMIT %(limit)s
"""


def sees_all(function: ApprovalFunction) -> bool:
    return function in ALL_DRAFT_FUNCTIONS


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def promotions(conn: psycopg.Connection[Any], run_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not run_ids:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT DISTINCT ON (subject) subject, seq, actor_id, occurred_at FROM audit_event"
            " WHERE stream = %s AND kind = %s AND subject = ANY(%s) ORDER BY subject, seq",
            (audit.STREAM, PROMOTED_KIND, run_ids),
        ).fetchall()
    return {str(r["subject"]): dict(r) for r in rows}


def runs(
    conn: psycopg.Connection[Any], *, user_id: str | None, run_id: str | None = None
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        return list(cur.execute(_RUNS, {"user_id": user_id, "run_id": run_id, "limit": LIMIT}).fetchall())


def _as_of(report: dict[str, Any]) -> datetime | None:
    raw = str(report.get("as_of_utc") or "")
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC) if raw else None


def draft(run: dict[str, Any], values: dict[str, Any], promoted: dict[str, Any] | None) -> SitrepDraft:
    report = dict(values.get("report") or {})
    text = report.get("rendered")
    ready = report.get("kind") == "sitrep_draft" and isinstance(text, str) and bool(text)
    tier = report.get("tier")
    status = "promoted" if promoted else ("draft" if ready else "blocked")
    return SitrepDraft(
        run_id=run["run_id"],
        thread_id=run["thread_id"],
        drafted_by=run["user_id"],
        started_at=run["started_at"],
        as_of_utc=_as_of(report),
        tier=Tier(tier) if tier else None,
        path=report.get("path"),
        text=text if ready else None,
        slots={str(k): str(v) for k, v in (report.get("slots") or {}).items()},
        tainted=bool(report.get("tainted") or values.get("tainted")),
        status=status,  # type: ignore[arg-type]
        promoted_by=promoted["actor_id"] if promoted else None,
        promoted_at=promoted["occurred_at"] if promoted else None,
        audit_seq=int(promoted["seq"]) if promoted else None,
        classification=Classification.C2,
    )


async def drafts(
    conn: psycopg.Connection[Any], read_state: StateReader, *, user_id: str | None, run_id: str | None = None
) -> list[SitrepDraft]:
    rows = runs(conn, user_id=user_id, run_id=run_id)
    done = promotions(conn, [r["run_id"] for r in rows])
    return [
        draft(r, await read_state(f"{r['thread_id']}:{r['run_id']}"), done.get(r["run_id"])) for r in rows
    ]


def promote(
    conn: psycopg.Connection[Any], item: SitrepDraft, *, actor_id: str, at: datetime, note: str | None
) -> int | None:
    """Appends `sitrep_promoted` unless the run was promoted meanwhile; returns the audit seq or None."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_LOCK_KEY,))
        if promotions(conn, [item.run_id]):
            return None
        record = audit.append(
            conn,
            kind=PROMOTED_KIND,
            actor_type="user",
            actor_id=actor_id,
            subject=item.run_id,
            payload={
                "run_id": item.run_id,
                "thread_id": item.thread_id,
                "drafted_by": item.drafted_by,
                "as_of_utc": item.as_of_utc.isoformat() if item.as_of_utc else None,
                "tier": item.tier.value if item.tier else None,
                "path": item.path,
                "text_sha256": text_sha256(item.text or ""),
                "tainted": item.tainted,
                "note": note,
            },
            occurred_at=at,
        )
    return record.seq
