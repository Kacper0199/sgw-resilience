"""K3 Health and control routes: feed freshness, pipeline runs and assets with lineage, DQ checks,
model cards with evaluation, and the control plane (kill switch K0-K4 with a two-function restore, degraded
modes M0-M4).

`POST /api/control/kill` raises the level for one listed role (no step-up: stopping must be easy). A lower
level is a restore: the first signature (command or compliance, stepped-up session) answers 202 with the
unchanged state and `X-SGW-Restore: pending; id=<id>; awaiting=<function>`; the second signature from the
other function answers 200 with the restored state. Routes outside K3 v1.1 (`/api/llm/usage`,
`/api/control/capabilities`) are mounted only once the contract lists them.

The router's lifespan starts the degraded-mode reconciler when `FAULT_*` flags or probes are configured.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse

from sgw.approval import audit
from sgw.approval.breakglass_deps import audit_paths
from sgw.approval.deps import SESSION_READER, SESSION_WRITER, db_conn
from sgw.common.app_scope import per_app
from sgw.contracts.api_models import (
    ControlState,
    DqCheckOut,
    ErrorBody,
    FeedHealthItem,
    KillRequest,
    ModelCard,
    ModeRequest,
    PipelineRunOut,
    contract_routes,
)
from sgw.contracts.vocab import ApprovalFunction, RunMode
from sgw.ops import eval_reports, health, levels
from sgw.ops import pipeline as ops_pipeline
from sgw.ops.control import ControlService, read_control
from sgw.ops.errors import OpsError, OpsForbidden
from sgw.ops.reconciler import Reconciler, enabled, interval_s
from sgw.ops.wiring import build_service

log = logging.getLogger("sgw.ops.api")
SCENARIO_ENV = "SGW_SCENARIO"
DEFAULT_SCENARIO = "helene"
PIPELINE_FUNCTIONS = frozenset({ApprovalFunction.DATA, ApprovalFunction.PLATFORM})
DETAIL_FUNCTIONS = frozenset(
    {ApprovalFunction.PLATFORM, ApprovalFunction.COMMAND, ApprovalFunction.EXECUTIVE}
)
ADAPTER_ENV_PREFIXES = ("FAULT_FEED_",)
ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorBody} for code in (401, 403, 404, 409, 422, 503)
}


@asynccontextmanager
async def ops_lifespan(app: FastAPI) -> AsyncIterator[dict[str, Any]]:
    reconciler: Reconciler | None = None
    if enabled(os.environ):
        api = getattr(app.state, "sgw", None)
        dsn = api.settings.database_url if api is not None else os.environ.get("SGW_DATABASE_URL", "")
        if dsn:
            reconciler = Reconciler(dsn, build_service, every_s=interval_s(os.environ))
            reconciler.start()
            log.info("ops reconciler started (every %.1f s)", reconciler.every_s)
    try:
        yield {}
    finally:
        if reconciler is not None:
            reconciler.stop()


router = APIRouter(lifespan=ops_lifespan)
proposed_router = APIRouter()
Conn = Annotated[psycopg.Connection[Any], Depends(db_conn)]


@dataclass(frozen=True)
class Principal:
    user_id: str
    stepped_up: bool
    session_hash: str | None = None


def _step_up_valid(request: Request, user: Any) -> bool:
    api = getattr(request.app.state, "sgw", None)
    check = getattr(user, "step_up_valid_until", None)
    if api is None or check is None:
        return False
    return check(api.clock.wall.now(), api.settings.step_up_ttl_s) is not None


def ops_reader(user: Annotated[Any, Depends(SESSION_READER)]) -> str:
    return user if isinstance(user, str) else str(user.user_id)


def ops_writer(request: Request, user: Annotated[Any, Depends(SESSION_WRITER)]) -> Principal:
    if isinstance(user, str):
        return Principal(user, False)
    return Principal(str(user.user_id), _step_up_valid(request, user), getattr(user, "session_hash", None))


Reader = Annotated[str, Depends(ops_reader)]
Writer = Annotated[Principal, Depends(ops_writer)]


def control_service(request: Request) -> ControlService:
    service = getattr(request.app.state, "ops_control_service", None)
    if isinstance(service, ControlService):
        return service

    def build() -> ControlService:
        api = getattr(request.app.state, "sgw", None)
        paths = audit_paths(request)
        if api is None:
            return build_service(paths=paths)
        return build_service(clock=api.clock.wall.now, scenario_clock=api.clock.now, paths=paths)

    return per_app(request.app, "ops_owned_control_service", build)


Service = Annotated[ControlService, Depends(control_service)]


def replay_time(request: Request) -> datetime | None:
    """The scenario time when the API runs a replay (freshness is read at the replay clock), else None."""
    api = getattr(request.app.state, "sgw", None)
    if api is None or api.clock.view.run_mode is RunMode.LIVE:
        return None
    now: datetime = api.clock.now()
    return now


def _error(error: OpsError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content=error.body())


@router.get(
    "/api/feeds/health", operation_id="listFeedHealth", tags=["health"], response_model=list[FeedHealthItem]
)
def list_feed_health(_user: Reader, conn: Conn, request: Request) -> list[FeedHealthItem]:
    return health.feeds(conn, replay_time(request))


@router.get(
    "/api/pipeline/runs",
    operation_id="listPipelineRuns",
    tags=["health"],
    response_model=list[PipelineRunOut],
)
def list_pipeline_runs(
    user: Reader,
    conn: Conn,
    asset: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int | None, Query(ge=1, le=health.MAX_ROWS)] = None,
) -> list[PipelineRunOut]:
    out = health.runs(conn, asset=asset, limit=limit)
    if _function_of(conn, user) in DETAIL_FUNCTIONS:
        return out
    return [r.model_copy(update={"error": None if r.error is None else "withheld"}) for r in out]


@router.get("/api/pipeline/assets", operation_id="listPipelineAssets", tags=["health"])
def list_pipeline_assets(_user: Reader, conn: Conn, request: Request) -> list[dict[str, Any]]:
    return health.lineage(conn, replay_time(request))


@router.post(
    "/api/pipeline/assets/{name}/run",
    operation_id="runPipelineAsset",
    tags=["health"],
    response_model=PipelineRunOut,
    status_code=202,
    responses=ERRORS,
)
def run_pipeline_asset(
    name: str, user: Writer, conn: Conn, service: Service
) -> PipelineRunOut | JSONResponse:
    try:
        actor = _actor_function(conn, user.user_id)
        if actor not in PIPELINE_FUNCTIONS:
            raise OpsForbidden(
                "pipeline runs are started by the data and platform teams",
                code="PIPELINE_RUN_DENIED",
            )
        run = ops_pipeline.run_asset(
            conn,
            service,
            name,
            scenario=os.environ.get(SCENARIO_ENV, DEFAULT_SCENARIO),
            env=adapter_env(os.environ),
        )
    except OpsError as error:
        return _error(error)
    with conn.transaction():
        audit.append(
            conn,
            kind="pipeline_run_requested",
            actor_type="user",
            actor_id=user.user_id,
            subject=f"pipeline:{name}",
            payload={"asset": name, "run_id": run.run_id, "status": run.status, "function": actor.value},
            occurred_at=service.clock(),
        )
    return run


def adapter_env(environ: Mapping[str, str]) -> dict[str, str]:
    """Only the feed-fault drill flags reach the adapters; nothing else from the API's environment."""
    return {k: v for k, v in environ.items() if k.startswith(ADAPTER_ENV_PREFIXES)}


def _function_of(conn: psycopg.Connection[Any], user_id: str) -> ApprovalFunction | None:
    row = conn.execute("SELECT function FROM app_user WHERE user_id = %s", (user_id,)).fetchone()
    return ApprovalFunction(row[0]) if row else None


def _actor_function(conn: psycopg.Connection[Any], user_id: str) -> ApprovalFunction:
    row = conn.execute("SELECT function FROM app_user WHERE user_id = %s", (user_id,)).fetchone()
    if row is None:
        raise OpsForbidden(f"unknown user {user_id}", code="UNKNOWN_USER")
    return ApprovalFunction(row[0])


@router.get("/api/dq/checks", operation_id="listDqChecks", tags=["health"], response_model=list[DqCheckOut])
def list_dq_checks(
    _user: Reader,
    conn: Conn,
    request: Request,
    asset: Annotated[str | None, Query(max_length=64)] = None,
    failed: Annotated[bool, Query()] = False,
    limit: Annotated[int | None, Query(ge=1, le=health.MAX_ROWS)] = None,
) -> list[DqCheckOut]:
    return health.dq_checks(conn, asset=asset, failed_only=failed, limit=limit, at=replay_time(request))


@router.get("/api/models", operation_id="listModels", tags=["health"], response_model=list[ModelCard])
def list_models(_user: Reader, conn: Conn) -> list[ModelCard]:
    return health.models(conn)


@router.get(
    "/api/models/{name}/evaluation",
    operation_id="getModelEvaluation",
    tags=["health"],
    response_model=None,
    responses=ERRORS,
)
def get_model_evaluation(name: str, _user: Reader, conn: Conn) -> dict[str, Any] | JSONResponse:
    named = eval_reports.report(name)
    if named is not None:
        return named
    try:
        return eval_reports.with_k17_view(health.model_evaluation(conn, name))
    except OpsError as error:
        return _error(error)


@router.get("/api/control/kill", operation_id="getKill", tags=["control"], response_model=ControlState)
def get_kill(_user: Reader, conn: Conn, response: Response, service: Service) -> ControlState:
    pending = service.pending_restore(conn)
    if pending is not None:
        response.headers["X-SGW-Restore"] = (
            f"pending; id={pending['restore_id']}; to={pending['to_level']};"
            f" signed={pending['requested_function']}"
        )
    return service.state(conn)


@router.post(
    "/api/control/kill",
    operation_id="setKill",
    tags=["control"],
    response_model=ControlState,
    responses=ERRORS,
)
def set_kill(body: KillRequest, user: Writer, conn: Conn, service: Service) -> ControlState | JSONResponse:
    try:
        outcome = service.set_kill(
            conn,
            user_id=user.user_id,
            level=body.kill_level,
            reason=body.reason,
            session_hash=user.session_hash,
            stepped_up=user.stepped_up,
        )
    except OpsError as error:
        return _error(error)
    if outcome.status == "restore_pending":
        assert outcome.awaiting_function is not None
        return JSONResponse(
            status_code=202,
            content=outcome.state.model_dump(mode="json"),
            headers={
                "X-SGW-Restore": (
                    f"pending; id={outcome.restore_id}; awaiting={outcome.awaiting_function.value}"
                )
            },
        )
    return outcome.state


@router.get("/api/control/mode", operation_id="getMode", tags=["control"], response_model=ControlState)
def get_mode(_user: Reader, conn: Conn, service: Service) -> ControlState:
    return service.state(conn)


@router.post(
    "/api/control/mode",
    operation_id="setMode",
    tags=["control"],
    response_model=ControlState,
    responses=ERRORS,
)
def set_mode(body: ModeRequest, user: Writer, conn: Conn, service: Service) -> ControlState | JSONResponse:
    try:
        return service.set_mode(conn, user_id=user.user_id, mode=body.degraded_mode, reason=body.reason)
    except OpsError as error:
        return _error(error)


@proposed_router.get("/api/llm/usage", operation_id="getLlmUsage", tags=["health"], response_model=None)
def get_llm_usage(
    user: Reader,
    conn: Conn,
    group_by: Annotated[str, Query(max_length=64)] = "purpose,node,model",
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    run_id: Annotated[str | None, Query(max_length=128)] = None,
) -> dict[str, Any] | JSONResponse:
    if _function_of(conn, user) not in DETAIL_FUNCTIONS:
        return _error(
            OpsForbidden("LLM usage is shown to platform, command and executive", code="USAGE_DENIED")
        )
    groups = tuple(g.strip() for g in group_by.split(",") if g.strip())
    return health.llm_usage(conn, group_by=groups, flt=health.UsageFilter(since, until, run_id))


@proposed_router.get("/api/control/capabilities", operation_id="getCapabilities", tags=["control"])
def get_capabilities(_user: Reader, conn: Conn, service: Service) -> dict[str, Any]:
    view = read_control(conn)
    caps = service.capabilities(conn)
    rows = conn.execute(
        "SELECT signal, active, source, detail, floor_mode, since FROM ops_signal"
        " WHERE active ORDER BY signal"
    ).fetchall()
    return {
        "kill_level": view.kill_level.value,
        "degraded_mode": view.degraded_mode.value,
        "control_readable": view.readable,
        "capabilities": {cap.value: allowed for cap, allowed in caps.items()},
        "active_signals": [
            {
                "signal": r[0],
                "source": r[2],
                "detail": r[3],
                "floor": r[4],
                "since": r[5].isoformat() if r[5] else None,
                "exit": levels.RULES_BY_SIGNAL[r[0]].exit if r[0] in levels.RULES_BY_SIGNAL else "manual",
            }
            for r in rows
        ],
        "pending_restore": _jsonable(service.pending_restore(conn)),
        "mode_ladder": [
            {"mode": m.mode.value, "name": m.name, "available": m.available, "disabled": m.disabled}
            for m in levels.MODE_LADDER
        ],
    }


def _jsonable(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}


PROPOSED_ROUTES = {("GET", "/api/llm/usage"), ("GET", "/api/control/capabilities")}
if contract_routes() >= PROPOSED_ROUTES:
    router.include_router(proposed_router)
