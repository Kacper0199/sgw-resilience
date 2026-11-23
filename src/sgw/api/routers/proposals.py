"""K3 decision routes: list, read, create, approve or reject (compare-and-set), withdraw and the clock
waterfall. Every response that carries a proposal also carries `ETag: "<version>-<action_hash>"`; writes
accept `If-Match` with that value (412 on mismatch). Errors use the K3 `ErrorBody`."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from sgw.api.routers._scenario import active_scenario
from sgw.approval.deps import approval_service, db_conn, publish, reader_id, writer_id
from sgw.approval.errors import ApprovalError
from sgw.approval.service import ApprovalService, Outcome
from sgw.contracts.api_models import (
    ApprovalRequest,
    ApprovalResponse,
    ErrorBody,
    ProposalCard,
    ProposalCreate,
    ProposalSummary,
    StaleProposal,
    WithdrawRequest,
)
from sgw.contracts.clocks import ClockWaterfall
from sgw.scenarios import packs

log = logging.getLogger("sgw.api.proposals")

router = APIRouter(prefix="/api/proposals", tags=["decisions"])

Conn = Annotated[psycopg.Connection[Any], Depends(db_conn)]
Service = Annotated[ApprovalService, Depends(approval_service)]
Reader = Annotated[str, Depends(reader_id)]
Writer = Annotated[str, Depends(writer_id)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]
ERRORS: dict[int | str, dict[str, Any]] = {
    **{code: {"model": ErrorBody} for code in (401, 403, 404, 409, 422, 503)},
    412: {"model": StaleProposal, "description": "the proposal changed; K3 StaleProposal body"},
}


def _error(error: ApprovalError) -> JSONResponse:
    if error.status_code >= 500:
        log.error("approval request failed", extra={"code": error.code, "cause": str(error)})
    return JSONResponse(status_code=error.status_code, content=error.body())


def _run[T](
    request: Request, response: Response, call: Callable[[], Outcome[T]], status: int = 200
) -> T | JSONResponse:
    try:
        outcome = call()
    except ApprovalError as error:
        return _error(error)
    if outcome.etag:
        response.headers["ETag"] = outcome.etag
    response.status_code = status
    publish(request, outcome.events)
    return outcome.value


@router.get("", operation_id="listProposals", response_model=list[ProposalSummary], responses=ERRORS)
def list_proposals(
    _user: Reader,
    conn: Conn,
    service: Service,
    request: Request,
    state: Annotated[list[str] | None, Query()] = None,
) -> list[ProposalSummary]:
    return packs.visible(active_scenario(request), service.summaries(conn, state), lambda p: p.proposal_id)


@router.get("/{proposal_id}", operation_id="getProposal", response_model=ProposalCard, responses=ERRORS)
def get_proposal(
    proposal_id: str, request: Request, response: Response, _user: Reader, conn: Conn, service: Service
) -> ProposalCard | JSONResponse:
    return _run(request, response, lambda: service.card_with_etag(conn, proposal_id))


@router.post(
    "", operation_id="createProposal", response_model=ProposalCard, status_code=201, responses=ERRORS
)
def create_proposal(
    body: ProposalCreate, request: Request, response: Response, user: Writer, conn: Conn, service: Service
) -> ProposalCard | JSONResponse:
    result = _run(request, response, lambda: service.create(conn, proposed_by=user, request=body), 201)
    if isinstance(result, ProposalCard):
        response.headers["Location"] = f"/api/proposals/{result.proposal_id}"
    return result


@router.post(
    "/{proposal_id}/approvals",
    operation_id="approveProposal",
    response_model=ApprovalResponse,
    responses=ERRORS,
)
def approve_proposal(
    proposal_id: str,
    body: ApprovalRequest,
    request: Request,
    response: Response,
    user: Writer,
    conn: Conn,
    service: Service,
    if_match: IfMatch = None,
) -> ApprovalResponse | JSONResponse:
    return _run(
        request,
        response,
        lambda: service.decide(conn, user_id=user, proposal_id=proposal_id, request=body, if_match=if_match),
    )


@router.post(
    "/{proposal_id}/withdraw",
    operation_id="withdrawProposal",
    response_model=ProposalSummary,
    responses=ERRORS,
)
def withdraw_proposal(
    proposal_id: str,
    body: WithdrawRequest,
    request: Request,
    response: Response,
    user: Writer,
    conn: Conn,
    service: Service,
    if_match: IfMatch = None,
) -> ProposalSummary | JSONResponse:
    return _run(
        request,
        response,
        lambda: service.withdraw(
            conn, user_id=user, proposal_id=proposal_id, request=body, if_match=if_match
        ),
    )


@router.get("/{proposal_id}/clock", operation_id="getClock", response_model=ClockWaterfall, responses=ERRORS)
def get_clock(proposal_id: str, _user: Reader, conn: Conn, service: Service) -> ClockWaterfall | JSONResponse:
    try:
        return service.clock(conn, proposal_id)
    except ApprovalError as error:
        return _error(error)
