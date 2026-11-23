"""Golden-path API harness: a seeded scratch database, an OPA, a replay-only LLM gateway, the API as a uvicorn
subprocess (restartable with other env, e.g. `FAULT_LLM_DOWN=1`), the example webhook consumer, and an HTTP
session per persona that speaks the cookie + CSRF protocol and reads K4 run frames from SSE.

Ports are OS-assigned (bind to 0). Nothing reads `.env` or prints credentials."""

from __future__ import annotations

import json
import os
import secrets
import socket
import ssl
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[2]
CONSUMER = REPO / "examples" / "webhook-consumer" / "consumer.py"
GATEWAY_ENV = "GOLDEN_GATEWAY_URL"
"""A running gateway instead of the kit's replay one; to re-record the golden path on a record gateway, also
set GOLDEN_GATEWAY_TOKEN (an api caller token it accepts) and GOLDEN_LLM_PURPOSE / GOLDEN_LLM_WAVE."""
END_FRAMES = ("run_paused", "run_end", "run_error")


def free_port() -> int:
    """A port the OS assigns, so concurrent guard runs (several worktrees) never collide."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def require_free(port: int) -> None:
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"port {port} is in use (another golden-path run?)")


def wait_ok(url: str, timeout_s: float = 40, verify: ssl.SSLContext | bool = True) -> None:
    deadline = time.monotonic() + timeout_s
    last = "no answer"
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=2, verify=verify)
            if r.status_code == 200:
                return
            last = f"HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            last = type(exc).__name__
        time.sleep(0.2)
    raise RuntimeError(f"{url} not ready: {last}")


def tail(path: Path, lines: int = 40) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"


# ---- seed -------------------------------------------------------------------------------------------------


def seed_world(admin_url: str, password: str) -> None:
    """`sgw seed --demo` on the scratch database: users, reference rows, Helene replay, PS-17 queue at N, ETR
    publication, corpus index."""
    from sgw.approval.demo_seed import seed_demo

    report = seed_demo(admin_url, password)
    assert report.cases == 5 and report.ledger_head > 0 and report.regions > 0 and report.assets > 0, report


# ---- processes --------------------------------------------------------------------------------------------


def _clean_env() -> dict[str, str]:
    drop = ("SGW_", "FAULT_", "LLM_", "DEMO_", "ANTHROPIC_")
    return {k: v for k, v in os.environ.items() if not k.startswith(drop)}


@dataclass
class Stack:
    runtime_url: str
    admin_url: str
    opa_url: str
    password: str
    workdir: Path
    integration_key: str = field(default_factory=lambda: secrets.token_hex(32))
    procs: dict[str, subprocess.Popen[bytes]] = field(default_factory=dict)
    api_port: int = field(default_factory=free_port)
    gateway_port: int = field(default_factory=free_port)
    consumer_port: int = field(default_factory=free_port)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def hook_host(self) -> str:
        return f"127.0.0.1:{self.consumer_port}"

    @property
    def hook_url(self) -> str:
        return f"https://{self.hook_host}/hooks/sgw"

    def _spawn(self, name: str, cmd: list[str], env: Mapping[str, str]) -> subprocess.Popen[bytes]:
        log = (self.workdir / f"{name}.log").open("ab")
        proc = subprocess.Popen(cmd, env=dict(env), stdout=log, stderr=subprocess.STDOUT, cwd=REPO)  # noqa: S603
        self.procs[name] = proc
        return proc

    @property
    def gateway_url(self) -> str:
        return os.environ.get(GATEWAY_ENV) or f"http://127.0.0.1:{self.gateway_port}"

    def start_gateway(self) -> None:
        if os.environ.get(GATEWAY_ENV):
            wait_ok(f"{self.gateway_url}/healthz")
            return
        require_free(self.gateway_port)
        env = {
            **_clean_env(),
            "LLM_MODE": "replay",
            "LLM_EGRESS_PDP": "reference",
            "LLM_ACCEPT_TEST_TOKENS": "1",
            "LLM_SPEND_CSV": str(self.workdir / "llm_spend.csv"),
        }
        cmd = [
            sys.executable,
            "-m",
            "sgw.cli.main",
            "gateway",
            "--mode",
            "replay",
            "--port",
            str(self.gateway_port),
        ]
        self._spawn("gateway", cmd, env)
        try:
            wait_ok(f"http://127.0.0.1:{self.gateway_port}/healthz")
        except RuntimeError as exc:
            raise RuntimeError(f"{exc}\n{tail(self.workdir / 'gateway.log')}") from None

    def api_env(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        gateway = self.gateway_url
        return {
            **_clean_env(),
            "SGW_DATABASE_URL": self.runtime_url,
            "SGW_SCENARIO": "helene",
            "DEMO_MODE": "1",
            "SGW_GATEWAY_URL": gateway,
            "SGW_GATEWAY_TOKEN": os.environ.get("GOLDEN_GATEWAY_TOKEN") or "sgw-test-caller-api",
            "SGW_OPS_GATEWAY_URL": gateway,
            "SGW_OPA_URL": self.opa_url,
            "SGW_OPS_OPA_URL": self.opa_url,
            "SGW_OPS_RECONCILE_S": "1",
            "SGW_SCENARIO_JOBS_S": "2",
            "SGW_ZONE_RULES": "1",
            "SGW_LLM_WAVE": os.environ.get("GOLDEN_LLM_WAVE") or "W6",
            "SGW_LLM_PURPOSE": os.environ.get("GOLDEN_LLM_PURPOSE") or "test",
            "SGW_LOGIN_IP_BURST": "1000",
            "SGW_LOGIN_USER_BURST": "200",
            "SGW_INTEGRATION_KEY": self.integration_key,
            "SGW_WEBHOOK_ALLOW_HOSTS": self.hook_host,
            "SGW_AUDIT_KEYRING": str(self.workdir / "audit" / "keyring.json"),
            "SGW_AUDIT_KEY_DIR": str(self.workdir / "audit" / "keys"),
            "SGW_AUDIT_ANCHORS_DIR": str(self.workdir / "audit" / "anchors"),
            **(extra or {}),
        }

    def start_api(self, extra: Mapping[str, str] | None = None) -> None:
        require_free(self.api_port)
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

    def restart_api(self, extra: Mapping[str, str] | None = None) -> None:
        self.stop("api")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", self.api_port)) != 0:
                    break
            time.sleep(0.1)
        self.start_api(extra)

    def start_consumer(self, secret: str, ca: Path, cert: Path, key: Path, out: Path) -> None:
        require_free(self.consumer_port)
        env = {**_clean_env(), "SGW_WEBHOOK_SECRETS": secret}
        cmd = [sys.executable, str(CONSUMER), "--cert", str(cert), "--key", str(key)]
        cmd += ["--port", str(self.consumer_port), "--out", str(out)]
        self._spawn("consumer", cmd, env)
        wait_ok(f"https://{self.hook_host}/healthz", verify=ssl.create_default_context(cafile=str(ca)))

    def close(self) -> None:
        for name in list(self.procs):
            self.stop(name)


# ---- HTTP as a persona ------------------------------------------------------------------------------------


class Persona:
    """A browser-like session: login cookie, double-submit CSRF header on writes, same-origin header."""

    def __init__(self, base: str, user_id: str, password: str) -> None:
        self.user_id = user_id
        self.c = httpx.Client(base_url=base, timeout=60, headers={"Origin": base})
        r = self.c.post("/api/auth/login", json={"user_id": user_id, "password": password})
        assert r.status_code == 200, f"login {user_id}: {r.status_code} {r.text[:200]}"

    def _csrf(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        return {"X-CSRF-Token": self.c.cookies.get("sgw_csrf") or "", **(extra or {})}

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return self.c.get(path, **kw)

    def post(self, path: str, body: Any = None, headers: Mapping[str, str] | None = None) -> httpx.Response:
        return self.c.post(path, json=body, headers=self._csrf(headers))

    def seek(self, at: str) -> dict[str, Any]:
        r = self.post("/api/scenario", {"action": "seek", "scenario_time": at})
        assert r.status_code == 200, r.text
        return dict(r.json())

    def frames(
        self, thread_id: str, after_seq: int = -1, until: tuple[str, ...] = END_FRAMES
    ) -> list[dict[str, Any]]:
        """K4 frames of the thread's live run with seq > after_seq, up to the first `until` frame."""
        out: list[dict[str, Any]] = []
        with self.c.stream("GET", f"/api/threads/{thread_id}/events", timeout=180) as r:
            assert r.status_code == 200, r.read()
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                frame = json.loads(line[5:])
                if frame["seq"] <= after_seq:
                    continue
                out.append(frame)
                if frame["type"] in until:
                    return out
        return out

    def run(self, graph: str, run_input: dict[str, Any], module: str) -> Run:
        t = self.post("/api/threads", {"module": module})
        assert t.status_code == 201, t.text
        thread_id = t.json()["thread_id"]
        r = self.post(f"/api/threads/{thread_id}/runs", {"graph": graph, "input": run_input})
        assert r.status_code == 202, r.text
        run = Run(thread_id=thread_id, run_id=r.json()["run_id"])
        run.frames = self.frames(thread_id)
        return run

    def resume(self, run: Run) -> list[dict[str, Any]]:
        last = max((f["seq"] for f in run.frames), default=-1)
        r = self.post(f"/api/runs/{run.run_id}/resume", {})
        assert r.status_code == 202, r.text
        new = self.frames(run.thread_id, after_seq=last)
        run.frames += new
        return new

    def card(self, proposal_id: str) -> httpx.Response:
        r = self.get(f"/api/proposals/{proposal_id}")
        assert r.status_code == 200, r.text
        return r

    def decide(self, proposal_id: str, decision: str = "approve") -> httpx.Response:
        card = self.card(proposal_id)
        c = card.json()
        body = {
            "decision": decision,
            "proposal_version": c["proposal_version"],
            "action_hash": c["action_hash"],
        }
        return self.post(
            f"/api/proposals/{proposal_id}/approvals",
            body,
            headers={"If-Match": card.headers.get("etag", "")},
        )


@dataclass
class Run:
    thread_id: str
    run_id: str
    frames: list[dict[str, Any]] = field(default_factory=list)

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [f.get("payload") or {} for f in self.frames if f["type"] == kind]

    def artifacts(self, kind: str) -> list[dict[str, Any]]:
        return [p for p in self.of("artifact") if p.get("kind") == kind]

    @property
    def last(self) -> dict[str, Any]:
        return self.frames[-1]


@contextmanager
def opa() -> Iterator[str | None]:
    from sgw.approval.testkit import opa_server

    with opa_server() as url:
        if url is not None:
            from sgw.approval.breakglass_policy import OpaGovernance
            from sgw.approval.policy import OpaPolicy

            for client in (OpaPolicy(url, allow_load=True), OpaGovernance(url, allow_load=True)):
                client.load()
                client.close()
        yield url
