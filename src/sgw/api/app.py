"""API application factory.

Routers are auto-discovered: every module in `sgw/api/routers/` (namespace package, no `__init__.py`) that
exposes `router: fastapi.APIRouter` is mounted, in module-name order. Routes declare their full contract path
(e.g. `/api/auth/login`); the served OpenAPI document is the K3 contract itself (`openapi_document()`), and a
contract test keeps the mounted routes a subset of it.

Run: `uv run sgw api serve` or `uvicorn sgw.api.app:create_app --factory`.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
import uuid
from collections.abc import AsyncIterator, Iterable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from opentelemetry import trace
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool
from starlette.routing import BaseRoute, Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sgw.api import clock_service, ledger, scenario_jobs
from sgw.api.clock import ClockState, ScenarioClock, SystemWallClock, TimeSource, scenario_def
from sgw.api.deps import ApiState
from sgw.api.errors import install_error_handlers
from sgw.api.ledger import ControlSnapshot
from sgw.api.metrics import ApiMetrics, MetricsMiddleware
from sgw.api.ratelimit import LoginLimiter, TokenBuckets
from sgw.api.settings import ApiSettings
from sgw.api.stream import LedgerBroadcaster
from sgw.common.app_scope import close_all
from sgw.common.telemetry import span_attributes
from sgw.contracts.api_models import openapi_document
from sgw.contracts.vocab import Classification, RunMode

log = logging.getLogger("sgw.api")


async def _warm_reads() -> None:
    """Live and demo stacks (scenario jobs on): run the deterministic ETR story simulation once in a thread,
    so the first `GET /api/after-action` does not pay for it (about 6 s)."""
    from sgw.reports import scorecard

    try:
        await asyncio.to_thread(scorecard.warm)
    except Exception:  # noqa: BLE001
        log.warning("warming the ETR story run failed; the first after-action read runs it", exc_info=True)


ROUTERS_DIR = Path(__file__).resolve().parent / "routers"
ROUTERS_PACKAGE = "sgw.api.routers"
OPENAPI_URL = "/api/openapi.json"
LEDGER_CHANNEL = ledger.NOTIFY_CHANNEL


class RouterConflictError(RuntimeError):
    pass


def discover_routers(directory: Path = ROUTERS_DIR) -> list[tuple[str, APIRouter]]:
    found: list[tuple[str, APIRouter]] = []
    for info in sorted(pkgutil.iter_modules([str(directory)]), key=lambda i: i.name):
        if info.name.startswith("_") or info.ispkg:
            continue
        module = importlib.import_module(f"{ROUTERS_PACKAGE}.{info.name}")
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            found.append((info.name, router))
    return found


def mount_routers(app: FastAPI, routers: list[tuple[str, APIRouter]]) -> None:
    owner: dict[tuple[str, str], str] = {}
    for name, router in routers:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in route.methods or ():
                key = (method, route.path)
                if key in owner:
                    raise RouterConflictError(
                        f"{method} {route.path} in {name} already defined by {owner[key]}"
                    )
                owner[key] = name
        app.include_router(router)


def _walk_routes(routes: Iterable[BaseRoute]) -> Iterator[Route]:
    for route in routes:
        nested = getattr(route, "original_router", None)
        if isinstance(nested, APIRouter):
            yield from _walk_routes(nested.routes)
        elif isinstance(route, Route):
            yield route


def app_routes(app: FastAPI) -> set[tuple[str, str]]:
    """(method, path) pairs the app serves; routers are mounted without prefixes, so paths are final."""
    return {
        (method, route.path)
        for route in _walk_routes(app.routes)
        for method in route.methods or ()
        if method != "HEAD"
    }


DEMO_HEADER = (b"x-sgw-demo-mode", b"synthetic data; demo identities")


class RequestContextMiddleware:
    """Request id (echoed as `X-Request-ID`), a K12 span per request, `no-store` on API responses, and the
    `X-SGW-Demo-Mode` banner header on every response while DEMO_MODE=1 (the UI shows the banner from it)."""

    def __init__(self, app: ASGIApp, demo_mode: bool = False) -> None:
        self.app = app
        self.demo_mode = demo_mode

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if 0 < len(incoming) <= 64 and incoming.isascii() else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        path: str = scope.get("path", "")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                extra = [(b"x-request-id", request_id.encode())]
                existing = {k.lower() for k, _ in message.get("headers", [])}
                if path.startswith("/api/") and b"cache-control" not in existing:
                    extra.append((b"cache-control", b"no-store"))
                if self.demo_mode:
                    extra.append(DEMO_HEADER)
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        tracer = trace.get_tracer("sgw")
        attrs = span_attributes(
            run_id=None, classification=Classification.C1, user_role="anonymous", run_mode=RunMode.REPLAY
        )
        with tracer.start_as_current_span(f"{scope.get('method', 'GET')} {path}", attributes=attrs):
            await self.app(scope, receive, send_wrapper)


class _PoolSource:
    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self.pool = pool

    async def head(self) -> int:
        async with self.pool.connection() as conn:
            return await ledger.head(conn)

    async def epoch(self) -> int:
        async with self.pool.connection() as conn:
            return await ledger.database_epoch(conn)

    async def fetch_after(self, after: int, upto: int, limit: int) -> list[ledger.LedgerRow]:
        async with self.pool.connection() as conn:
            return await ledger.fetch_after(conn, after, upto, limit)

    async def control(self) -> ControlSnapshot | None:
        async with self.pool.connection() as conn:
            return await ledger.read_control(conn)

    async def existing(self, seqs: list[int]) -> list[int]:
        async with self.pool.connection() as conn:
            return await ledger.existing(conn, seqs)


async def _listen(url: str, broadcaster: LedgerBroadcaster) -> None:
    """Wake the broadcaster on `NOTIFY sgw_ledger` when a writer sends it; polling covers the rest."""
    while True:
        try:
            async with await AsyncConnection.connect(url, autocommit=True) as conn:
                await conn.execute(f"LISTEN {LEDGER_CHANNEL}")
                async for _ in conn.notifies():
                    broadcaster.wake()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("ledger LISTEN connection lost; retrying in 5 s", exc_info=True)
            await asyncio.sleep(5)


def create_app(settings: ApiSettings | None = None, wall: TimeSource | None = None) -> FastAPI:
    settings = settings or ApiSettings.from_env()
    wall_clock: TimeSource = wall or SystemWallClock()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=settings.pool_max,
            open=False,
            name="sgw-api",
            check=AsyncConnectionPool.check_connection,
        )
        await pool.open(wait=True, timeout=15)
        sdef = scenario_def(settings.scenario)
        clock = ScenarioClock(sdef, ClockState.initial(sdef, wall_clock.now()), wall_clock)
        async with pool.connection() as conn:
            await clock_service.load(conn, clock, settings.scenario)
            epoch = await ledger.database_epoch(conn)

        async def reload_clock() -> None:
            """A recreated database holds a fresh control row: the process clock follows it, so the scenario
            jobs never expire or re-plan the new data on the old database's scenario time."""
            async with pool.connection() as conn:
                await clock_service.load(conn, clock, settings.scenario)

        broadcaster = LedgerBroadcaster(
            source=_PoolSource(pool),
            poll_s=settings.ledger_poll_s,
            gap_hold_s=settings.gap_hold_s,
            queue_max=settings.client_queue_max,
            epoch=epoch,
            on_control=lambda snap: clock_service.sync_from_control(snap, clock, settings.scenario),
            on_reset=reload_clock,
        )
        await broadcaster.start()
        listener = asyncio.create_task(_listen(settings.database_url, broadcaster), name="sgw-ledger-listen")
        limiter = LoginLimiter(
            per_ip=TokenBuckets(settings.login_ip_burst, settings.login_ip_per_min / 60),
            per_user=TokenBuckets(settings.login_user_burst, settings.login_user_per_min / 60),
        )
        app.state.sgw = ApiState(
            settings=settings, pool=pool, clock=clock, broadcaster=broadcaster, limiter=limiter
        )
        every = scenario_jobs.interval_s()
        jobs = (
            asyncio.create_task(scenario_jobs.loop(app, every), name="sgw-scenario-jobs") if every else None
        )
        warm = asyncio.create_task(_warm_reads(), name="sgw-warm-reads") if every else None
        log.info("api started: scenario=%s epoch=%s head=%s", settings.scenario, epoch, broadcaster.head_seq)
        try:
            yield
        finally:
            if jobs is not None:
                jobs.cancel()
            if warm is not None:
                warm.cancel()
            listener.cancel()
            await broadcaster.stop()
            await close_all(app)
            await pool.close()

    app = FastAPI(
        title="SGW Resilience Decision Platform API",
        lifespan=lifespan,
        openapi_url=OPENAPI_URL,
        docs_url="/api/docs" if settings.demo_mode or settings.api_docs else None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
    )
    app.openapi = openapi_document  # type: ignore[method-assign]
    install_error_handlers(app)
    mount_routers(app, discover_routers())
    app.add_middleware(RequestContextMiddleware, demo_mode=settings.demo_mode)
    app.state.api_metrics = ApiMetrics()
    app.add_middleware(MetricsMiddleware, metrics=app.state.api_metrics)
    return app
