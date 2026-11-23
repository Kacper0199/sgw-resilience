"""Integration helpers: scratch database, uvicorn subprocess, Caddy container, SSE reader."""

from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
from psycopg.types.json import Jsonb

from sgw.contracts.events import EVENT_MODELS
from sgw.contracts.wire import SseId, WireFrame

REPO_ROOT = Path(__file__).resolve().parents[3]
CADDYFILE = REPO_ROOT / "infra" / "caddy" / "Caddyfile"
CADDY_IMAGE = "caddy:2.11-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0"
DB_ENV = "SGW_TEST_DATABASE_URL"
API_PORT_BASE = 8201
CADDY_PORT_BASE = 8210
MAX_WORKERS = 5


def worker_index() -> int:
    """pytest-xdist worker number (0 without xdist). Every worker runs its own database, API and Caddy, so
    each needs its own ports: sharing 8210 let one worker's tests reach another worker's API (wrong seeded
    password -> 401 in CI)."""
    raw = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    index = int(raw[2:]) if raw.startswith("gw") and raw[2:].isdigit() else 0
    if index >= MAX_WORKERS:
        raise RuntimeError(f"WP-08 ports 8200-8219 support {MAX_WORKERS} xdist workers, got {raw}")
    return index


@dataclass(frozen=True)
class CaddyPorts:
    name: str
    site: int
    relay: int

    @property
    def site_url(self) -> str:
        return f"http://127.0.0.1:{self.site}"

    def port(self, proxy: str) -> int:
        return {"site-8080": self.site, "relay-8000": self.relay}[proxy]


def worker_ports() -> tuple[int, int, int]:
    """Three free ports chosen by the OS, so parallel runs from several worktrees never collide."""
    sockets = [socket.socket() for _ in range(3)]
    try:
        for s in sockets:
            s.bind(("127.0.0.1", 0))
        api, site, relay = (s.getsockname()[1] for s in sockets)
    finally:
        for s in sockets:
            s.close()
    return api, site, relay


def require_free(port: int) -> None:
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"port {port} is already in use (another test run or a stale container?)")


LOGIN_USER_BURST = 50
EXTENSIONS = ("timescaledb", "postgis", "vector", "btree_gist", "pgcrypto")


def with_db(url: str, dbname: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/{dbname}"


def with_user(url: str, user: str, password: str) -> str:
    scheme, _, rest = url.partition("://")
    return f"{scheme}://{user}:{password}@{rest.split('@', 1)[1]}"


@dataclass
class ScratchDb:
    admin_url: str
    runtime_url: str
    password: str
    name: str
    role: str


def create_scratch_db(admin: str) -> ScratchDb:
    from sgw.api.users import seed_users
    from sgw.common.migrate import apply

    suffix = uuid.uuid4().hex[:10]
    name, role, role_pw = f"sgw_wp08_t_{suffix}", f"sgw_wp08rt_{suffix}", secrets.token_hex(16)
    with psycopg.connect(admin, autocommit=True) as conn:
        for app_role in ("sgw_app", "sgw_readonly"):
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (app_role,)).fetchone():
                conn.execute(f"CREATE ROLE {app_role} NOLOGIN")
        conn.execute(f'CREATE DATABASE "{name}"')
        conn.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{role_pw}' IN ROLE sgw_app")
    url = with_db(admin, name)
    with psycopg.connect(url, autocommit=True) as conn:
        for ext in EXTENSIONS:
            conn.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
    apply(url)
    password = "wp08-" + secrets.token_hex(12)
    seed_users(url, password)
    return ScratchDb(url, with_user(url, role, role_pw), password, name, role)


def drop_scratch_db(admin: str, db: ScratchDb) -> None:
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{db.name}" WITH (FORCE)')
        conn.execute(f"DROP ROLE IF EXISTS {db.role}")


def wait_http(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last = "no response"
    while time.monotonic() < deadline:
        try:
            status = httpx.get(url, timeout=2).status_code
            if status == 200:
                return
            last = f"HTTP {status}"
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(0.2)
    raise RuntimeError(f"{url} not ready: {last}")


def api_bind_host() -> str:
    """Address the test uvicorn listens on, reachable from the Caddy container as `host.docker.internal`.

    Docker Desktop (macOS, Windows) forwards `host-gateway` to the host's loopback, so 127.0.0.1 works and
    nothing is exposed. On Linux `host-gateway` is the bridge gateway (docker0, e.g. 172.17.0.1), which cannot
    reach a loopback listener, so the server binds that gateway address: reachable from containers on the
    bridge, still not from the network. `SGW_TEST_API_BIND` overrides both.
    """
    override = os.environ.get("SGW_TEST_API_BIND")
    if override:
        return override
    if not sys.platform.startswith("linux"):
        return "127.0.0.1"
    out = subprocess.run(
        ["docker", "network", "inspect", "bridge", "--format", "{{(index .IPAM.Config 0).Gateway}}"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    gateway = out.stdout.strip()
    return gateway if out.returncode == 0 and gateway else "0.0.0.0"  # noqa: S104


def _tail(path: Path, lines: int = 60) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"


def start_api(db: ScratchDb, port: int, log_path: Path) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "SGW_DATABASE_URL": db.runtime_url,
        "SGW_SCENARIO": "helene",
        "SGW_SSE_HEARTBEAT_S": "1",
        "DEMO_MODE": "1",
        "SGW_LOGIN_IP_BURST": "1000",
        "SGW_LOGIN_USER_BURST": str(LOGIN_USER_BURST),
    }
    host = api_bind_host()
    cmd = [sys.executable, "-m", "uvicorn", "sgw.api.app:create_app", "--factory", "--host", host]
    cmd += ["--port", str(port), "--no-server-header", "--log-level", "warning"]
    log = log_path.open("wb")
    proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, cwd=REPO_ROOT)  # noqa: S603
    try:
        wait_http(f"http://{host}:{port}/readyz")
    except RuntimeError as exc:
        proc.terminate()
        raise RuntimeError(f"{exc}\n--- uvicorn log ({host}:{port}) ---\n{_tail(log_path)}") from None
    return proc


def caddyfile_for(api_port: int) -> str:
    """The repository Caddyfile with only the upstream address changed (api:8000 -> the host uvicorn)."""
    text = CADDYFILE.read_text(encoding="utf-8")
    assert "reverse_proxy api:8000" in text
    return text.replace("reverse_proxy api:8000", f"reverse_proxy host.docker.internal:{api_port}")


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0  # noqa: S607


def start_caddy(api_port: int, workdir: Path, site_port: int, relay_port: int) -> CaddyPorts:
    conf = workdir / "Caddyfile"
    conf.write_text(caddyfile_for(api_port), encoding="utf-8")
    name = f"sgw-wp08-caddy-{uuid.uuid4().hex[:8]}"
    cmd = ["docker", "run", "-d", "--rm", "--name", name, "--add-host", "host.docker.internal:host-gateway"]
    require_free(site_port)
    require_free(relay_port)
    cmd += ["-p", f"127.0.0.1:{site_port}:8080", "-p", f"127.0.0.1:{relay_port}:8000"]
    cmd += ["-v", f"{conf}:/etc/caddy/Caddyfile:ro", CADDY_IMAGE]
    subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603
    try:
        wait_http(f"http://127.0.0.1:{site_port}/healthz")
        wait_http(f"http://127.0.0.1:{site_port}/api/openapi.json")
    except RuntimeError as exc:
        logs = caddy_logs(name)
        stop_caddy(name)
        raise RuntimeError(f"{exc}\n--- caddy logs ({name}) ---\n{logs}") from None
    return CaddyPorts(name, site_port, relay_port)


def caddy_logs(name: str, lines: int = 80) -> str:
    out = subprocess.run(  # noqa: S603
        ["docker", "logs", "--tail", str(lines), name],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return (out.stdout + out.stderr).strip() or "(no output)"


def stop_caddy(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)  # noqa: S603,S607


def insert_events(admin_db_url: str, n: int, *, pace_s: float = 0.0) -> list[tuple[int, float]]:
    """Insert `n` K2 OutageEvent rows as the ledger writer would; returns (ledger_seq, commit wall time)."""
    out: list[tuple[int, float]] = []
    with psycopg.connect(admin_db_url, autocommit=True) as conn:
        for _ in range(n):
            out.append(insert_one(conn))
            if pace_s:
                time.sleep(pace_s)
    return out


def insert_one(conn: psycopg.Connection[Any]) -> tuple[int, float]:
    event_id = uuid.uuid4()
    now = datetime.now(UTC)
    at = datetime(2024, 9, 27, 4, tzinfo=UTC)
    env = EVENT_MODELS["OutageEvent"].model_validate(
        {
            "type": "OutageEvent",
            "event_id": str(event_id),
            "source_id": "oms-synthetic",
            "feed_mode": "replay",
            "run_mode": "replay",
            "event_time": at,
            "received_at": now,
            "known_at": now,
            "scenario_known_at": at,
            "dedup_key": f"wp08-test:{event_id}",
            "classification": "C1",
            "trust": "verified_internal",
            "payload": {
                "outage_id": f"OUT-WP08-{event_id.hex[:8]}",
                "status": "open",
                "device_id": "RCL-AIK-0412",
                "feeder_id": "FDR-AIK-2207",
                "customers_out": 37,
                "cause": "wind",
            },
        }
    )
    d = env.model_dump(mode="json")
    row = conn.execute(
        "INSERT INTO event (event_id, type, schema_version, source_id, feed_mode, run_mode, event_time,"
        " received_at, known_at, scenario_known_at, dedup_key, classification, trust, payload)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING ledger_seq",
        (
            event_id,
            d["type"],
            d["schema_version"],
            d["source_id"],
            d["feed_mode"],
            d["run_mode"],
            at,
            now,
            now,
            at,
            d["dedup_key"],
            d["classification"],
            d["trust"],
            Jsonb(d["payload"]),
        ),
    ).fetchone()
    assert row is not None
    return int(row[0]), time.time()


@dataclass
class Received:
    sse_id: SseId
    frame: WireFrame
    at: float


@dataclass
class SseReader:
    """Incremental SSE parser over an httpx stream; records the wall time each frame was parsed."""

    frames: list[Received] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)

    async def read(
        self, client: httpx.AsyncClient, url: str, *, last_event_id: str | None, stop: asyncio.Event
    ) -> None:
        headers = {"Accept": "text/event-stream", "Accept-Encoding": "gzip, deflate, zstd"}
        if last_event_id:
            headers["Last-Event-ID"] = last_event_id
        async with client.stream("GET", url, headers=headers, timeout=httpx.Timeout(30, read=30)) as resp:
            resp.raise_for_status()
            self.headers = dict(resp.headers)
            buf = ""
            async for text in _chunks(resp):
                buf += text
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    self._block(block)
                if stop.is_set():
                    return

    def _block(self, block: str) -> None:
        if not block.strip() or block.startswith(":"):
            return
        fields = dict(line.partition(": ")[::2] for line in block.splitlines())
        self.frames.append(
            Received(SseId.parse(fields["id"]), WireFrame.model_validate_json(fields["data"]), time.time())
        )


async def _chunks(resp: httpx.Response) -> AsyncIterator[str]:
    async for text in resp.aiter_text():
        yield text


def expect(response: httpx.Response, status: int) -> httpx.Response:
    """Assert a status and show the body on failure (an ErrorBody code says which check refused)."""
    assert response.status_code == status, (
        f"{response.request.method} {response.request.url} -> {response.status_code}, expected {status}: "
        f"{response.text[:500]}"
    )
    return response
