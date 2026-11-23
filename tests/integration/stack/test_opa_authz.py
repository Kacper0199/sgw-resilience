"""H3: the stack's OPA (command and mounts read from compose.yaml) answers decision queries for the token
holder only and refuses every policy or data write, even with the token."""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
DOCKER = shutil.which("docker")
NO_DOCKER = DOCKER is None
pytestmark = pytest.mark.skipif(NO_DOCKER, reason="no docker")  # sgw-allow-skip: no docker CLI


def free_port() -> int:
    for port in range(8340, 8350):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("no free port in 8340-8349")


@pytest.fixture(scope="module")
def opa() -> Iterator[tuple[str, str]]:
    service = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]["opa"]
    token = secrets.token_urlsafe(32)
    port = free_port()
    name = f"sgw-test-opa-{uuid.uuid4().hex[:8]}"
    mounts: list[str] = []
    for volume in service["volumes"]:
        source, target, mode = volume.split(":")
        mounts += ["-v", f"{(ROOT / source).resolve()}:{target}:{mode}"]
    cmd = [
        DOCKER or "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        name,
        "-p",
        f"127.0.0.1:{port}:8181",
        "-e",
        "SGW_OPA_TOKEN",
        *mounts,
        service["image"],
        *service["command"],
    ]
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


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_compose_runs_opa_with_token_authentication_and_basic_authorization() -> None:
    command = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]["opa"]["command"]
    assert "--authentication=token" in command
    assert "--authorization=basic" in command
    assert "/authz/authz.rego" in command


def test_queries_need_the_token(opa: tuple[str, str]) -> None:
    url, token = opa
    tiers = httpx.post(f"{url}/v1/data/sgw/tiers", json={"input": {}}, headers=auth(token))
    assert tiers.status_code == 200
    assert tiers.json().get("result")
    assert httpx.post(f"{url}/v1/data/sgw/tiers", json={"input": {}}).status_code == 401
    assert (
        httpx.post(f"{url}/v1/data/sgw/tiers", json={"input": {}}, headers=auth("x" * 43)).status_code == 401
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/v1/policies/sgw-approval"),
        ("PUT", "/v1/policies/injected"),
        ("DELETE", "/v1/policies/sgw-approval"),
        ("PUT", "/v1/data/sgw/tiers"),
        ("PATCH", "/v1/data/sgw/tiers"),
        ("DELETE", "/v1/data/sgw/tiers"),
        ("GET", "/v1/policies"),
        ("POST", "/v1/data/system/authz/allow"),
    ],
)
def test_writes_and_introspection_are_denied_even_with_the_token(
    opa: tuple[str, str], method: str, path: str
) -> None:
    url, token = opa
    before = httpx.post(f"{url}/v1/data/sgw/tiers", json={"input": {}}, headers=auth(token)).json()
    body = "package injected\nallow := true\n" if "policies" in path else '{"hacked": true}'
    response = httpx.request(method, f"{url}{path}", content=body, headers=auth(token))
    assert response.status_code in (401, 403), (method, path, response.status_code)
    after = httpx.post(f"{url}/v1/data/sgw/tiers", json={"input": {}}, headers=auth(token))
    assert after.status_code == 200
    assert after.json() == before
    injected = httpx.post(f"{url}/v1/data/injected/allow", json={"input": {}}, headers=auth(token))
    assert "result" not in injected.json()


def test_policy_clients_send_the_token_and_cannot_push(
    opa: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sgw.approval.errors import PolicyUnavailableError
    from sgw.approval.policy import OpaPolicy

    url, token = opa
    monkeypatch.setenv("SGW_OPA_TOKEN", token)
    monkeypatch.delenv("SGW_OPA_DEV_LOAD", raising=False)
    client = OpaPolicy(url)
    assert client._client.post("/v1/data/sgw/tiers", json={"input": {}}).status_code == 200
    with pytest.raises(PolicyUnavailableError, match="runtime policy load is disabled"):
        client.load()
    pusher = OpaPolicy(url, allow_load=True)
    with pytest.raises(PolicyUnavailableError, match="401"):
        pusher.load()
