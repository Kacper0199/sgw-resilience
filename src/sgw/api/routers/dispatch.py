"""Crew dispatch routes: the assignable targets, propose an assignment, sign or reject it,
withdraw it, and move the crew (on the way, on site, staged, blocked with a reason, clear block, release).
Writes need a session, CSRF and a non read-only role; the dispatch policy (OPA `sgw.dispatch`) decides who may
act and who signs. Errors use the K3 `ErrorBody`. The crew list itself stays `GET /api/crews`."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse

from sgw.api.deps import CurrentUser, DbConn
from sgw.approval.deps import OPA_ENV, db_conn, writer_id
from sgw.approval.errors import ApprovalError
from sgw.approval.ledger import default_sink
from sgw.common.app_scope import per_app
from sgw.contracts.api_models import (
    CrewAssignRequest,
    CrewDispatchResult,
    CrewMoveRequest,
    CrewSignRequest,
    CrewTarget,
    ErrorBody,
)
from sgw.dispatch import read
from sgw.dispatch.policy import OpaDispatch
from sgw.dispatch.service import DispatchService

log = logging.getLogger("sgw.api.dispatch")

router = APIRouter(prefix="/api/crews", tags=["ops"])

Conn = Annotated[psycopg.Connection[Any], Depends(db_conn)]
Writer = Annotated[str, Depends(writer_id)]
CrewId = Annotated[str, Path(pattern=r"^[A-Z0-9][A-Z0-9-]{0,63}$")]
ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorBody} for code in (401, 403, 404, 409, 422, 503)
}


def app_dispatch_service(app: Any) -> DispatchService:
    service = getattr(app.state, "dispatch_service", None)
    if service is not None:
        return service  # type: ignore[no-any-return]

    def build() -> DispatchService:
        api = getattr(app.state, "sgw", None)
        clock = api.clock.now if api is not None else None
        if clock is None:
            raise RuntimeError("the dispatch service needs the API scenario clock")
        policy = OpaDispatch(os.environ.get(OPA_ENV, "http://127.0.0.1:8181"))
        return DispatchService(policy, scenario_clock=clock, ledger=default_sink())

    return per_app(app, "dispatch_owned_service", build)


def dispatch_service(request: Request) -> DispatchService:
    return app_dispatch_service(request.app)


Service = Annotated[DispatchService, Depends(dispatch_service)]


def _run(
    call: Callable[[], str | None], crew_id: str, status: int = 200
) -> CrewDispatchResult | JSONResponse:
    try:
        assignment_id = call()
    except ApprovalError as error:
        if error.status_code >= 500:
            cause = {"crew_id": crew_id, "code": error.code, "cause": str(error)}
            log.error("crew dispatch failed", extra=cause)
        return JSONResponse(status_code=error.status_code, content=error.body())
    body = CrewDispatchResult(crew_id=crew_id, assignment_id=assignment_id)
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


@router.get("/targets", operation_id="listCrewTargets", response_model=list[CrewTarget])
async def list_crew_targets(_: CurrentUser, conn: DbConn) -> list[CrewTarget]:
    return await read.targets(conn)


@router.post(
    "/{crew_id}/assignments",
    operation_id="assignCrew",
    response_model=CrewDispatchResult,
    status_code=201,
    responses=ERRORS,
)
def assign_crew(
    crew_id: CrewId, body: CrewAssignRequest, user: Writer, conn: Conn, service: Service
) -> CrewDispatchResult | JSONResponse:
    return _run(
        lambda: service.propose(
            conn, user_id=user, crew_id=crew_id, target_kind=body.target_kind, target_id=body.target_id
        ),
        crew_id,
        201,
    )


@router.post(
    "/{crew_id}/assignment/sign",
    operation_id="signCrewAssignment",
    response_model=CrewDispatchResult,
    responses=ERRORS,
)
def sign_crew_assignment(
    crew_id: CrewId, body: CrewSignRequest, user: Writer, conn: Conn, service: Service
) -> CrewDispatchResult | JSONResponse:
    return _run(
        lambda: service.sign(conn, user_id=user, crew_id=crew_id, decision=body.decision, reason=body.reason),
        crew_id,
    )


@router.post(
    "/{crew_id}/assignment/withdraw",
    operation_id="withdrawCrewAssignment",
    response_model=CrewDispatchResult,
    responses=ERRORS,
)
def withdraw_crew_assignment(
    crew_id: CrewId, user: Writer, conn: Conn, service: Service
) -> CrewDispatchResult | JSONResponse:
    return _run(lambda: service.withdraw(conn, user_id=user, crew_id=crew_id), crew_id)


@router.post(
    "/{crew_id}/status", operation_id="moveCrew", response_model=CrewDispatchResult, responses=ERRORS
)
def move_crew(
    crew_id: CrewId, body: CrewMoveRequest, user: Writer, conn: Conn, service: Service
) -> CrewDispatchResult | JSONResponse:
    return _run(
        lambda: service.move(
            conn, user_id=user, crew_id=crew_id, move=body.move, block_reason=body.block_reason
        ),
        crew_id,
    )
