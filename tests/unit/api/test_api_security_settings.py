from __future__ import annotations

import pytest

from sgw.api.security import (
    csrf_matches,
    csrf_token,
    hash_password,
    new_session_token,
    token_hash,
    verify_password,
)
from sgw.api.settings import ApiSettings, SettingsError
from sgw.api.users import seed_rows
from sgw.contracts.identities import load_users

from .api_testkit import USERS_YAML


def test_argon2_round_trip_and_unknown_user() -> None:
    h = hash_password("correct horse")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse")
    assert not verify_password(h, "wrong")
    assert not verify_password(None, "correct horse")
    assert not verify_password("not-a-hash", "x")


def test_session_token_and_csrf_are_bound() -> None:
    a, b = new_session_token(), new_session_token()
    assert a != b and len(a) >= 40
    assert len(token_hash(a)) == 64
    assert csrf_matches(a, csrf_token(a))
    assert not csrf_matches(a, csrf_token(b))
    assert not csrf_matches(a, None)


def test_settings_from_env_validates() -> None:
    s = ApiSettings.from_env({"SGW_DATABASE_URL": "postgresql://x/y", "SGW_COOKIE_SECURE": "1"})
    assert not s.demo_mode, "DEMO_MODE is off unless the deployment turns it on"
    assert s.heartbeat_s == 10.0 and s.step_up_ttl_s == 300
    with pytest.raises(SettingsError, match="Secure"):
        ApiSettings.from_env({"SGW_DATABASE_URL": "postgresql://x/y"})
    assert ApiSettings.from_env({"SGW_DATABASE_URL": "postgresql://x/y", "DEMO_MODE": "1"}).demo_mode
    assert "demo_password" not in repr(s)
    with pytest.raises(SettingsError):
        ApiSettings.from_env({})
    with pytest.raises(SettingsError):
        ApiSettings.from_env({"SGW_DATABASE_URL": "x", "DEMO_MODE": "maybe"})
    with pytest.raises(SettingsError):
        ApiSettings.from_env({"SGW_DATABASE_URL": "x", "SGW_SSE_HEARTBEAT_S": "0"})


def test_seed_rows_hash_every_user_and_refuse_short_password() -> None:
    users = load_users(USERS_YAML)
    rows = seed_rows(users, "long-enough-pass")
    assert {r["user_id"] for r in rows} == {u.user_id for u in users.users}
    assert all(r["password_hash"].startswith("$argon2id$") for r in rows)
    assert all(r["functions"] == [r["function"]] for r in rows)
    with pytest.raises(ValueError, match="at least 8"):
        seed_rows(users, "short")


def test_local_demo_env_may_lower_the_password_minimum_but_not_below_three() -> None:
    users = load_users(USERS_YAML)
    rows = seed_rows(users, "123", env={"DEMO_PASSWORD_MIN_LENGTH": "3"})
    assert len(rows) == len(users.users)
    with pytest.raises(ValueError, match="at least 3"):
        seed_rows(users, "12", env={"DEMO_PASSWORD_MIN_LENGTH": "1"})
    with pytest.raises(ValueError, match="at least 8"):
        seed_rows(users, "123", env={})
