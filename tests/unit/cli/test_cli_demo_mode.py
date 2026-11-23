from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from sgw.cli.main import app
from sgw.cli.support import read_env_file
from sgw.contracts.identities import demo_password_for, load_users, password_env_for

ROOT = Path(__file__).resolve().parents[3]
USERS = load_users(ROOT / "data" / "seed" / "users.yaml")


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SGW_STATE_ROOT", str(tmp_path))
    for name in [k for k in os.environ if k.startswith(("DEMO_PASSWORD", "SGW_AUDIT", "SGW_ENV_FILE"))]:
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_bootstrap_writes_one_password_per_persona_and_keeps_them(state: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["bootstrap"])
    assert result.exit_code == 0, result.output
    demo = state / "var" / "demo.env"
    values = read_env_file(demo)
    expected = {password_env_for(u.user_id) for u in USERS.users}
    assert set(values) == expected
    assert len(set(values.values())) == len(expected)
    assert all(len(v) >= 40 for v in values.values())
    assert not any(v in result.output for v in values.values())
    if os.name != "nt":
        assert demo.stat().st_mode & 0o777 == 0o600
    before = demo.read_bytes()
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    assert demo.read_bytes() == before


def test_bootstrap_keeps_a_legacy_shared_password_and_existing_personas(state: Path) -> None:
    demo = state / "var" / "demo.env"
    demo.parent.mkdir(parents=True)
    first = USERS.users[0].user_id
    demo.write_text(f"DEMO_PASSWORD=legacy-shared-pass\n{password_env_for(first)}=kept-persona-pass\n")
    assert CliRunner().invoke(app, ["bootstrap"]).exit_code == 0
    values = read_env_file(demo)
    assert values["DEMO_PASSWORD"] == "legacy-shared-pass"  # noqa: S105
    assert values[password_env_for(first)] == "kept-persona-pass"  # noqa: S105
    assert len(values) == len(USERS.users) + 1


def test_password_lookup_prefers_the_persona() -> None:
    env = {"DEMO_PASSWORD": "shared-pass-123", password_env_for("ic_01"): "ic-own-pass-123"}
    assert demo_password_for("ic_01", env) == "ic-own-pass-123"
    assert demo_password_for("ops_dm_01", env) == "shared-pass-123"
    assert demo_password_for("ops_dm_01", {}) is None
    assert password_env_for("ops_dm_01") == "DEMO_PASSWORD_OPS_DM_01"


def test_api_seed_rows_hash_each_persona_password() -> None:
    from sgw.api.security import verify_password
    from sgw.api.users import seed_rows

    env = {password_env_for(u.user_id): f"own-{u.user_id}-pass" for u in USERS.users}
    rows = {r["user_id"]: r["password_hash"] for r in seed_rows(USERS, None, env)}
    for user in USERS.users:
        assert verify_password(rows[user.user_id], f"own-{user.user_id}-pass")
        other = USERS.users[1] if user is USERS.users[0] else USERS.users[0]
        assert not verify_password(rows[user.user_id], f"own-{other.user_id}-pass")
    with pytest.raises(ValueError, match="at least 8 characters"):
        seed_rows(USERS, None, {})


def test_approval_seed_users_hash_each_persona_password() -> None:
    from argon2 import PasswordHasher

    from sgw.approval.seed import seed_users

    captured: list[tuple[Any, ...]] = []

    class FakeConn:
        def execute(self, _sql: str, params: tuple[Any, ...]) -> None:
            captured.append(params)

    env = {password_env_for(u.user_id): f"own-{u.user_id}-pass" for u in USERS.users}
    seed_users(FakeConn(), USERS, None, env=env)  # type: ignore[arg-type]
    hasher = PasswordHasher()
    for params in captured:
        assert hasher.verify(params[-1], f"own-{params[0]}-pass")


def test_compose_defaults_to_demo_mode_off_with_secure_cookies() -> None:
    api = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]["api"]
    assert api["environment"]["DEMO_MODE"] == "${SGW_DEMO_MODE:-0}"
    assert api["environment"]["SGW_COOKIE_SECURE"] == "${SGW_COOKIE_SECURE:-1}"


def test_up_demo_flag_sets_demo_mode_for_compose(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sgw.cli import demo_goto_role
    from sgw.cli.commands import stack

    calls: list[dict[str, str] | None] = []
    monkeypatch.delenv("LLM_MODE", raising=False)
    monkeypatch.delenv("LLM_REPLAY_PACE_MAX_S", raising=False)
    monkeypatch.setattr(stack, "preflight", lambda: None)
    monkeypatch.setattr(stack, "prepare_database", lambda *a, **k: None)
    monkeypatch.setattr(stack, "compose_cmd", lambda *a, **k: ["docker", "compose", *a])
    monkeypatch.setattr(stack, "run", lambda cmd, env=None, **k: calls.append(env))
    monkeypatch.setattr(demo_goto_role, "apply", lambda statements: None)
    runner = CliRunner()
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    assert runner.invoke(app, ["up", "--demo"]).exit_code == 0
    assert runner.invoke(app, ["up"]).exit_code == 0
    digest = stack.policy_digest()
    goto_dsn = read_env_file(state / "var" / "secrets" / "demo_goto.env")["SGW_DEMO_GOTO_DSN"]
    expected = [
        {
            "SGW_DEMO_MODE": "1",
            "SGW_COOKIE_SECURE": "0",
            "LLM_MODE": "replay_then_live",
            "LLM_REPLAY_PACE_MAX_S": "12",
            "SGW_POLICY_DIGEST": digest,
            "SGW_DEMO_GOTO_DSN": goto_dsn,
        },
        {"SGW_DEMO_MODE": "0", "SGW_POLICY_DIGEST": digest, "SGW_DEMO_GOTO_DSN": ""},
    ]
    matched = calls == expected
    assert matched


def test_up_starts_postgres_and_migrates_before_the_services(
    state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sgw.cli import demo_goto_role
    from sgw.cli.commands import database, stack

    events: list[object] = []
    monkeypatch.setattr(stack, "preflight", lambda: None)
    monkeypatch.setattr(stack, "compose_cmd", lambda *a, **k: list(a))
    monkeypatch.setattr(stack, "run", lambda cmd, env=None, **k: events.append(tuple(cmd)))
    monkeypatch.setattr(database, "apply_migrations", lambda **k: events.append("migrate") or [])
    monkeypatch.setattr(demo_goto_role, "apply", lambda statements: None)
    runner = CliRunner()
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    assert runner.invoke(app, ["up"]).exit_code == 0
    assert events[0][-2:] == ("postgres", "pg-port")
    assert events[1] == "migrate"
    assert "--remove-orphans" in events[2]
