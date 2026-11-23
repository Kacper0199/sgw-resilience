from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from sgw.cli.main import app
from sgw.cli.support import read_env_file

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SGW_STATE_ROOT", str(tmp_path))
    monkeypatch.delenv("SGW_ENV_FILE", raising=False)
    return tmp_path


def test_gateway_env_holds_only_the_llm_call_writer_dsn(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key_file = state / "keys.env"
    key_file.write_text("ANTHROPIC_API_KEY=canary-not-a-key\n")
    monkeypatch.setenv("SGW_ENV_FILE", str(key_file))
    assert CliRunner().invoke(app, ["bootstrap"]).exit_code == 0
    secrets = state / "var" / "secrets"
    gateway_env = secrets / "gateway.env"
    values = read_env_file(gateway_env)
    password = read_env_file(secrets / "postgres.env")["SGW_GATEWAY_PASSWORD"]
    opa_token = read_env_file(secrets / "opa.env")["SGW_OPA_TOKEN"]
    assert set(values) == {"SGW_LLM_CALL_DSN", "SGW_OPA_TOKEN", "LLM_CALLER_TOKEN_SHA256"}
    assert values["SGW_LLM_CALL_DSN"] == f"postgresql://sgw_gateway:{password}@postgres:5432/sgw"
    assert values["SGW_OPA_TOKEN"] == opa_token
    tokens = read_env_file(secrets / "gateway_tokens.env").values()
    assert not any(token in gateway_env.read_text() for token in tokens)
    text = gateway_env.read_text()
    assert "canary-not-a-key" not in text
    assert "ANTHROPIC" not in text
    if os.name != "nt":
        assert gateway_env.stat().st_mode & 0o777 == 0o600
    others = {k: read_env_file(secrets / f"{k}.env") for k in ("app", "host", "postgres")}
    assert password not in "".join(others["app"].values())
    assert "@127.0.0.1:5434/sgw" in others["host"]["SGW_GATEWAY_DATABASE_URL"]


def test_bootstrap_adds_gateway_password_and_keeps_existing_ones(state: Path) -> None:
    secrets = state / "var" / "secrets"
    secrets.mkdir(parents=True)
    old = {"POSTGRES_PASSWORD": "a" * 43, "SGW_DB_PASSWORD": "b" * 43, "SGW_RUNTIME_PASSWORD": "c" * 43}
    (secrets / "postgres.env").write_text("".join(f"{k}={v}\n" for k, v in old.items()))
    runner = CliRunner()
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    values = read_env_file(secrets / "postgres.env")
    assert {k: values[k] for k in old} == old
    gateway = values["SGW_GATEWAY_PASSWORD"]
    assert len(gateway) >= 40 and gateway not in old.values()

    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    assert read_env_file(secrets / "postgres.env")["SGW_GATEWAY_PASSWORD"] == gateway

    (secrets / "gateway.env").unlink()
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    assert gateway in read_env_file(secrets / "gateway.env")["SGW_LLM_CALL_DSN"]
    assert read_env_file(secrets / "postgres.env") == values


def test_compose_gateway_waits_for_postgres_and_keeps_both_networks() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    services = compose["services"]
    gateway = services["llm-gateway"]
    assert gateway["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert gateway["depends_on"]["opa"]["condition"] == "service_healthy"
    assert {"app", "egress"} <= set(gateway["networks"])
    assert "app" in services["postgres"]["networks"]
    assert "egress" not in services["postgres"]["networks"]
    assert compose["networks"]["app"]["internal"] is True
    env_files = [entry["path"] for entry in gateway["env_file"]]
    assert env_files[0].startswith("${SGW_ENV_FILE")
    assert env_files[1].endswith("/gateway.env")
    for name in ("api", "worker"):
        assert not any("gateway.env" in entry["path"] for entry in services[name]["env_file"])


def test_init_script_creates_the_gateway_login_in_the_writer_role() -> None:
    script = (ROOT / "docker" / "postgres" / "initdb" / "100_sgw_roles.sh").read_text()
    assert "CREATE ROLE sgw_llm_writer NOLOGIN;" in script
    assert "CREATE ROLE sgw_gateway LOGIN CONNECTION LIMIT 5 IN ROLE sgw_llm_writer" in script
    assert "SGW_GATEWAY_PASSWORD:?" in script
    assert "sgw_gateway" in script.split("GRANT CONNECT ON DATABASE sgw TO", 1)[1]
