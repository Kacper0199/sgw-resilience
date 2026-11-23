"""FastAPI dependencies for the proposals router, bound to WP-08's API core when it is present.

With `sgw.api.deps` importable: reads need its `current_user` (session cookie, 401) and writes its
`writer` (session + CSRF + not read-only, 403); the scenario clock is `app.state.sgw.clock.now` and the
database URL `app.state.sgw.settings.database_url`. Without it (this package alone, or a bare test app):
`request.state.user_id`, SGW_DATABASE_URL and the wall clock. The approval service talks to psycopg
synchronously, so it keeps its own small pool next to WP-08's async pool. `app.state` may override:
`approval_db_pool` (psycopg_pool.ConnectionPool), `approval_service`, `publish_events` (callable taking K2
event models).
"""

from __future__ import annotations

import importlib
import importlib.util
import os
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Annotated, Any

import psycopg
from fastapi import Depends, HTTPException, Request
from psycopg import pq
from psycopg_pool import ConnectionPool

from sgw.approval.ledger import default_sink
from sgw.approval.policy import OpaPolicy
from sgw.approval.service import ApprovalService, wall_clock
from sgw.common.app_scope import per_app

DATABASE_ENV = "SGW_DATABASE_URL"
OPA_ENV = "SGW_OPA_URL"


def current_user_id(request: Request) -> str:
    """Fallback identity when WP-08's session layer is not installed."""
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="sign in first")
    return user_id


def _api_deps() -> Any:
    try:
        found = importlib.util.find_spec("sgw.api.deps")
    except ModuleNotFoundError:
        found = None
    return importlib.import_module("sgw.api.deps") if found else None


_API = _api_deps()
SESSION_READER: Callable[..., Any] = _API.current_user if _API else current_user_id
SESSION_WRITER: Callable[..., Any] = _API.writer if _API else current_user_id


def _user_id(user: Any) -> str:
    return user if isinstance(user, str) else str(user.user_id)


def reader_id(user: Annotated[Any, Depends(SESSION_READER)]) -> str:
    return _user_id(user)


def writer_id(user: Annotated[Any, Depends(SESSION_WRITER)]) -> str:
    return _user_id(user)


def _api_state(request: Request) -> Any:
    return getattr(request.app.state, "sgw", None)


def _close_pool(pool: ConnectionPool[Any]) -> None:
    pool.close()


def refresh_owned_pool(app: Any) -> None:
    """After the database under the API was replaced (demo goto, scenario load): drop the dead connections and
    wait until the pool serves again, so the first request after the load does not time out."""
    pool = getattr(app.state, "approval_owned_pool", None)
    if pool is None:
        return
    pool.check()
    with pool.connection(timeout=10):
        pass


def _pool(request: Request) -> ConnectionPool[Any]:
    """The injected `app.state.approval_db_pool`, else one pool per app on that app's database, closed with
    the app's lifespan (never shared across apps or databases)."""
    pool = getattr(request.app.state, "approval_db_pool", None)
    if pool is not None:
        return pool  # type: ignore[no-any-return]
    api = _api_state(request)
    dsn = api.settings.database_url if api is not None else os.environ.get(DATABASE_ENV)
    if not dsn:
        raise HTTPException(status_code=503, detail="no database configured")
    return per_app(
        request.app,
        "approval_owned_pool",
        lambda: ConnectionPool(
            dsn,
            min_size=1,
            max_size=5,
            kwargs={"autocommit": True},
            timeout=5.0,
            open=True,
            check=ConnectionPool.check_connection,
        ),
        _close_pool,
    )


def db_conn(request: Request) -> Iterator[psycopg.Connection[Any]]:
    with _pool(request).connection() as conn:
        switched = False
        if not conn.autocommit and conn.info.transaction_status == pq.TransactionStatus.IDLE:
            conn.autocommit = True
            switched = True
        try:
            yield conn
        finally:
            if switched and conn.info.transaction_status == pq.TransactionStatus.IDLE:
                conn.autocommit = False


def _scenario_clock(app: Any) -> Callable[[], datetime]:
    api = getattr(app.state, "sgw", None)
    clock = getattr(api, "clock", None) if api is not None else None
    return clock.now if clock is not None else wall_clock


def app_approval_service(app: Any) -> ApprovalService:
    """The app's approval service (`app.state.approval_service` when set), shared by requests and the
    API's background scenario jobs."""
    service = getattr(app.state, "approval_service", None)
    if service is not None:
        return service  # type: ignore[no-any-return]

    def build() -> ApprovalService:
        policy = OpaPolicy(os.environ.get(OPA_ENV, "http://127.0.0.1:8181"))
        return ApprovalService(policy, scenario_clock=_scenario_clock(app), ledger=default_sink())

    return per_app(app, "approval_owned_service", build)


def approval_service(request: Request) -> ApprovalService:
    return app_approval_service(request.app)


def publish(request: Request, events: Any) -> None:
    sink = getattr(request.app.state, "publish_events", None)
    if sink is not None and events:
        sink(list(events))
