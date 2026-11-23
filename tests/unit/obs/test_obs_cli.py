from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sgw.cli.commands import obs
from sgw.cli.main import app
from sgw.cli.support import read_env_file


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SGW_STATE_ROOT", str(tmp_path))
    monkeypatch.delenv("SGW_ENV_FILE", raising=False)
    return tmp_path


def test_obs_secrets_are_private_kept_and_rotated(state: Path) -> None:
    first = obs.write_obs_secrets()
    assert first.created
    grafana = read_env_file(obs.grafana_env_path())
    exporter = read_env_file(obs.exporter_env_path())
    assert grafana["GF_SECURITY_ADMIN_USER"] == "sgw-admin"
    assert len(grafana["GF_SECURITY_ADMIN_PASSWORD"]) >= 40
    assert exporter["DATA_SOURCE_NAME"].startswith("postgresql://sgw_monitor:")
    assert exporter["DATA_SOURCE_NAME"].endswith("@postgres:5432/sgw?sslmode=disable")
    assert grafana["GF_SECURITY_ADMIN_PASSWORD"] not in obs.exporter_env_path().read_text()
    if os.name != "nt":
        assert obs.grafana_env_path().stat().st_mode & 0o777 == 0o600
        assert obs.exporter_env_path().stat().st_mode & 0o777 == 0o600
    again = obs.write_obs_secrets()
    assert not again.created and again.grafana_password == first.grafana_password
    rotated = obs.write_obs_secrets(rotate=True)
    assert rotated.created and rotated.monitor_password != first.monitor_password


def test_monitor_role_is_statistics_only() -> None:
    statements = obs.monitor_role_statements("pw'x")
    joined = "\n".join(statements)
    assert 'GRANT pg_monitor TO "sgw_monitor"' in joined
    assert "NOSUPERUSER" in joined and "CONNECTION LIMIT 3" in joined
    assert "'pw''x'" in joined
    assert "sgw_app" not in joined and "sgw_readonly" not in joined


def test_obs_commands_are_discovered_and_never_print_secrets(
    state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(obs, "ensure_monitor_role", lambda password: None)
    result = CliRunner().invoke(app, ["obs", "init"])
    assert result.exit_code == 0, result.output
    secrets = obs.write_obs_secrets()
    assert secrets.grafana_password not in result.output
    assert secrets.monitor_password not in result.output


def test_obs_down_touches_only_obs_services(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(obs, "compose_cmd", lambda *args, profile: [profile, *args])
    monkeypatch.setattr(obs, "run", lambda cmd, **kw: calls.append(list(cmd)))
    assert CliRunner().invoke(app, ["obs", "down"]).exit_code == 0
    assert calls == [["obs", "rm", "--stop", "--force", *obs.SERVICES]]


def test_obs_up_uses_no_deps_so_core_is_never_recreated(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(obs, "ensure_monitor_role", lambda password: None)
    monkeypatch.setattr(obs, "compose_cmd", lambda *args, profile: [profile, *args])
    monkeypatch.setattr(obs, "run", lambda cmd, **kw: calls.append(list(cmd)))
    assert CliRunner().invoke(app, ["obs", "up"]).exit_code == 0
    (cmd,) = calls
    assert "--no-deps" in cmd and "--remove-orphans" not in cmd and "--build" not in cmd
    assert cmd[-4:] == list(obs.SERVICES)


def test_stack_up_with_obs_profile_prepares_secrets_and_role(
    state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sgw.cli.commands import stack

    events: list[str] = []
    monkeypatch.setattr(stack, "preflight", lambda: None)
    monkeypatch.setattr(stack, "prepare_database", lambda *a, **k: None)
    monkeypatch.setattr(stack, "compose_cmd", lambda *args, profile: [profile, *args])
    monkeypatch.setattr(stack, "run", lambda cmd, **kw: events.append(f"compose:{cmd[0]}"))
    monkeypatch.setattr(obs, "ensure_monitor_role", lambda password: events.append("role"))
    assert CliRunner().invoke(app, ["up", "--profile", "obs"]).exit_code == 0
    assert events == ["compose:obs", "role"]
    assert obs.grafana_env_path().is_file() and obs.exporter_env_path().is_file()
    events.clear()
    assert CliRunner().invoke(app, ["up"]).exit_code == 0
    assert events == ["compose:core"]
