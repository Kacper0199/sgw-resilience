"""Operational errors and the one place that maps them to K3 `ErrorBody` responses."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout
from starlette.exceptions import HTTPException as StarletteHTTPException

from sgw.contracts.api_models import ErrorBody, ErrorDetail

log = logging.getLogger("sgw.api")


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"
    is_operational = True

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.headers = headers or {}
        if code:
            self.code = code


class Unauthenticated(AppError):
    status_code = 401
    code = "UNAUTHENTICATED"


class Forbidden(AppError):
    status_code = 403
    code = "FORBIDDEN"


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"


class Unprocessable(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class TooManyRequests(AppError):
    status_code = 429
    code = "RATE_LIMITED"


class Unavailable(AppError):
    status_code = 503
    code = "UNAVAILABLE"


def error_response(
    status: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    body = ErrorBody(error=ErrorDetail(code=code, message=message, details=details or {}))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


_HTTP_CODES = {
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        response = error_response(exc.status_code, exc.code, exc.message, exc.details)
        response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [
            {"loc": [str(p) for p in err.get("loc", ())], "msg": str(err.get("msg", ""))}
            for err in exc.errors()
        ]
        return error_response(422, "VALIDATION_ERROR", "request failed validation", {"errors": problems})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, psycopg.OperationalError | PoolTimeout):
            log.warning("database unavailable: %s", type(exc).__name__)
            response = error_response(
                503, "DATABASE_UNAVAILABLE", "the database is not reachable right now; try again in a moment"
            )
            response.headers["Retry-After"] = "2"
            return response
        log.exception("unhandled error", extra={"request_id": getattr(request.state, "request_id", None)})
        return error_response(500, "INTERNAL", "internal error")
