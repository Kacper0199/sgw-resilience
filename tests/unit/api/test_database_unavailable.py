"""A request that meets a database being replaced (demo goto, scenario load) answers 503 with Retry-After,
so a client retries instead of reporting an internal error."""

from __future__ import annotations

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sgw.api.errors import install_error_handlers


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/gone")
    async def gone() -> None:
        raise psycopg.OperationalError('database "sgw" does not exist')

    @app.get("/bug")
    async def bug() -> None:
        raise RuntimeError("bug")

    return TestClient(app, raise_server_exceptions=False)


def test_a_lost_database_is_a_retryable_503() -> None:
    res = _client().get("/gone")
    assert res.status_code == 503
    assert res.headers["Retry-After"] == "2"
    assert res.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


def test_other_errors_stay_internal() -> None:
    res = _client().get("/bug")
    assert res.status_code == 500
    assert res.json()["error"]["code"] == "INTERNAL"
