from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from sgw.cli import demo_goto_role
from sgw.cli.commands import stack
from sgw.cli.main import app
from sgw.cli.support import DB_DEMO_GOTO, load_credentials, read_env_file

ROOT = Path(__file__).resolve().parents[3]
DSN_KEY = "SGW_DEMO_GOTO_DSN"
PASSWORD_KEY = "SGW_DEMO_GOTO_PASSWORD"  # noqa: S105


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SGW_STATE_ROOT", str(tmp_path))
    for name in [
        k for k in os.environ if k.startswith(("DEMO_PASSWORD", "SGW_AUDIT", "SGW_ENV_FILE", DSN_KEY))
    ]:
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def _goto_file(state: Path) -> Path:
    return state / "var" / "secrets" / "demo_goto.env"


def _bootstrap(*args: str) -> str:
    result = CliRunner().invoke(app, ["bootstrap", *args])
    assert result.exit_code == 0, "bootstrap failed"
    return result.output


def _render(statements: list[Any]) -> list[str]:
    return [statement.as_string(None) for statement in statements]


class FakeConn:
    def __init__(self, log: list[Any]) -> None:
        self.log = log

    def __enter__(self) -> FakeConn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, statement: Any) -> None:
        self.log.append(statement)


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    seen: dict[str, list[Any]] = {"dsn": [], "statements": [], "events": []}

    def connect(dsn: str, **kwargs: Any) -> FakeConn:
        seen["dsn"].append(dsn)
        seen["events"].append("connect")
        return FakeConn(seen["statements"])

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(stack, "preflight", lambda: None)
    monkeypatch.setattr(stack, "prepare_database", lambda *a, **k: None)
    monkeypatch.setattr(stack, "compose_cmd", lambda *a, **k: ["docker", "compose", *a])

    def run(cmd: list[str], env: dict[str, str] | None = None, **kwargs: Any) -> None:
        seen["events"].append(("compose", dict(env or {})))

    monkeypatch.setattr(stack, "run", run)
    return seen


def test_bootstrap_writes_a_private_goto_dsn_and_keeps_it(state: Path) -> None:
    output = _bootstrap()
    path = _goto_file(state)
    values = read_env_file(path)
    password = values[PASSWORD_KEY]
    assert len(password) >= 40
    assert values[DSN_KEY] == f"postgresql://{DB_DEMO_GOTO}:{password}@postgres:5432/postgres"
    assert set(values) == {PASSWORD_KEY, DSN_KEY}
    assert "never commit" in path.read_text().splitlines()[0]
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    assert password not in output
    assert "demo_goto.env" in output
    before = path.read_bytes()
    _bootstrap()
    assert path.read_bytes() == before


def test_bootstrap_rotate_replaces_the_goto_password(state: Path) -> None:
    _bootstrap()
    first = read_env_file(_goto_file(state))[PASSWORD_KEY]
    _bootstrap("--rotate")
    values = read_env_file(_goto_file(state))
    assert values[PASSWORD_KEY] != first
    assert values[PASSWORD_KEY] in values[DSN_KEY]


def test_goto_password_stays_out_of_every_other_generated_file(state: Path) -> None:
    _bootstrap()
    password = read_env_file(_goto_file(state))[PASSWORD_KEY]
    others = [p for p in (state / "var").rglob("*") if p.is_file() and p.name != "demo_goto.env"]
    assert others
    leaked = [p.name for p in others if password.encode() in p.read_bytes()]
    assert leaked == []
    assert DSN_KEY not in read_env_file(state / "var" / "secrets" / "app.env")


def test_stack_env_passes_the_goto_dsn_only_in_demo_mode(
    state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap()
    expected = read_env_file(_goto_file(state))[DSN_KEY]
    carried = stack.stack_env(True)[DSN_KEY] == expected
    assert carried
    monkeypatch.setenv(DSN_KEY, "postgresql://stray@elsewhere/postgres")
    assert stack.stack_env(False)[DSN_KEY] == ""
    assert {**os.environ, **stack.stack_env(False)}[DSN_KEY] == ""


def test_stack_env_without_goto_file_passes_an_empty_dsn(state: Path) -> None:
    assert stack.stack_env(True)[DSN_KEY] == ""


def test_enable_statements_grant_only_what_the_database_swap_needs() -> None:
    rendered = _render(demo_goto_role.enable_statements("pa'ss"))
    role = f'"{DB_DEMO_GOTO}"'
    assert rendered[0].startswith("DO $$")
    assert f"CREATE ROLE {role} NOLOGIN" in rendered[0]
    assert rendered[1] == (
        f"ALTER ROLE {role} LOGIN CREATEDB NOSUPERUSER NOCREATEROLE NOREPLICATION NOBYPASSRLS"
        " CONNECTION LIMIT 3 PASSWORD 'pa''ss'"
    )
    assert rendered[2] == f'GRANT "sgw" TO {role} WITH INHERIT TRUE, SET TRUE'
    assert rendered[3] == f'GRANT "pg_signal_backend" TO {role}'
    assert len(rendered) == 4
    assert [s for s in rendered if "pa''ss" in s] == [rendered[1]]


def test_disable_statement_sets_an_existing_role_nologin() -> None:
    rendered = _render(demo_goto_role.disable_statements())
    assert len(rendered) == 1
    assert f"rolname = '{DB_DEMO_GOTO}'" in rendered[0]
    assert f'ALTER ROLE "{DB_DEMO_GOTO}" NOLOGIN' in rendered[0]
    assert "PASSWORD" not in rendered[0]
    assert "CREATE ROLE" not in rendered[0]


def test_compose_passes_the_goto_dsn_to_the_api_only() -> None:
    services = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]
    assert services["api"]["environment"][DSN_KEY] == "${SGW_DEMO_GOTO_DSN:-}"
    others = [
        name for name, svc in services.items() if name != "api" and DSN_KEY in (svc.get("environment") or {})
    ]
    assert others == []


def test_up_demo_enables_the_role_after_compose(state: Path, fake_db: dict[str, list[Any]]) -> None:
    _bootstrap()
    values = read_env_file(_goto_file(state))
    result = CliRunner().invoke(app, ["up", "--demo"])
    assert result.exit_code == 0, "up --demo failed"
    compose, connect = fake_db["events"]
    assert compose[0] == "compose" and connect == "connect"
    carried = compose[1][DSN_KEY] == values[DSN_KEY]
    assert carried
    admin = fake_db["dsn"] == [load_credentials().admin_dsn()]
    assert admin
    expected = _render(demo_goto_role.enable_statements(values[PASSWORD_KEY]))
    executed = _render(fake_db["statements"]) == expected
    assert executed
    assert values[PASSWORD_KEY] not in result.output


def test_up_without_demo_sets_the_role_nologin(state: Path, fake_db: dict[str, list[Any]]) -> None:
    _bootstrap()
    result = CliRunner().invoke(app, ["up"])
    assert result.exit_code == 0, result.output
    compose, _connect = fake_db["events"]
    assert compose[1][DSN_KEY] == ""
    assert _render(fake_db["statements"]) == _render(demo_goto_role.disable_statements())


def test_up_demo_without_goto_file_asks_for_bootstrap(state: Path, fake_db: dict[str, list[Any]]) -> None:
    _bootstrap()
    _goto_file(state).unlink()
    result = CliRunner().invoke(app, ["up", "--demo"])
    assert result.exit_code == 1
    assert "uv run sgw bootstrap" in result.output
    assert fake_db["events"] == []


def test_role_setup_failure_names_only_the_error_type(
    state: Path, fake_db: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap()
    password = read_env_file(_goto_file(state))[PASSWORD_KEY]
    superuser = load_credentials().superuser_password

    def refused(dsn: str, **kwargs: Any) -> FakeConn:
        raise psycopg.OperationalError(f"connection to {dsn} refused")

    monkeypatch.setattr(psycopg, "connect", refused)
    result = CliRunner().invoke(app, ["up", "--demo"])
    assert result.exit_code == 1
    assert "OperationalError" in result.output
    assert DB_DEMO_GOTO in result.output
    assert password not in result.output and superuser not in result.output
    assert "postgresql://" not in result.output
    assert "Traceback" not in result.output


def test_reset_demo_enables_the_role_after_migrations(
    state: Path, fake_db: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sgw.cli.commands import database

    _bootstrap()
    monkeypatch.setattr(database, "apply_migrations", lambda **k: fake_db["events"].append("migrate"))
    monkeypatch.setattr(stack, "retire_anchors", lambda database: [])
    result = CliRunner().invoke(app, ["reset", "--yes", "--demo"])
    assert result.exit_code == 0, "reset --demo failed"
    assert fake_db["events"][-2:] == ["migrate", "connect"]
    password = read_env_file(_goto_file(state))[PASSWORD_KEY]
    assert _render(fake_db["statements"]) == _render(demo_goto_role.enable_statements(password))


def test_up_without_demo_and_without_goto_file_does_not_connect(
    state: Path, fake_db: dict[str, list[Any]]
) -> None:
    _bootstrap()
    _goto_file(state).unlink()
    result = CliRunner().invoke(app, ["up"])
    assert result.exit_code == 0, result.output
    assert len(fake_db["dsn"]) == 0
    assert demo_goto_role.statements_for(False) == []
