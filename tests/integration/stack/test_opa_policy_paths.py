"""Every decision path the API and the gateway query is defined in an OPA started exactly as compose starts it
(command, mounts, token), and a policy file added under the mount is picked up without a restart (R27 DR
Blocker 1: Crews "Assign" got 503 because `sgw/dispatch/propose` was undefined in the running OPA)."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
DOCKER = shutil.which("docker")
pytestmark = pytest.mark.skipif(DOCKER is None, reason="no docker")  # sgw-allow-skip: no docker CLI

QUERIED_PATHS = (
    "sgw/approval/propose",
    "sgw/approval/approve",
    "sgw/breakglass/break_glass",
    "sgw/breakglass/cosign",
    "sgw/envelope/assessment",
    "sgw/dispatch/act",
    "sgw/dispatch/propose",
    "sgw/dispatch/sign",
    "sgw/egress/decision",
    "sgw/tiers",
    "sgw/governance",
    "sgw/crew_dispatch",
)


def _free_port() -> int:
    for port in range(63150, 63160):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("no free port in 63150-63159")


@contextmanager
def compose_opa(sources: dict[str, Path] | None = None) -> Iterator[tuple[str, str]]:
    service = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]["opa"]
    token = secrets.token_urlsafe(32)
    port = _free_port()
    name = f"sgw-test-opa-paths-{uuid.uuid4().hex[:8]}"
    mounts: list[str] = []
    for volume in service["volumes"]:
        source, target, mode = volume.split(":")
        host = (sources or {}).get(target) or (ROOT / source).resolve()
        mounts += ["-v", f"{host}:{target}:{mode}"]
    cmd = [DOCKER or "docker", "run", "-d", "--rm", "--name", name, "-p", f"127.0.0.1:{port}:8181"]
    cmd += ["-e", "SGW_OPA_TOKEN", *mounts, service["image"], *service["command"]]
    subprocess.run(cmd, check=True, capture_output=True, env={**os.environ, "SGW_OPA_TOKEN": token})  # noqa: S603
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
        else:
            raise RuntimeError("OPA did not become healthy")
        yield url, token
    finally:
        subprocess.run([DOCKER or "docker", "rm", "-f", name], capture_output=True, check=False)  # noqa: S603


def _query(url: str, token: str, path: str) -> dict[str, object]:
    response = httpx.post(
        f"{url}/v1/data/{path}", json={"input": {}}, headers={"Authorization": f"Bearer {token}"}, timeout=5
    )
    assert response.status_code == 200, (path, response.status_code)
    return dict(response.json())


@pytest.fixture(scope="module")
def opa() -> Iterator[tuple[str, str]]:
    with compose_opa() as server:
        yield server


@pytest.mark.parametrize("path", QUERIED_PATHS)
def test_every_queried_decision_is_defined(opa: tuple[str, str], path: str) -> None:
    url, token = opa
    assert "result" in _query(url, token, path), f"{path} is undefined in the compose-started OPA"


def test_every_policy_package_is_queried() -> None:
    packages = {
        m.group(1).replace(".", "/")
        for rego in (ROOT / "policy").glob("*.rego")
        if not rego.name.endswith("_test.rego")
        for m in [re.search(r"^package (\S+)", rego.read_text(encoding="utf-8"), re.M)]
        if m
    }
    queried = {p.rsplit("/", 1)[0] for p in QUERIED_PATHS}
    assert packages <= queried, f"add the decision paths of {sorted(packages - queried)} to QUERIED_PATHS"


def test_the_clients_query_only_listed_paths() -> None:
    sources = "\n".join(
        p.read_text(encoding="utf-8") for d in ("src/sgw", "services") for p in (ROOT / d).rglob("*.py")
    )
    literal = set(re.findall(r"/v1/data/(sgw/[a-z_]+/[a-z_]+)\"", sources))
    literal |= set(re.findall(r"_query\(\"(sgw/[a-z_]+/[a-z_]+)\"", sources))
    templated = {"sgw/dispatch": ("act", "propose", "sign"), "sgw/approval": ("propose", "approve")}
    for package, rules in templated.items():
        assert f"/v1/data/{package}/{{rule}}" in sources
        literal |= {f"{package}/{r}" for r in rules}
    assert literal <= set(QUERIED_PATHS), sorted(literal - set(QUERIED_PATHS))


def test_a_policy_added_under_the_mount_is_loaded_without_a_restart(tmp_path: Path) -> None:
    policy = tmp_path / "policy"
    shutil.copytree(ROOT / "policy", policy)
    with compose_opa({"/policy": policy}) as (url, token):
        assert "result" not in _query(url, token, "sgw/added_later/answer")
        added = policy / "added_later.rego"
        added.write_text("package sgw.added_later\n\nanswer := 42\n", encoding="utf-8")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and "result" not in _query(url, token, "sgw/added_later/answer"):
            time.sleep(0.5)
        assert _query(url, token, "sgw/added_later/answer").get("result") == 42
