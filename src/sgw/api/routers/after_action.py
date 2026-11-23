"""K3 after-action routes: `GET /api/after-action` (any signed-in reader; C0/C1) and
`POST /api/audit/tamper-demo` (CSRF-checked session; one run per session per window, like the verifier).
The tamper demo alters only an in-memory copy of the chain; the real chain is read, never written."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Request, Response

from sgw.api.deps import CurrentUser, SessionWrite, State
from sgw.api.errors import NotFound, TooManyRequests
from sgw.api.readmodels import after_action as aa
from sgw.api.readmodels.http import cached_json, read_span
from sgw.approval import audit
from sgw.approval.breakglass_deps import audit_paths
from sgw.approval.deps import db_conn
from sgw.approval.signer import AuditPaths, Keyring
from sgw.contracts.api_models import AfterActionView, TamperDemoRequest, TamperDemoResult
from sgw.scenarios import packs
from sgw.scenarios import reads as pack_reads

router = APIRouter(tags=["governance"])

Conn = Annotated[psycopg.Connection[Any], Depends(db_conn)]
Paths = Annotated[AuditPaths, Depends(audit_paths)]
TAMPER_WINDOW_S = 10.0
VIEW_CACHE_S = 5.0
CacheKey = tuple[datetime, int, str]


@dataclass
class _ViewCache:
    lock: threading.Lock = field(default_factory=threading.Lock)
    entries: dict[CacheKey, tuple[float, AfterActionView]] = field(default_factory=dict)


def _view_cache(request: Request) -> _ViewCache:
    cache = getattr(request.app.state, "after_action_cache", None)
    if not isinstance(cache, _ViewCache):
        cache = _ViewCache()
        request.app.state.after_action_cache = cache
    return cache


def _head(conn: psycopg.Connection[Any]) -> tuple[int, str]:
    row = conn.execute(
        "SELECT seq, hash FROM audit_event WHERE stream = %s ORDER BY seq DESC LIMIT 1", (audit.STREAM,)
    ).fetchone()
    return (int(row[0]), str(row[1])) if row else (0, "")


@dataclass
class _Window:
    lock: threading.Lock = field(default_factory=threading.Lock)
    by_session: dict[str, float] = field(default_factory=dict)


def _window(request: Request) -> _Window:
    state = getattr(request.app.state, "tamper_demo_window", None)
    if not isinstance(state, _Window):
        state = _Window()
        request.app.state.tamper_demo_window = state
    return state


@router.get("/api/after-action", response_model=AfterActionView)
def get_after_action(request: Request, user: CurrentUser, state: State, conn: Conn, paths: Paths) -> Response:
    """The O(n) chain verify runs once per (scenario time, chain head) within the cache window."""
    ttl = float(getattr(request.app.state, "after_action_cache_s", VIEW_CACHE_S))
    cache = _view_cache(request)
    with read_span("after_action", user):
        at = state.clock.now()
        key: CacheKey = (at, *_head(conn))
        now = time.monotonic()
        with cache.lock:
            hit = cache.entries.get(key)
        if hit is not None and now - hit[0] < ttl:
            doc = hit[1]
        else:
            doc = aa.view(conn, at, Keyring.load(paths.keyring), audit.AnchorStore(paths.anchors))
            pack = packs.get(state.clock.view.state.scenario)
            if pack is not None:
                doc = pack_reads.after_action(pack, doc, pack_reads.load_seq(conn, pack.scenario))
            with cache.lock:
                cache.entries = {k: v for k, v in cache.entries.items() if now - v[0] < ttl}
                cache.entries[key] = (now, doc)
    return cached_json(request, doc, max_age_s=0)


@router.post("/api/audit/tamper-demo", response_model=TamperDemoResult)
def tamper_demo(
    body: TamperDemoRequest, request: Request, user: SessionWrite, conn: Conn, paths: Paths
) -> TamperDemoResult:
    window = float(getattr(request.app.state, "tamper_demo_window_s", TAMPER_WINDOW_S))
    state = _window(request)
    now = time.monotonic()
    with state.lock:
        last = state.by_session.get(user.user_id)
        if last is not None and now - last < window:
            retry = max(1, int(window - (now - last)) + 1)
            raise TooManyRequests(f"run the demo again in {retry} s", headers={"Retry-After": str(retry)})
        state.by_session[user.user_id] = now
    with read_span("audit.tamper_demo", user):
        result = aa.tamper_demo(conn, body.seq, Keyring.load(paths.keyring), audit.AnchorStore(paths.anchors))
    if result is None:
        raise NotFound("no audit record with that sequence", code="AUDIT_SEQ_NOT_FOUND")
    return result
