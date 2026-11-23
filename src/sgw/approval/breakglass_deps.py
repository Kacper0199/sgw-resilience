"""FastAPI dependencies for the break-glass and audit routes, bound to WP-08's session layer when present.

Break-glass needs a stepped-up session (`sgw.api.deps.stepped_up`: password re-entered on this session,
CSRF, not read-only); audit verification needs a session with CSRF (read-only roles such as the auditor may
verify); listing needs a session. `app.state` may override `breakglass_service` and `audit_paths`.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, Request

from sgw.approval import audit
from sgw.approval.breakglass import BreakGlassService, SignerSource
from sgw.approval.breakglass_policy import OpaGovernance
from sgw.approval.deps import _API, OPA_ENV, approval_service, current_user_id
from sgw.approval.envelope import EnvelopeService
from sgw.approval.service import ApprovalService
from sgw.approval.signer import SIGNING_ENV, AuditPaths, active_signer, default_paths
from sgw.common.app_scope import per_app

log = logging.getLogger("sgw.approval.breakglass")
SESSION_STEP_UP: Callable[..., Any] = _API.stepped_up if _API else current_user_id
SESSION_CSRF: Callable[..., Any] = _API.csrf_protect if _API else current_user_id


def _user_id(user: Any) -> str:
    return user if isinstance(user, str) else str(user.user_id)


def breakglass_actor(user: Annotated[Any, Depends(SESSION_STEP_UP)]) -> str:
    return _user_id(user)


def auditor_id(user: Annotated[Any, Depends(SESSION_CSRF)]) -> str:
    return _user_id(user)


def audit_paths(request: Request) -> AuditPaths:
    paths = getattr(request.app.state, "audit_paths", None)
    return paths if isinstance(paths, AuditPaths) else default_paths()


def signer_source(paths: AuditPaths) -> SignerSource:
    def load() -> tuple[Any, audit.AnchorStore | None] | None:
        signer = active_signer(paths)
        return None if signer is None else (signer, audit.AnchorStore(paths.anchors))

    return load


def post_commit_signer(paths: AuditPaths) -> SignerSource | None:
    """The stack's api runs with SGW_AUDIT_SIGNING=0 and no private key: audit-checkpoint signs (within its
    interval). Elsewhere (host runs, tests) the api signs right after a break-glass commit."""
    return None if os.environ.get(SIGNING_ENV, "1") == "0" else signer_source(paths)


def breakglass_service(
    request: Request, approvals: Annotated[ApprovalService, Depends(approval_service)]
) -> BreakGlassService:
    service = getattr(request.app.state, "breakglass_service", None)
    if isinstance(service, BreakGlassService):
        return service

    def build() -> BreakGlassService:
        policy = OpaGovernance(os.environ.get(OPA_ENV, "http://127.0.0.1:8181"))
        envelopes = EnvelopeService(policy, clock=approvals.scenario_clock, ledger=approvals.ledger)
        return BreakGlassService(
            approvals, policy, envelopes=envelopes, signer=post_commit_signer(audit_paths(request))
        )

    return per_app(request.app, "breakglass_owned_service", build)
