"""One app's database pool and services never reach a later app: they live on that app's state and close with
its lifespan (the cross-module failure where a second test module's app used the first module's dropped
database through a process-global approval pool)."""

from __future__ import annotations

import asyncio
import secrets
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sgw.api.app import create_app
from sgw.api.settings import ApiSettings
from sgw.api.users import seed_users
from sgw.approval import testkit as tk
from sgw.common.app_scope import close_all, on_close, per_app

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
PASSWORD = "scope-" + secrets.token_hex(12)


def _app() -> Any:
    return SimpleNamespace(state=SimpleNamespace())


def test_per_app_builds_once_per_app_and_closes_newest_first() -> None:
    first, second = _app(), _app()
    closed: list[str] = []

    async def close_async(value: str) -> None:
        closed.append(value)

    a = per_app(first, "thing", lambda: "pool-a", closed.append)
    assert per_app(first, "thing", lambda: "pool-other", closed.append) == "pool-a"
    on_close(first, "runtime", close_async, "runtime-a")
    assert per_app(second, "thing", lambda: "pool-b", closed.append) == "pool-b"
    asyncio.run(close_all(first))
    assert a == "pool-a" and closed == ["runtime-a", "pool-a"]
    assert first.state.thing is None and first.state.runtime is None
    assert second.state.thing == "pool-b"
    assert per_app(first, "thing", lambda: "pool-c", closed.append) == "pool-c"


def _client(url: str) -> TestClient:
    settings = ApiSettings(database_url=url, demo_mode=True, cookie_secure=False, login_ip_burst=1000)
    return TestClient(create_app(settings))


def _audit_page(client: TestClient) -> int:
    r = client.post("/api/auth/login", json={"user_id": "audit_01", "password": PASSWORD})
    assert r.status_code == 200, r.text
    page = client.get("/api/audit")
    assert page.status_code == 200, page.text
    return len(page.json())


def test_a_second_app_never_uses_the_first_apps_dropped_database() -> None:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with tk.scratch_database("sgw_scope_a") as first_url:
        seed_users(first_url, PASSWORD)
        with _client(first_url) as first:
            _audit_page(first)
            app_a: Any = first.app
            pool_a = app_a.state.approval_owned_pool
            assert pool_a is not None and not pool_a.closed
        assert pool_a.closed
        assert app_a.state.approval_owned_pool is None
    with tk.scratch_database("sgw_scope_b") as second_url:
        seed_users(second_url, PASSWORD)
        with _client(second_url) as second:
            assert _audit_page(second) >= 0
            app_b: Any = second.app
            assert app_b.state.approval_owned_pool is not pool_a
            assert second_url.rpartition("/")[2] in app_b.state.approval_owned_pool.conninfo
