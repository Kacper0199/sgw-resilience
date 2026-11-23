from __future__ import annotations

import hashlib
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


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def test_bootstrap_writes_one_token_per_service_and_only_digests_to_the_gateway(state: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["bootstrap"])
    assert result.exit_code == 0, result.output
    secrets = state / "var" / "secrets"
    tokens = read_env_file(secrets / "gateway_tokens.env")
    api, worker, cli = (tokens[f"SGW_GATEWAY_TOKEN_{s}"] for s in ("API", "WORKER", "CLI"))
    assert len({api, worker, cli}) == 3 and min(map(len, (api, worker, cli))) >= 40
    for token in (api, worker, cli):
        assert token not in result.output
    app_env = read_env_file(secrets / "app.env")
    assert (app_env["SGW_GATEWAY_TOKEN_API"], app_env["SGW_GATEWAY_TOKEN_WORKER"]) == (api, worker)
    assert "SGW_GATEWAY_TOKEN_CLI" not in app_env
    host_env = read_env_file(secrets / "host.env")
    assert host_env["SGW_GATEWAY_TOKEN_CLI"] == cli and "SGW_GATEWAY_TOKEN_API" not in host_env
    assert app_env["SGW_DATABASE_URL"].startswith("postgresql://sgw_runtime:")
    gateway_env = (secrets / "gateway.env").read_text()
    for token in (api, worker, cli):
        assert token not in gateway_env
    digests = read_env_file(secrets / "gateway.env")["LLM_CALLER_TOKEN_SHA256"]
    assert digests == f"api:{_digest(api)},worker:{_digest(worker)},cli:{_digest(cli)}"
    assert "SGW_LLM_CALL_DSN" in read_env_file(secrets / "gateway.env")
    if os.name != "nt":
        assert (secrets / "gateway_tokens.env").stat().st_mode & 0o777 == 0o600

    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    assert read_env_file(secrets / "gateway_tokens.env") == tokens
    assert runner.invoke(app, ["bootstrap", "--rotate"]).exit_code == 0
    rotated = read_env_file(secrets / "gateway_tokens.env")
    assert rotated["SGW_GATEWAY_TOKEN_API"] != api
    assert read_env_file(secrets / "app.env")["SGW_GATEWAY_TOKEN_API"] == rotated["SGW_GATEWAY_TOKEN_API"]


def test_second_bootstrap_changes_no_file(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key_file = state / "keys.env"
    key_file.write_text("ANTHROPIC_API_KEY=canary-not-a-key\n")
    monkeypatch.setenv("SGW_ENV_FILE", str(key_file))
    runner = CliRunner()
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0

    def snapshot() -> dict[str, bytes]:
        return {
            str(p.relative_to(state)): p.read_bytes()
            for p in sorted((state / "var").rglob("*"))
            if p.is_file()
        }

    first = snapshot()
    monkeypatch.delenv("SGW_ENV_FILE")
    assert runner.invoke(app, ["bootstrap"]).exit_code == 0
    second = snapshot()
    changed = sorted(k for k in set(first) | set(second) if first.get(k) != second.get(k))
    assert changed == [], changed
    assert read_env_file(state / "var" / "compose.env")["SGW_ENV_FILE"] == key_file.as_posix()
