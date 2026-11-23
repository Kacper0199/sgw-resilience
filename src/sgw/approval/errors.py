"""Operational errors of the approval service, each with an HTTP status and a stable K3 `ErrorDetail.code`.

Database authority errors map by SQLSTATE: 42501 (insufficient_privilege) -> 403, 09000
(triggered_action_exception, stale version or hash) -> 412, 23505 (unique_violation) -> 409.
"""

from __future__ import annotations

from typing import Any

import psycopg

from sgw.contracts.api_models import StaleProposal


class ApprovalError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(
        self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details: dict[str, Any] = details or {}

    def body(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class NotFoundError(ApprovalError):
    status_code = 404
    code = "NOT_FOUND"


class ForbiddenError(ApprovalError):
    status_code = 403
    code = "FORBIDDEN"


class ConflictError(ApprovalError):
    status_code = 409
    code = "CONFLICT"


class PreconditionFailedError(ApprovalError):
    """412. With `stale` set (a proposal changed under the caller) the body is the frozen K3
    `StaleProposal` itself, not an `ErrorBody`."""

    status_code = 412
    code = "STALE_PROPOSAL"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        stale: StaleProposal | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)
        self.stale = stale

    def body(self) -> dict[str, Any]:
        if self.stale is not None:
            return self.stale.model_dump(mode="json")
        return super().body()


class UnprocessableError(ApprovalError):
    status_code = 422
    code = "UNPROCESSABLE"


class PolicyUnavailableError(ApprovalError):
    """503. The message keeps the technical cause for the log; the body tells the user in plain words."""

    status_code = 503
    code = "POLICY_UNAVAILABLE"
    public_message = (
        "The sign-off rules could not be checked just now, so nothing was changed. Try again in a minute."
    )

    def body(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.public_message, "details": {}}}


SQLSTATE_ERRORS: dict[str, tuple[type[ApprovalError], str]] = {
    "42501": (ForbiddenError, "DB_AUTHORITY_DENIED"),
    "09000": (PreconditionFailedError, "STALE_PROPOSAL"),
    "23503": (UnprocessableError, "UNKNOWN_REFERENCE"),
    "23505": (ConflictError, "DUPLICATE"),
}
SIGNATURE_CONSTRAINTS = frozenset(
    {
        "approval_proposal_id_proposal_version_function_key",
        "approval_proposal_id_proposal_version_approver_id_key",
    }
)


def from_db_error(error: psycopg.Error) -> ApprovalError | None:
    sqlstate = getattr(error, "sqlstate", None)
    mapped = SQLSTATE_ERRORS.get(sqlstate or "")
    if mapped is None:
        return None
    cls, code = mapped
    diag = error.diag
    constraint = diag.constraint_name if diag else None
    if sqlstate == "23505" and constraint in SIGNATURE_CONSTRAINTS:
        code = "ALREADY_SIGNED"
    primary = diag.message_primary if diag else None
    if primary and primary.startswith("kill switch K"):
        code, primary = "SIGNING_PAUSED", "Signing is paused while the stop level is raised."
    elif primary and primary.startswith("degraded ("):
        code, primary = "SIGNING_PAUSED", "Signing is paused while SGW runs in a reduced mode."
    details: dict[str, Any] = {"sqlstate": sqlstate}
    if constraint:
        details["constraint"] = constraint
    return cls(primary or str(error), code=code, details=details)
