"""Test helpers for WP-37 database tests (unit and integration): a migrated scratch database (runtime
role for the app), seeded users and the Helene crew proposal, and an API app with the `/v1` routes."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sgw.api.app import create_app
from sgw.api.security import CSRF_HEADER
from sgw.api.settings import ApiSettings
from sgw.integrations.keys import IntegrationKeys
from sgw.integrations.urls import UrlPolicy

KEYS = IntegrationKeys.from_master(bytes.fromhex("a5" * 32))
ALLOWED_HOST = "127.0.0.1:8701"


@dataclass(frozen=True)
class Db:
    admin_url: str
    runtime_url: str
    password: str


@contextmanager
def seeded_db(label: str) -> Iterator[Db]:
    from sgw.api.users import seed_users
    from sgw.approval.seed import run_seed
    from sgw.ingest.testing import scratch_database

    with scratch_database(label) as db:
        run_seed(db.admin_url, use_default_ledger=False)
        password = "wp37-" + secrets.token_hex(10)
        seed_users(db.admin_url, password)
        yield Db(db.admin_url, db.runtime_url, password)


def build_app(runtime_url: str) -> FastAPI:
    app = create_app(
        ApiSettings(
            database_url=runtime_url,
            demo_mode=True,
            heartbeat_s=0.2,
            login_user_burst=1000,
            login_ip_burst=1000,
        )
    )
    app.state.integration_keys = KEYS
    app.state.integration_url_policy = UrlPolicy(allow_hosts=frozenset({ALLOWED_HOST}))
    return app


def login(client: TestClient, user: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"user_id": user, "password": password})
    assert response.status_code == 200, response.text
    return {CSRF_HEADER: client.cookies["sgw_csrf"]}


def new_token(
    client: TestClient,
    csrf: dict[str, str],
    scopes: list[str],
    *,
    days: int = 30,
    name: str = "Halvorsen SCADA bridge",
) -> dict[str, Any]:
    expires = (datetime.now(UTC) + timedelta(days=days)).isoformat()
    response = client.post(
        "/api/admin/tokens", json={"name": name, "scopes": scopes, "expires_at": expires}, headers=csrf
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def audit_kinds(admin_url: str, subject_like: str) -> list[tuple[str, dict[str, Any]]]:
    with psycopg.connect(admin_url) as conn:
        rows = conn.execute(
            "SELECT kind, payload FROM audit_event WHERE subject LIKE %s ORDER BY seq", (subject_like,)
        ).fetchall()
    return [(str(r[0]), dict(r[1])) for r in rows]
