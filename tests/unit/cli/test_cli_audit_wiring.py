from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from sgw.cli import audit_setup
from sgw.cli.commands import doctor
from sgw.cli.main import app
from sgw.cli.support import CliError, read_env_file

ROOT = Path(__file__).resolve().parents[3]
NO_DOCKER = shutil.which("docker") is None


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SGW_STATE_ROOT", str(tmp_path))
    for name in (
        "SGW_ENV_FILE",
        "SGW_AUDIT_KEYRING",
        "SGW_AUDIT_KEY_DIR",
        "SGW_AUDIT_ANCHORS_DIR",
        "SGW_AUDIT_ACTIVE_KEY",
        "SGW_AUDIT_DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def bootstrap() -> str:
    result = CliRunner().invoke(app, ["bootstrap"])
    assert result.exit_code == 0, result.output
    return result.output


def active_key(state: Path) -> str:
    return json.loads((state / "var" / "audit" / "keyring.json").read_text())["active"]


def test_bootstrap_creates_one_audit_key_and_keeps_it(state: Path) -> None:
    output = bootstrap()
    key = active_key(state)
    assert f"audit signing key {key} generated" in output
    key_dir = state / "var" / "secrets" / "audit"
    pems = sorted(key_dir.glob("*.pem"))
    assert [p.name for p in pems] == [f"{key.replace(':', '-')}.pem"]
    pem_bytes = pems[0].read_bytes()
    if os.name != "nt":
        assert pems[0].stat().st_mode & 0o777 == 0o600
        assert key_dir.stat().st_mode & 0o777 == 0o700
    assert (state / "var" / "audit" / "anchors").is_dir()

    output = bootstrap()
    assert f"audit signing key {key} kept" in output
    assert active_key(state) == key
    assert sorted(key_dir.glob("*.pem")) == pems
    assert pems[0].read_bytes() == pem_bytes


def test_compose_env_pins_the_key_and_uses_the_runtime_dsn(state: Path) -> None:
    bootstrap()
    values = read_env_file(state / "var" / "compose.env")
    secrets = read_env_file(state / "var" / "secrets" / "postgres.env")
    assert values["SGW_AUDIT_ACTIVE_KEY"] == active_key(state)
    dsn = values["SGW_AUDIT_DATABASE_URL"]
    assert dsn == f"postgresql://sgw_runtime:{secrets['SGW_RUNTIME_PASSWORD']}@postgres:5432/sgw"
    assert secrets["SGW_DB_PASSWORD"] not in dsn
    assert secrets["POSTGRES_PASSWORD"] not in dsn
    if os.name != "nt":
        assert (state / "var" / "compose.env").stat().st_mode & 0o777 == 0o600


def test_bootstrap_keeps_a_key_made_by_sgw_audit_keygen(state: Path) -> None:
    from datetime import UTC, datetime

    from sgw.approval.signer import AuditPaths, generate_key

    keyring, key_dir, anchors = audit_setup.audit_dirs()
    existing = generate_key(AuditPaths(keyring, key_dir, anchors), datetime.now(UTC)).key_id
    bootstrap()
    assert active_key(state) == existing
    assert read_env_file(state / "var" / "compose.env")["SGW_AUDIT_ACTIVE_KEY"] == existing


def test_missing_private_key_is_an_error_not_a_silent_rotation(state: Path) -> None:
    bootstrap()
    key = active_key(state)
    (state / "var" / "secrets" / "audit" / f"{key.replace(':', '-')}.pem").unlink()
    result = CliRunner().invoke(app, ["bootstrap"])
    assert result.exit_code == 1
    assert "is missing" in result.output
    assert active_key(state) == key


def test_doctor_checks_audit_key_and_anchors(state: Path) -> None:
    [finding] = doctor.check_audit()
    assert (finding.check, finding.status) == ("audit key", doctor.FAIL)
    bootstrap()
    findings = {f.check: f for f in doctor.check_audit()}
    assert findings["audit key"].status == doctor.OK
    assert findings["audit anchors"].status == doctor.OK
    assert "audit key pin" not in findings
    if os.name != "nt":
        pem = next((state / "var" / "secrets" / "audit").glob("*.pem"))
        pem.chmod(0o644)
        assert {f.check: f for f in doctor.check_audit()}["audit key"].status == doctor.FAIL


@pytest.mark.parametrize(
    ("platform", "uid", "expected"),
    [
        ("darwin", 501, (10001, 10001)),
        ("win32", 0, (10001, 10001)),
        ("linux", 1000, (1000, 1000)),
        ("linux", 0, (10001, 10001)),
    ],
)
def test_run_ids_follow_the_host(monkeypatch: pytest.MonkeyPatch, platform: str, uid: int, expected) -> None:
    monkeypatch.setattr(audit_setup.sys, "platform", platform)
    monkeypatch.setattr(audit_setup.os, "getuid", lambda: uid, raising=False)
    monkeypatch.setattr(audit_setup.os, "getgid", lambda: uid, raising=False)
    assert audit_setup.run_ids() == expected


def test_up_preflight_names_missing_bootstrap_output(state: Path) -> None:
    result = CliRunner().invoke(app, ["up"])
    assert result.exit_code == 1
    assert "sgw bootstrap" in result.output
    assert "SGW_AUDIT_ACTIVE_KEY" in result.output


def test_compose_audit_checkpoint_service() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    service = compose["services"]["audit-checkpoint"]
    assert service["networks"] == ["app"]
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["command"][-4:] == ["audit", "checkpoint", "--every", "60"]
    assert "healthcheck" in service
    assert service["environment"]["SGW_AUDIT_DATABASE_URL"] == "${SGW_AUDIT_DATABASE_URL:-}"
    assert service["volumes"][1].endswith("/audit:/run/secrets/sgw-audit:ro")
    api = compose["services"]["api"]
    assert api["volumes"][0] == service["volumes"][0] + ":ro"
    assert all(v.endswith(":ro") for v in api["volumes"])
    assert api["environment"]["SGW_AUDIT_ACTIVE_KEY"] == "${SGW_AUDIT_ACTIVE_KEY:-}"
    assert "SGW_AUDIT_DATABASE_URL" not in api["environment"]
    for name in ("api", "audit-checkpoint"):
        assert compose["services"][name]["user"] == "${SGW_RUN_UID:-10001}:${SGW_RUN_GID:-10001}"


@pytest.mark.skipif(NO_DOCKER, reason="no docker CLI")  # sgw-allow-skip: Windows unit runner
def test_compose_config_renders_with_ci_dummy_env_files(tmp_path: Path) -> None:
    secrets = tmp_path / "sgw-secrets"
    secrets.mkdir()
    for name in ("app.env", "postgres.env"):
        (secrets / name).write_text("")
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "SGW_SECRETS_DIR": str(secrets),
        "SGW_ENV_FILE": str(tmp_path / "ci.env"),
    }
    (tmp_path / "ci.env").write_text("")
    result = subprocess.run(  # noqa: S603
        [
            shutil.which("docker") or "docker",
            "compose",
            "-p",
            "sgwci",
            "-f",
            str(ROOT / "compose.yaml"),
            "--profile",
            "core",
            "config",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_audit_setup_rejects_nothing_when_keyring_absent_and_creates_dirs(state: Path) -> None:
    setup = audit_setup.ensure_audit_key()
    assert setup.created and setup.anchors.is_dir()
    assert not audit_setup.ensure_audit_key().created
    with pytest.raises(CliError):
        next(setup.key_dir.glob("*.pem")).unlink()
        audit_setup.ensure_audit_key()
