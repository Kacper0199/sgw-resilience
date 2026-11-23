from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from sgw.cli.commands.stack import REQUIRED_COMPOSE_KEYS
from sgw.cli.main import app
from sgw.cli.support import read_env_file
from sgw.integrations.keys import KEY_ENV, decode_key, load_keys

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SGW_STATE_ROOT", str(tmp_path))
    for name in ("SGW_ENV_FILE", "SGW_AUDIT_ACTIVE_KEY", "SGW_AUDIT_DATABASE_URL", KEY_ENV):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def bootstrap() -> None:
    result = CliRunner().invoke(app, ["bootstrap"])
    assert result.exit_code == 0, result.output


def test_bootstrap_generates_one_integration_key_for_containers_and_host(state: Path) -> None:
    bootstrap()
    key_file = state / "var" / "secrets" / "integration.key"
    pinned = read_env_file(state / "var" / "compose.env")[KEY_ENV]
    assert len(pinned) == 64 and len(decode_key(pinned)) == 32
    assert key_file.read_text(encoding="utf-8").strip() == pinned
    assert load_keys(env={}, key_file=key_file) == load_keys(env={KEY_ENV: pinned})
    if os.name != "nt":
        assert key_file.stat().st_mode & 0o777 == 0o600
    bootstrap()
    assert read_env_file(state / "var" / "compose.env")[KEY_ENV] == pinned
    assert KEY_ENV in REQUIRED_COMPOSE_KEYS


def test_compose_runs_the_webhook_worker_with_the_shared_key() -> None:
    services = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]
    worker = services["webhooks"]
    assert worker["command"] == ["python", "-m", "sgw.cli.main", "integrations", "worker"]
    assert worker["command"][:3] == services["audit-checkpoint"]["command"][:3]
    assert worker["image"] == services["api"]["image"]
    assert worker["read_only"] is True and worker["cap_drop"] == ["ALL"]
    assert set(worker["networks"]) == {"app", "egress"}
    assert worker["env_file"][0]["path"].endswith("/app.env")
    for name in ("api", "webhooks"):
        env = services[name]["environment"]
        assert env[KEY_ENV] == "${SGW_INTEGRATION_KEY:-}"
        assert env["SGW_WEBHOOK_ALLOW_HOSTS"] == "${SGW_WEBHOOK_ALLOW_HOSTS:-}"


def test_env_example_lists_integration_settings_without_values() -> None:
    values = read_env_file(ROOT / ".env.example")
    assert {KEY_ENV, "SGW_WEBHOOK_ALLOW_HOSTS", "SGW_WEBHOOK_CA_FILE"} <= set(values)
    assert all(value == "" for value in values.values())
