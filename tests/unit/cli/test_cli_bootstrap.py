from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sgw.cli.main import app
from sgw.cli.support import read_env_file


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SGW_STATE_ROOT", str(tmp_path))
    monkeypatch.delenv("SGW_ENV_FILE", raising=False)
    return tmp_path


def test_bootstrap_never_touches_env_file(state: Path) -> None:
    env_file = state / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=canary-not-a-key\n")
    before = (env_file.read_bytes(), env_file.stat().st_mtime_ns)
    result = CliRunner().invoke(app, ["bootstrap"])
    assert result.exit_code == 0, result.output
    assert (env_file.read_bytes(), env_file.stat().st_mtime_ns) == before
    assert "canary-not-a-key" not in result.output
    for generated in (state / "var").rglob("*"):
        if generated.is_file():
            assert "canary-not-a-key" not in generated.read_text()


def test_bootstrap_writes_private_credentials_once(state: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    secrets = state / "var" / "secrets"
    first = read_env_file(secrets / "postgres.env")
    assert len(first["POSTGRES_PASSWORD"]) >= 40
    assert first["POSTGRES_PASSWORD"] != first["SGW_DB_PASSWORD"]
    app_env = read_env_file(secrets / "app.env")
    assert app_env["SGW_DATABASE_URL"].startswith("postgresql://sgw_runtime:")
    assert app_env["SGW_DB_PASSWORD"] == first["SGW_RUNTIME_PASSWORD"]
    assert len({first["POSTGRES_PASSWORD"], first["SGW_DB_PASSWORD"], first["SGW_RUNTIME_PASSWORD"]}) == 3
    assert first["SGW_DB_PASSWORD"] not in (secrets / "app.env").read_text()
    assert "@postgres:5432/sgw" in app_env["SGW_DATABASE_URL"]
    assert "@127.0.0.1:5434/" in read_env_file(secrets / "host.env")["SGW_DATABASE_URL"]
    compose_env = read_env_file(state / "var" / "compose.env")
    assert compose_env["SGW_SECRETS_DIR"] == secrets.as_posix()
    assert compose_env["SGW_ENV_FILE"] == (state / "var" / "llm.env").as_posix()
    assert compose_env["SGW_VAR_DIR"] == (state / "var").as_posix()
    assert (state / "var" / "llm.env").read_text().startswith("# placeholder")
    assert (state / "var" / "llm").is_dir()
    assert "PASSWORD" not in (state / "var" / "compose.env").read_text()
    if os.name != "nt":
        for path in secrets.iterdir():
            assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
        assert secrets.stat().st_mode & 0o777 == 0o700

    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    assert read_env_file(secrets / "postgres.env") == first

    assert runner.invoke(app, ["bootstrap", "--rotate"]).exit_code == 0
    assert read_env_file(secrets / "postgres.env")["POSTGRES_PASSWORD"] != first["POSTGRES_PASSWORD"]


def test_commands_need_bootstrap_first(state: Path) -> None:
    result = CliRunner().invoke(app, ["migrate", "--dry-run"])
    assert result.exit_code == 1
    assert "sgw bootstrap" in result.output


def test_bootstrap_points_the_gateway_at_a_given_key_file(
    state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_file = state / "elsewhere" / ".env"
    key_file.parent.mkdir()
    key_file.write_text("ANTHROPIC_API_KEY=canary-not-a-key\n")
    before = key_file.stat().st_mtime_ns
    monkeypatch.setenv("SGW_ENV_FILE", str(key_file))
    result = CliRunner().invoke(app, ["bootstrap"])
    assert result.exit_code == 0, result.output
    assert read_env_file(state / "var" / "compose.env")["SGW_ENV_FILE"] == key_file.resolve().as_posix()
    assert key_file.stat().st_mtime_ns == before
    assert "canary-not-a-key" not in result.output


def test_rerun_without_override_keeps_the_stored_key_file(
    state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_file = state / "elsewhere" / ".env"
    key_file.parent.mkdir()
    key_file.write_text("ANTHROPIC_API_KEY=canary-not-a-key\n")
    runner = CliRunner()
    monkeypatch.setenv("SGW_ENV_FILE", str(key_file))
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    monkeypatch.delenv("SGW_ENV_FILE")
    result = runner.invoke(app, ["bootstrap"])
    assert result.exit_code == 0, result.output
    stored = read_env_file(state / "var" / "compose.env")["SGW_ENV_FILE"]
    assert stored == key_file.resolve().as_posix()
    assert "placeholder without a key" not in result.output

    other = state / "other.env"
    other.write_text("")
    monkeypatch.setenv("SGW_ENV_FILE", str(other))
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    assert read_env_file(state / "var" / "compose.env")["SGW_ENV_FILE"] == other.resolve().as_posix()


def test_bootstrap_adds_runtime_password_to_older_credentials(state: Path) -> None:
    secrets = state / "var" / "secrets"
    secrets.mkdir(parents=True)
    old = {"POSTGRES_PASSWORD": "old-super", "SGW_DB_PASSWORD": "old-owner"}
    (secrets / "postgres.env").write_text("".join(f"{k}={v}\n" for k, v in old.items()))
    result = CliRunner().invoke(app, ["bootstrap"])
    assert result.exit_code == 0, result.output
    values = read_env_file(secrets / "postgres.env")
    assert {k: values[k] for k in old} == old
    assert len(values["SGW_RUNTIME_PASSWORD"]) >= 40
    assert read_env_file(secrets / "app.env")["SGW_DB_USER"] == "sgw_runtime"


def test_opa_token_is_generated_once_and_shared_with_api_and_gateway_only(state: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    secrets = state / "var" / "secrets"
    token = read_env_file(secrets / "opa.env")["SGW_OPA_TOKEN"]
    assert len(token) >= 40
    assert read_env_file(secrets / "app.env")["SGW_OPA_TOKEN"] == token
    assert read_env_file(secrets / "gateway.env")["SGW_OPA_TOKEN"] == token
    assert "SGW_OPA_TOKEN" not in read_env_file(secrets / "postgres.env")
    assert "SGW_OPA_TOKEN" not in read_env_file(state / "var" / "compose.env")
    snapshot = {p.name: p.read_bytes() for p in secrets.glob("*.env")}
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    assert {p.name: p.read_bytes() for p in secrets.glob("*.env")} == snapshot
    (secrets / "app.env").unlink()
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    assert read_env_file(secrets / "app.env")["SGW_OPA_TOKEN"] == token


def test_gateway_spend_dir_is_private(state: Path) -> None:
    assert CliRunner().invoke(app, ["bootstrap"]).exit_code == 0
    spend = state / "var" / "llm"
    assert spend.is_dir()
    if os.name != "nt":
        assert spend.stat().st_mode & 0o777 == 0o700


def test_bootstrap_generates_every_key_once(state: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    var = state / "var"
    expected = {
        "secrets/postgres.env",
        "secrets/app.env",
        "secrets/host.env",
        "secrets/gateway.env",
        "secrets/opa.env",
        "secrets/integration.key",
        "secrets/grafana.env",
        "secrets/pg-exporter.env",
        "compose.env",
        "demo.env",
    }
    present = {str(p.relative_to(var)) for p in var.rglob("*") if p.is_file()}
    assert expected <= present
    compose = read_env_file(var / "compose.env")
    assert compose["SGW_INTEGRATION_KEY"] and compose["SGW_AUDIT_ACTIVE_KEY"]
    snapshot = {p: p.read_bytes() for p in var.rglob("*") if p.is_file()}
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    assert {p: p.read_bytes() for p in var.rglob("*") if p.is_file()} == snapshot


def test_demo_password_option_sets_every_persona_and_the_minimum_length(state: Path) -> None:
    from sgw.api.users import seed_rows
    from sgw.contracts.identities import load_users

    runner = CliRunner()
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    demo_env = state / "var" / "demo.env"
    generated = read_env_file(demo_env)
    assert all(len(v) >= 8 for k, v in generated.items() if k.startswith("DEMO_PASSWORD_"))

    result = runner.invoke(app, ["bootstrap", "--demo-password", "123"])
    assert result.exit_code == 0, result.output
    assert "123" not in result.output.replace(str(state), "")
    values = read_env_file(demo_env)
    users = load_users(Path("data/seed/users.yaml"))
    persona_keys = {k for k in values if k.startswith("DEMO_PASSWORD_") and not k.endswith("MIN_LENGTH")}
    assert len(persona_keys) == len(users.users)
    assert {values[k] for k in persona_keys} == {"123"}
    assert int(values["DEMO_PASSWORD_MIN_LENGTH"]) == len("123")
    assert len(seed_rows(users, None, env=values)) == len(users.users)
    if os.name != "nt":
        assert demo_env.stat().st_mode & 0o777 == 0o600

    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    assert read_env_file(demo_env) == values

    long_value = "a-longer-local-demo-value"
    assert runner.invoke(app, ["bootstrap", "--demo-password", long_value]).exit_code == 0
    values = read_env_file(demo_env)
    assert "DEMO_PASSWORD_MIN_LENGTH" not in values
    assert {values[k] for k in persona_keys} == {long_value}


@pytest.mark.parametrize("bad", ["12", " 123"])
def test_demo_password_option_refuses_short_or_padded_values(state: Path, bad: str) -> None:
    result = CliRunner().invoke(app, ["bootstrap", "--demo-password", bad])
    assert result.exit_code != 0
    assert "at least 3 characters" in result.output
    assert not (state / "var").exists()


def test_package_key_file_at_the_root_is_used_without_an_override(state: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    package_file = state / "llm.env"
    package_file.write_text("ANTHROPIC_API_KEY=\n")
    result = runner.invoke(app, ["bootstrap"])
    assert result.exit_code == 0, result.output
    assert read_env_file(state / "var" / "compose.env")["SGW_ENV_FILE"] == package_file.as_posix()
    assert "placeholder without a key" not in result.output
