"""Test helpers shared by `tests/unit/gateway` and `tests/security`: an OPA server with `policy/` loaded.

`opa_server()` yields the URL of `SGW_TEST_OPA_URL` (the egress policy is pushed when that server lacks it),
or of a throw-away pinned OPA container on 127.0.0.1:8330-8339 that mounts `policy/` read-only like compose
does, or None when neither is available. The container is removed afterwards.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import httpx

from .egress import DECISION_PATH, REGO_PATH

OPA_IMAGE = (
    "openpolicyagent/opa:1.22.4-static"
    "@sha256:12cecac5a174368f7d3f09d3a19d040ebe0c91d576e520335ae7a985a26e39d3"
)
OPA_ENV = "SGW_TEST_OPA_URL"
OPA_PORTS = range(8330, 8340)
POLICY_ID = "sgw-egress"
PROBE: dict[str, dict[str, list[str]]] = {"input": {"classes": []}}


def _free_port() -> int | None:
    for port in OPA_PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return None


def _decision_defined(url: str) -> bool:
    try:
        r = httpx.post(f"{url}{DECISION_PATH}", json=PROBE, timeout=2.0)
        return r.status_code == 200 and "result" in r.json()
    except (httpx.HTTPError, ValueError):
        return False


def _wait_ready(url: str, timeout_s: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _decision_defined(url):
            return True
        time.sleep(0.2)
    return False


def _ensure_policy(url: str) -> bool:
    if _decision_defined(url):
        return True
    rego = REGO_PATH.read_text(encoding="utf-8")
    r = httpx.put(f"{url}/v1/policies/{POLICY_ID}", content=rego, headers={"Content-Type": "text/plain"})
    return r.status_code == 200 and _decision_defined(url)


def docker_available() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    return subprocess.run([docker, "info"], capture_output=True, check=False).returncode == 0  # noqa: S603


@contextmanager
def opa_server() -> Iterator[str | None]:
    env = os.environ.get(OPA_ENV)
    if env:
        env_url = env.rstrip("/")
        yield env_url if _ensure_policy(env_url) else None
        return
    docker = shutil.which("docker")
    if docker is None or not docker_available():
        yield None
        return
    started: str | None = None
    url: str | None = None
    for _ in range(3):
        port = _free_port()
        if port is None:
            break
        name = f"sgw-wp14a-opa-test-{uuid.uuid4().hex[:8]}"
        cmd = [docker, "run", "-d", "--rm", "--name", name, "-p", f"127.0.0.1:{port}:8181"]
        cmd += ["-v", f"{REGO_PATH.parent}:/policy:ro", OPA_IMAGE]
        cmd += ["run", "--server", "--addr=0.0.0.0:8181", "--disable-telemetry"]
        cmd += ["--ignore=*_test.rego", "/policy"]
        if subprocess.run(cmd, capture_output=True, check=False).returncode == 0:  # noqa: S603
            started, url = name, f"http://127.0.0.1:{port}"
            break
    try:
        yield url if url and _wait_ready(url) else None
    finally:
        if started:
            subprocess.run([docker, "rm", "-f", started], capture_output=True, check=False)  # noqa: S603


def must_run_opa() -> bool:
    """CI (ubuntu runners have Docker) must run the OPA tests: there a missing OPA fails, never skips."""
    return os.environ.get("CI", "").lower() in {"1", "true"}
