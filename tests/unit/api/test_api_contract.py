"""K3 conformance: the served OpenAPI is the committed contract; every mounted route is a contract route."""

from __future__ import annotations

import json

import pytest

from sgw.api.app import (
    OPENAPI_URL,
    RouterConflictError,
    app_routes,
    create_app,
    discover_routers,
    mount_routers,
)
from sgw.api.settings import ApiSettings
from sgw.contracts.api_models import contract_routes, missing_routes

from .api_testkit import REPO_ROOT

WP08_ROUTES = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/step-up"),
    ("GET", "/api/me"),
    ("GET", "/api/scenario"),
    ("POST", "/api/scenario"),
    ("GET", "/api/stream/ops"),
    ("GET", "/healthz"),
    ("GET", "/readyz"),
}
TOOLING_ROUTES = {("GET", OPENAPI_URL), ("GET", "/api/docs")}


@pytest.fixture(scope="module")
def app():  # type: ignore[no-untyped-def]
    return create_app(ApiSettings(database_url="postgresql://unused/unused", demo_mode=True))


def test_served_openapi_is_the_committed_contract(app) -> None:  # type: ignore[no-untyped-def]
    committed = json.loads((REPO_ROOT / "contracts" / "openapi.json").read_text(encoding="utf-8"))
    assert app.openapi() == committed


def test_mounted_routes_are_contract_routes(app) -> None:  # type: ignore[no-untyped-def]
    extra = app_routes(app) - contract_routes() - TOOLING_ROUTES
    assert not extra, f"routes outside K3: {sorted(extra)}"


def test_wp08_routes_exist(app) -> None:  # type: ignore[no-untyped-def]
    assert app_routes(app) >= WP08_ROUTES
    served = app_routes(app)
    gaps = missing_routes(
        served, prefixes=("/api/auth", "/api/me", "/api/scenario", "/api/stream/ops", "/healthz")
    )
    assert gaps == []


def test_router_discovery_is_sorted_and_conflicts_fail() -> None:
    found = discover_routers()
    names = [n for n, _ in found]
    assert names == sorted(names)
    assert {"auth", "clock", "health", "session", "stream"} <= set(names)
    from fastapi import FastAPI

    dup = dict(found)["session"]
    with pytest.raises(RouterConflictError, match="/api/me"):
        mount_routers(FastAPI(), [("session", dup), ("copy", dup)])
