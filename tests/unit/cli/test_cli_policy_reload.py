"""OPA reads `policy/` once at start; a policy merged while the stack runs must still reach it (R27 DR
Blocker 1: `dispatch/propose` was undefined for hours because `sgw up --build` kept the old OPA container)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from sgw.cli.commands import stack

ROOT = Path(__file__).resolve().parents[3]


def _copy(tmp_path: Path) -> Path:
    for directory in stack.POLICY_DIRS:
        shutil.copytree(ROOT / directory, tmp_path / directory)
    return tmp_path


def test_policy_digest_changes_with_any_mounted_policy_or_data_file(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    before = stack.policy_digest(root)
    assert stack.policy_digest(root) == before
    (root / "policy" / "sgw" / "crew_dispatch" / "data.json").write_text("{}", encoding="utf-8")
    after_data = stack.policy_digest(root)
    assert after_data != before
    (root / "policy" / "added.rego").write_text("package sgw.added\n", encoding="utf-8")
    assert stack.policy_digest(root) != after_data
    (root / "infra" / "opa" / "authz.rego").write_text("package system.authz\n", encoding="utf-8")
    assert stack.policy_digest(root) not in {before, after_data}


def test_compose_recreates_and_watches_opa_on_policy_change() -> None:
    service = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]["opa"]
    assert service["labels"]["sgw.policy-digest"] == "${SGW_POLICY_DIGEST:-}"
    assert "--watch" in service["command"]
    mounted = {volume.split(":")[0].removeprefix("./") for volume in service["volumes"]}
    assert mounted == set(stack.POLICY_DIRS)


def test_stack_env_carries_the_policy_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SGW_STATE_ROOT", str(tmp_path))
    assert stack.stack_env(True)["SGW_POLICY_DIGEST"] == stack.policy_digest()
    assert stack.stack_env(False)["SGW_DEMO_MODE"] == "0"


def test_demo_stack_defaults_the_gateway_to_replay_then_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MODE", raising=False)
    assert stack.mode_env(True)["LLM_MODE"] == "replay_then_live"
    assert "LLM_MODE" not in stack.mode_env(False)
    monkeypatch.setenv("LLM_MODE", "replay")
    assert stack.mode_env(True)["LLM_MODE"] == "replay"
