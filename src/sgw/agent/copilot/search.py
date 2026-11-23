"""Retrieval behind the copilot's `search_procedures` tool.

`DbSearch` runs the WP-18 hybrid search in Postgres (in force at the injected `as_of`, readable classes
from the injected ceiling). `RecordedSearch` serves results captured from `DbSearch`, keyed by query,
`top_k` and `as_of`, so copilot replay tests run without a database; a DB test checks the recording still
equals a live search (drift fails). Both return guarded hits: the input guard has already withheld
instruction lines."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import psycopg

from sgw.agent.rag.search import Hit
from sgw.agent.rag.tool import GuardedHit, guard_hit, search_procedures
from sgw.contracts.tools import InjectedContext, SearchProceduresArgs


class SearchUnavailable(Exception):
    pass


class SearchFn(Protocol):
    def __call__(self, args: SearchProceduresArgs, ctx: InjectedContext) -> list[GuardedHit]: ...


def key(args: SearchProceduresArgs, ctx: InjectedContext) -> str:
    return f"{ctx.as_of.isoformat()}|{args.top_k}|{' '.join(args.query.split()).lower()}"


def hit_to_json(h: Hit) -> dict[str, Any]:
    d = asdict(h)
    d["blocks"] = list(h.blocks)
    d["effective_from"] = h.effective_from.isoformat()
    d["expires_at"] = h.expires_at.isoformat() if h.expires_at else None
    return d


def hit_from_json(d: dict[str, Any]) -> Hit:
    return Hit(
        **{
            **d,
            "blocks": tuple(d["blocks"]),
            "effective_from": datetime.fromisoformat(d["effective_from"]),
            "expires_at": datetime.fromisoformat(d["expires_at"]) if d["expires_at"] else None,
        }
    )


class DbSearch:
    def __init__(self, connect: Callable[[], psycopg.Connection[Any]], embedder: Any = None) -> None:
        self.connect = connect
        self._embedder = embedder

    def embedder(self) -> Any:
        if self._embedder is None:
            from sgw.agent.rag.embed import default_embedder

            self._embedder = default_embedder()
        return self._embedder

    def __call__(self, args: SearchProceduresArgs, ctx: InjectedContext) -> list[GuardedHit]:
        try:
            with self.connect() as conn:
                _, hits = search_procedures(args, ctx, conn=conn, embedder=self.embedder())
        except psycopg.Error as exc:
            raise SearchUnavailable(type(exc).__name__) from exc
        return hits


class RecordingSearch:
    """Wraps a live search and keeps every result for `save` (used once to produce the recording)."""

    def __init__(self, inner: SearchFn) -> None:
        self.inner = inner
        self.seen: dict[str, list[dict[str, Any]]] = {}

    def __call__(self, args: SearchProceduresArgs, ctx: InjectedContext) -> list[GuardedHit]:
        hits = self.inner(args, ctx)
        self.seen[key(args, ctx)] = [hit_to_json(g.hit) for g in hits]
        return hits

    def save(self, path: Path, merge: bool = True) -> None:
        data: dict[str, Any] = {}
        if merge and path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
        data.update(self.seen)
        path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


class RecordedSearch:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, list[dict[str, Any]]] = (
            json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        )

    def __call__(self, args: SearchProceduresArgs, ctx: InjectedContext) -> list[GuardedHit]:
        rows = self.data.get(key(args, ctx))
        if rows is None:
            raise SearchUnavailable(f"no recorded search for {key(args, ctx)!r}")
        return [guard_hit(hit_from_json(r)) for r in rows]


REPO = Path(__file__).resolve().parents[4]
DEMO_SEARCH = REPO / "data" / "fixtures" / "copilot" / "search_recorded.json"


class ReplayFirstSearch:
    """The demo's searches as they were recorded, live search for any other query. The query embedding is
    computed by onnxruntime, whose floats differ slightly between the host that records and the API container,
    so passages with close dense ranks can swap places and a recorded answer would miss (R32: 3 of 34 searches
    after landfall, including the ETR revision analyst's)."""

    def __init__(self, recorded: RecordedSearch, live: SearchFn) -> None:
        self.recorded = recorded
        self.live = live

    def __call__(self, args: SearchProceduresArgs, ctx: InjectedContext) -> list[GuardedHit]:
        if key(args, ctx) in self.recorded.data:
            return self.recorded(args, ctx)
        return self.live(args, ctx)


def env_search() -> SearchFn | None:
    """Live search from `SGW_DATABASE_URL` (the API process), or None when no database is configured; in
    DEMO_MODE the recorded demo searches come first (`ReplayFirstSearch`)."""
    dsn = os.environ.get("SGW_DATABASE_URL")
    if not dsn:
        return None
    live = DbSearch(lambda: psycopg.connect(dsn, autocommit=True))
    if os.environ.get("DEMO_MODE", "").strip().lower() in ("1", "true", "yes") and DEMO_SEARCH.is_file():
        return ReplayFirstSearch(RecordedSearch(DEMO_SEARCH), live)
    return live
