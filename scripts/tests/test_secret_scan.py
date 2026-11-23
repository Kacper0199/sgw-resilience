"""Fake-key canary for the secret scan (S9): keys are generated at test time, none is committed."""

from __future__ import annotations

import os
import secrets
import shutil
import string
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import SCRIPTS, run_git

from sgw.integrations.signing import new_secret
from sgw.integrations.tokens import new_token

PREFIX = "sk-" + "ant-api03-"
ALPHABET = string.ascii_letters + string.digits + "_-"

ON_WINDOWS = sys.platform == "win32"
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(ON_WINDOWS, reason="bash wrapper"),  # sgw-allow-skip: Windows CI is unit-only
]


def fake_key() -> str:
    return PREFIX + "".join(secrets.choice(ALPHABET) for _ in range(93)) + "AA"


def scanner_available() -> bool:
    if shutil.which("gitleaks"):
        return True
    docker = shutil.which("docker")
    if docker is None:
        return False
    return subprocess.run([docker, "info"], capture_output=True, check=False).returncode == 0  # noqa: S603


@pytest.fixture
def scan_repo(repo: Path) -> Path:
    if not scanner_available():
        pytest.fail(
            "secret scan needs gitleaks or a running Docker; this canary must not be skipped silently"
        )
    shutil.copy(SCRIPTS.parent / ".gitleaks.toml", repo / ".gitleaks.toml")
    return repo


def scan(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPTS / "secret-scan.sh"), *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "NO_COLOR": "1"},
    )


def test_staged_fake_key_is_caught_and_redacted(scan_repo: Path) -> None:
    key = fake_key()
    (scan_repo / "canary.txt").write_text(f'token = "{key}"\n')
    run_git(scan_repo, "add", "canary.txt")
    result = scan(scan_repo, "staged")
    assert result.returncode == 1, result.stdout + result.stderr
    assert key not in result.stdout + result.stderr
    assert "anthropic-key-any" in result.stdout + result.stderr


def test_committed_fake_key_is_caught_in_history(scan_repo: Path) -> None:
    key = fake_key()
    (scan_repo / "notes.md").write_text(f"ANTHROPIC_API_KEY={key}\n")
    run_git(scan_repo, "add", "notes.md")
    run_git(scan_repo, "commit", "-q", "--no-verify", "-m", "canary")
    result = scan(scan_repo, "history")
    assert result.returncode == 1, result.stdout + result.stderr
    assert key not in result.stdout + result.stderr


def test_clean_tree_passes(scan_repo: Path) -> None:
    (scan_repo / "ok.txt").write_text("prefix only: " + PREFIX + "\n")
    run_git(scan_repo, "add", "ok.txt")
    result = scan(scan_repo, "staged")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("rule", "make"),
    [
        ("sgw-integration-token", lambda: new_token().token),
        ("sgw-webhook-secret", new_secret),
    ],
)
def test_staged_integration_credentials_are_caught(scan_repo: Path, rule: str, make) -> None:
    value = make()
    (scan_repo / "consumer.env").write_text(f"SGW_CREDENTIAL={value}\n")
    run_git(scan_repo, "add", "consumer.env")
    result = scan(scan_repo, "staged")
    assert result.returncode == 1, result.stdout + result.stderr
    assert value not in result.stdout + result.stderr
    assert rule in result.stdout + result.stderr
