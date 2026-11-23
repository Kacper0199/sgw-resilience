"""Operational errors of the ops service, each with an HTTP status and a stable K3 `ErrorDetail.code`."""

from __future__ import annotations

import logging
from typing import Any

import psycopg

log = logging.getLogger("sgw.ops.errors")


class OpsError(Exception):
    status_code = 400

    def __init__(self, message: str, *, code: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def body(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class OpsForbidden(OpsError):
    status_code = 403


class OpsNotFound(OpsError):
    status_code = 404


class OpsConflict(OpsError):
    status_code = 409


class OpsUnavailable(OpsError):
    status_code = 503


def connection_lost(error: psycopg.Error) -> bool:
    """The connection went away (SQLSTATE classes 08 and 57, e.g. a demo moment load dropping the database
    under the API), so nothing was decided about the change itself."""
    state = error.sqlstate
    return (state is None and isinstance(error, psycopg.OperationalError)) or (
        state is not None and state[:2] in {"08", "57"}
    )


def from_db_error(error: psycopg.Error) -> OpsError:
    """SQLSTATE 42501 (the database refused on authority) -> 403; a lost connection -> 503; anything else ->
    409. The client gets a generic message; the database's reason is logged with its SQLSTATE."""
    if connection_lost(error):
        return OpsUnavailable("the database connection was lost; try again", code="DATABASE_UNAVAILABLE")
    log.warning(
        "control change refused by the database",
        extra={"sqlstate": error.sqlstate, "reason": (error.diag.message_primary or "").strip()},
    )
    if error.sqlstate == "42501":
        return OpsForbidden("the database refused this control change", code="REFUSED_BY_DATABASE")
    return OpsConflict("the control change conflicts with the current state", code="CONTROL_CONFLICT")
