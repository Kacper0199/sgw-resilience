"""K3 governance routes: break-glass on a T3 proposal, the audit list and the audit verifier.

`POST /api/proposals/{id}/break-glass` (IC alone, stepped-up session, mandatory reason, `If-Match`) returns
the proposal card with its break-glass block; `GET /api/audit?from_seq=` pages the hash chain;
`POST /api/audit/verify` recomputes it and checks signed checkpoints and anchors (first bad seq)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from sgw.approval import audit
from sgw.approval.breakglass import BreakGlassService
from sgw.approval.breakglass_deps import audit_paths, auditor_id, breakglass_actor, breakglass_service
from sgw.approval.deps import db_conn, publish, reader_id
from sgw.approval.errors import ApprovalError
from sgw.approval.signer import AuditPaths, Keyring
from sgw.contracts.api_models import (
    AuditEventOut,
    AuditVerifyResult,
    BreakGlassRequest,
    CosignTaskOut,
    ErrorBody,
    ProposalCard,
    StaleProposal,
)

router = APIRouter(tags=["governance"])

Conn = Annotated[psycopg.Connection[Any], Depends(db_conn)]
Service = Annotated[BreakGlassService, Depends(breakglass_service)]
Paths = Annotated[AuditPaths, Depends(audit_paths)]
PAGE = 500
VERIFY_WINDOW_S = 10.0
ERRORS: dict[int | str, dict[str, Any]] = {
    **{code: {"model": ErrorBody} for code in (401, 403, 404, 409, 422, 503)},
    412: {"model": StaleProposal, "description": "the proposal changed; K3 StaleProposal body"},
}


def _error(error: ApprovalError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content=error.body())


@router.post(
    "/api/proposals/{proposal_id}/break-glass",
    operation_id="breakGlass",
    tags=["decisions"],
    response_model=ProposalCard,
    responses=ERRORS,
)
def break_glass(
    proposal_id: str,
    body: BreakGlassRequest,
    request: Request,
    response: Response,
    user: Annotated[str, Depends(breakglass_actor)],
    conn: Conn,
    service: Service,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ProposalCard | JSONResponse:
    try:
        outcome = service.invoke(conn, user_id=user, proposal_id=proposal_id, request=body, if_match=if_match)
    except ApprovalError as error:
        return _error(error)
    if outcome.etag:
        response.headers["ETag"] = outcome.etag
    publish(request, outcome.events)
    return outcome.value


@router.post(
    "/api/proposals/{proposal_id}/cosign",
    operation_id="cosignBreakGlass",
    tags=["decisions"],
    response_model=CosignTaskOut,
    responses=ERRORS,
)
def cosign_break_glass(
    proposal_id: str,
    request: Request,
    response: Response,
    user: Annotated[str, Depends(breakglass_actor)],
    conn: Conn,
    service: Service,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> CosignTaskOut | JSONResponse:
    try:
        outcome = service.cosign(conn, user_id=user, proposal_id=proposal_id, if_match=if_match)
    except ApprovalError as error:
        return _error(error)
    if outcome.etag:
        response.headers["ETag"] = outcome.etag
    publish(request, outcome.events)
    return outcome.value.out()


@router.get("/api/audit", operation_id="listAudit", response_model=list[AuditEventOut], responses=ERRORS)
def list_audit(
    _user: Annotated[str, Depends(reader_id)],
    conn: Conn,
    from_seq: Annotated[str | None, Query()] = None,
    subject: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
) -> list[AuditEventOut] | JSONResponse:
    start = 1
    if from_seq is not None:
        if not from_seq.isdigit() or int(from_seq) < 1:
            return JSONResponse(
                status_code=422,
                content={"error": {"code": "BAD_FROM_SEQ", "message": "from_seq must be a positive integer"}},
            )
        start = int(from_seq)
    return audit.list_events(conn, from_seq=start, limit=PAGE, subject=subject)


@router.post(
    "/api/audit/verify", operation_id="verifyAudit", response_model=AuditVerifyResult, responses=ERRORS
)
def verify_audit(
    request: Request, user: Annotated[str, Depends(auditor_id)], conn: Conn, paths: Paths
) -> AuditVerifyResult | JSONResponse:
    """Full recomputation is O(n): one run per session per window; inside the window other sessions get the
    last result (at most `window` seconds old)."""
    state = _verify_state(request)
    window = float(getattr(request.app.state, "audit_verify_window_s", VERIFY_WINDOW_S))
    now = time.monotonic()
    with state.lock:
        last = state.by_session.get(user)
        if last is not None and now - last < window:
            retry = max(1, int(window - (now - last)) + 1)
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry)},
                content={"error": {"code": "RATE_LIMITED", "message": f"verify again in {retry} s"}},
            )
        state.by_session[user] = now
        if state.cached is not None and now - state.cached[0] < window:
            return state.cached[1]
    keyring = Keyring.load(paths.keyring)
    anchors = audit.AnchorStore(paths.anchors)
    result = audit.verify(conn, keyring=keyring, anchors=anchors).result()
    with state.lock:
        state.cached = (time.monotonic(), result)
    return result


@dataclass
class _VerifyState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    by_session: dict[str, float] = field(default_factory=dict)
    cached: tuple[float, AuditVerifyResult] | None = None


def _verify_state(request: Request) -> _VerifyState:
    state = getattr(request.app.state, "audit_verify_state", None)
    if not isinstance(state, _VerifyState):
        state = _VerifyState()
        request.app.state.audit_verify_state = state
    return state
