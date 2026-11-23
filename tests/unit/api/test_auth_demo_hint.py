"""`/api/auth/config` names the public demo password only in DEMO_MODE and only when every account's
stored password is that value, so an install with generated passwords shows no wrong hint."""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from sgw.api.app import create_app
from sgw.api.settings import ApiSettings
from sgw.api.users import seed_users
from sgw.approval import testkit as tk
from sgw.contracts.api_models import AuthConfig
from sgw.contracts.identities import PUBLIC_DEMO_PASSWORD

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: D-113 auth hint needs Postgres
    with tk.scratch_database("sgw_d113_t") as url:
        yield url


def _config(db_url: str, *, demo_mode: bool) -> dict[str, object]:
    settings = ApiSettings(database_url=db_url, demo_mode=demo_mode, cookie_secure=not demo_mode)
    with TestClient(create_app(settings)) as client:
        r = client.get("/api/auth/config")
        assert r.status_code == 200
        AuthConfig.model_validate(r.json())
        return r.json()


def test_hint_only_when_every_password_is_the_public_value(db_url: str) -> None:
    seed_users(db_url, PUBLIC_DEMO_PASSWORD, env={"DEMO_PASSWORD_MIN_LENGTH": "3"})
    assert _config(db_url, demo_mode=True) == {"demo_mode": True, "demo_password": PUBLIC_DEMO_PASSWORD}
    assert _config(db_url, demo_mode=False) == {"demo_mode": False}

    seed_users(
        db_url,
        PUBLIC_DEMO_PASSWORD,
        env={"DEMO_PASSWORD_MIN_LENGTH": "3", "DEMO_PASSWORD_IC_01": "a-generated-local-value"},
    )
    assert _config(db_url, demo_mode=True) == {"demo_mode": True}


def test_no_hint_without_accounts(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("UPDATE app_user SET password_hash = NULL")
    assert _config(db_url, demo_mode=True) == {"demo_mode": True}
