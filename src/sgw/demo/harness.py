"""A private demo stack on the host for the story driver: a replay-only LLM gateway (test caller token, no
key, no live call), a policy-loaded OPA and the API (DEMO_MODE=1, audit signing off) as uvicorn
subprocesses against one database. Ports are OS-assigned. Nothing reads `.env` or prints credentials."""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[3]
CALLER_TOKEN = "sgw-test-caller-api"  # noqa: S105 - the gateway's test caller name, accepted only with LLM_ACCEPT_TEST_TOKENS
DROP_PREFIXES = ("SGW_", "FAULT_", "LLM_", "DEMO_", "ANTHROPIC_")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def port_open(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_ok(url: str, timeout_s: float = 60) -> None:
    deadline = time.monotonic() + timeout_s
    last = "no answer"
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=2)
            if r.status_code == 200:
                return
            last = f"HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            last = type(exc).__name__
        time.sleep(0.2)
    raise RuntimeError(f"{url} not ready: {last}")


def tail(path: Path, lines: int = 30) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"


def clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith(DROP_PREFIXES)}


@dataclass
class DemoStack:
    runtime_url: str
    opa_url: str
    workdir: Path
    gateway_url_override: str | None = None
    procs: dict[str, subprocess.Popen[bytes]] = field(default_factory=dict)
    api_port: int = field(default_factory=free_port)
    gateway_port: int = field(default_factory=free_port)
    integration_key: str = field(default_factory=lambda: secrets.token_hex(32))

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def gateway_url(self) -> str:
        return self.gateway_url_override or f"http://127.0.0.1:{self.gateway_port}"

    def _spawn(self, name: str, cmd: list[str], env: Mapping[str, str]) -> None:
        log = (self.workdir / f"{name}.log").open("ab")
        self.procs[name] = subprocess.Popen(  # noqa: S603
            cmd, env=dict(env), stdout=log, stderr=subprocess.STDOUT, cwd=REPO
        )

    def start_gateway(self) -> None:
        if self.gateway_url_override:
            return
        env = {
            **clean_env(),
            "LLM_MODE": "replay",
            "LLM_EGRESS_PDP": "reference",
            "LLM_ACCEPT_TEST_TOKENS": "1",
            "LLM_SPEND_CSV": str(self.workdir / "llm_spend.csv"),
        }
        cmd = [sys.executable, "-m", "sgw.cli.main", "gateway", "--mode", "replay"]
        self._spawn("gateway", [*cmd, "--port", str(self.gateway_port)], env)
        try:
            wait_ok(f"{self.gateway_url}/healthz")
        except RuntimeError as exc:
            raise RuntimeError(f"{exc}\n{tail(self.workdir / 'gateway.log')}") from None

    def gateway_counters(self) -> dict[str, int]:
        r = httpx.get(f"{self.gateway_url}/healthz", timeout=5)
        r.raise_for_status()
        return {k: int(v) for k, v in dict(r.json().get("counters") or {}).items()}

    def api_env(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        audit = self.workdir / "audit"
        return {
            **clean_env(),
            "SGW_DATABASE_URL": self.runtime_url,
            "SGW_SCENARIO": "helene",
            "DEMO_MODE": "1",
            "SGW_GATEWAY_URL": self.gateway_url,
            "SGW_GATEWAY_TOKEN": CALLER_TOKEN,
            "SGW_OPS_GATEWAY_URL": self.gateway_url,
            "SGW_OPA_URL": self.opa_url,
            "SGW_OPS_OPA_URL": self.opa_url,
            "SGW_OPS_RECONCILE_S": "1",
            "SGW_SCENARIO_JOBS_S": "2",
            "SGW_ZONE_RULES": "1",
            "SGW_LLM_WAVE": "W7",
            "SGW_LLM_PURPOSE": "test",
            "SGW_LOGIN_IP_BURST": "1000",
            "SGW_LOGIN_USER_BURST": "200",
            "SGW_INTEGRATION_KEY": self.integration_key,
            "SGW_AUDIT_SIGNING": "0",
            "SGW_AUDIT_KEYRING": str(audit / "keyring.json"),
            "SGW_AUDIT_KEY_DIR": str(audit / "keys"),
            "SGW_AUDIT_ANCHORS_DIR": str(audit / "anchors"),
            **(extra or {}),
        }

    def start_api(self, extra: Mapping[str, str] | None = None) -> None:
        if port_open(self.api_port):
            raise RuntimeError(f"port {self.api_port} is in use")
        cmd = [sys.executable, "-m", "uvicorn", "sgw.api.app:create_app", "--factory", "--host", "127.0.0.1"]
        cmd += ["--port", str(self.api_port), "--no-server-header", "--log-level", "warning"]
        self._spawn("api", cmd, self.api_env(extra))
        try:
            wait_ok(f"{self.base}/readyz")
        except RuntimeError as exc:
            raise RuntimeError(f"{exc}\n{tail(self.workdir / 'api.log')}") from None

    def stop(self, name: str) -> None:
        proc = self.procs.pop(name, None)
        if proc is None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        port = self.api_port if name == "api" else self.gateway_port
        deadline = time.monotonic() + 10
        while port_open(port) and time.monotonic() < deadline:
            time.sleep(0.1)

    def restart_api(self, extra: Mapping[str, str] | None = None) -> None:
        self.stop("api")
        self.start_api(extra)

    def close(self) -> None:
        for name in list(self.procs):
            self.stop(name)


@contextmanager
def policy_opa() -> Iterator[str]:
    """`SGW_TEST_OPA_URL`, or a throwaway OPA container, with the approval and governance policies loaded."""
    from sgw.approval.breakglass_policy import OpaGovernance
    from sgw.approval.policy import OpaPolicy
    from sgw.approval.testkit import opa_server

    with opa_server() as url:
        if url is None:
            raise RuntimeError("no OPA: set SGW_TEST_OPA_URL or start Docker")
        clients: list[Any] = [OpaPolicy(url, allow_load=True), OpaGovernance(url, allow_load=True)]
        for client in clients:
            client.load()
            client.close()
        yield url
