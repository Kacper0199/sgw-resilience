from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from typing import Annotated

import typer

from sgw.cli import hostinfo
from sgw.cli.support import (
    HOST_PORTS,
    PROJECT,
    compose_env_path,
    llm_env_file,
    platform_name,
    read_env_file,
    repo_root,
    secrets_dir,
)

app = typer.Typer()

OK, WARN, FAIL = "ok", "warn", "FAIL"
MIN_DOCKER_MEMORY_GIB = 6.0
REC_DOCKER_MEMORY_GIB = 8.0
MIN_DISK_GIB = 15.0
MIN_COMPOSE = (2, 24)
MIN_ENGINE = 25
MIN_NODE = 22


@dataclass(frozen=True)
class Finding:
    check: str
    status: str
    detail: str
    fix: str = ""


HINTS = {
    "docker": {
        "macOS": "install Docker Desktop: https://docs.docker.com/desktop/setup/install/mac-install/",
        "Windows": "install Docker Desktop with the WSL 2 backend: https://docs.docker.com/desktop/setup/install/windows-install/",
        "Linux": "install Docker Engine + compose plugin: https://docs.docker.com/engine/install/",
    },
    "daemon": {
        "macOS": "start Docker Desktop (open -a Docker) and wait for 'Engine running'",
        "Windows": "start Docker Desktop and wait for 'Engine running'",
        "Linux": "sudo systemctl start docker (and add your user to the docker group)",
    },
    "memory": {
        "macOS": "Docker Desktop > Settings > Resources > Memory: 8 GB",
        "Windows": "WSL 2: set memory=8GB in %UserProfile%\\.wslconfig, then `wsl --shutdown`",
        "Linux": "Docker Engine uses host memory directly; free memory on the host",
    },
    "uv": {
        "macOS": "curl -LsSf https://astral.sh/uv/install.sh | sh",
        "Windows": 'powershell -c "irm https://astral.sh/uv/install.ps1 | iex"',
        "Linux": "curl -LsSf https://astral.sh/uv/install.sh | sh",
    },
    "git": {
        "macOS": "xcode-select --install (or `brew install git`)",
        "Windows": "winget install Git.Git",
        "Linux": "install git with your package manager",
    },
    "node": {
        "macOS": "install Node 24 LTS (https://nodejs.org or `brew install node@24`)",
        "Windows": "install Node 24 LTS from https://nodejs.org (or `winget install OpenJS.NodeJS.LTS`)",
        "Linux": "install Node 24 LTS from https://nodejs.org or your distribution's NodeSource package",
    },
}


def hint(topic: str) -> str:
    return HINTS[topic].get(platform_name(), HINTS[topic]["Linux"])


def _version(text: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    return tuple(int(g) for g in match.groups() if g is not None) if match else ()


def _run(*cmd: str, timeout: float = 20) -> tuple[int, str]:
    try:
        result = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return result.returncode, (result.stdout or result.stderr).strip()


def check_python() -> Finding:
    version = sys.version_info
    ok = (version.major, version.minor) == (3, 12)
    detail = f"{version.major}.{version.minor}.{version.micro}"
    return Finding(
        "python", OK if ok else WARN, detail, "" if ok else "run through `uv run`, which uses 3.12"
    )


def check_tool(name: str, topic: str, *version_args: str, required: bool = True) -> Finding:
    path = shutil.which(name)
    if not path:
        return Finding(name, FAIL if required else WARN, "not found on PATH", hint(topic))
    code, out = _run(path, *version_args)
    return Finding(name, OK if code == 0 else WARN, out.splitlines()[0] if out else path)


def check_docker() -> list[Finding]:
    docker = shutil.which("docker")
    if not docker:
        return [Finding("docker", FAIL, "not found on PATH", hint("docker"))]
    findings: list[Finding] = []
    code, out = _run(docker, "info", "--format", "{{json .}}", timeout=30)
    if code != 0:
        return [
            Finding("docker daemon", FAIL, out.splitlines()[-1] if out else "not reachable", hint("daemon"))
        ]
    info = json.loads(out)
    findings.append(
        Finding("docker daemon", OK, f"{info.get('ServerVersion')} on {info.get('Architecture')}")
    )
    engine = _version(str(info.get("ServerVersion", "")))
    if engine and engine[0] < MIN_ENGINE:
        findings.append(
            Finding(
                "docker engine",
                FAIL,
                f"{info.get('ServerVersion')} (need >= {MIN_ENGINE}: healthcheck start_interval)",
                "update Docker Desktop to >= 4.27 or Docker Engine to >= 25",
            )
        )
    memory_gib = info.get("MemTotal", 0) / hostinfo.GIB
    if memory_gib < MIN_DOCKER_MEMORY_GIB:
        status = FAIL
    elif memory_gib < REC_DOCKER_MEMORY_GIB - 0.5:
        status = WARN
    else:
        status = OK
    findings.append(
        Finding(
            "docker memory",
            status,
            f"{memory_gib:.1f} GiB (need >= {REC_DOCKER_MEMORY_GIB:.0f})",
            "" if status == OK else hint("memory"),
        )
    )
    code, out = _run(docker, "compose", "version", "--short")
    version = _version(out)
    if code != 0 or not version:
        findings.append(Finding("docker compose", FAIL, "compose v2 plugin missing", hint("docker")))
    else:
        status = OK if version[:2] >= MIN_COMPOSE else FAIL
        findings.append(
            Finding(
                "docker compose",
                status,
                out,
                "" if status == OK else f"update to compose >= {MIN_COMPOSE[0]}.{MIN_COMPOSE[1]}",
            )
        )
    code, out = _run(docker, "buildx", "version")
    findings.append(
        Finding(
            "docker buildx",
            OK if code == 0 else WARN,
            out.split("\n")[0] if out else "missing",
            "" if code == 0 else "needed only for multi-arch image builds",
        )
    )
    return findings


def check_node() -> list[Finding]:
    node = shutil.which("node")
    if not node:
        return [Finding("node", WARN, "not found (needed for the web UI build)", hint("node"))]
    _, out = _run(node, "--version")
    version = _version(out)
    findings = [
        Finding(
            "node",
            OK if version and version[0] >= MIN_NODE else WARN,
            out,
            "" if version and version[0] >= MIN_NODE else hint("node"),
        )
    ]
    pnpm = shutil.which("pnpm")
    if pnpm:
        _, pout = _run(pnpm, "--version")
        findings.append(Finding("pnpm", OK, pout))
    else:
        findings.append(Finding("pnpm", WARN, "not found", "corepack enable pnpm"))
    return findings


def _bind_option() -> int:
    """Windows lets SO_REUSEADDR bind over a live listener, so it needs the exclusive flag instead."""
    if os.name == "nt":
        return socket.SO_EXCLUSIVEADDRUSE  # type: ignore[attr-defined]
    return socket.SO_REUSEADDR


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, _bind_option(), 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _ports_held_by_stack() -> set[int]:
    docker = shutil.which("docker")
    if not docker:
        return set()
    code, out = _run(
        docker, "ps", "--filter", f"label=com.docker.compose.project={PROJECT}", "--format", "{{.Ports}}"
    )
    if code != 0:
        return set()
    return {int(p) for p in re.findall(r"127\.0\.0\.1:(\d+)->", out)}


def check_ports() -> list[Finding]:
    held = _ports_held_by_stack()
    findings = []
    for name, port in HOST_PORTS.items():
        if port in held:
            findings.append(Finding(f"port {port}", OK, f"held by the running sgw stack ({name})"))
        elif _port_free(port):
            findings.append(Finding(f"port {port}", OK, f"free ({name})"))
        else:
            fix = "find the owner: " + (
                "netstat -ano | findstr :" if platform_name() == "Windows" else "lsof -nP -iTCP:"
            )
            findings.append(
                Finding(f"port {port}", FAIL, f"in use by another program ({name})", f"{fix}{port}")
            )
    return findings


def check_host() -> list[Finding]:
    mem = hostinfo.host_memory()
    findings = []
    if mem.total:
        total = mem.total / hostinfo.GIB
        findings.append(
            Finding(
                "host memory",
                OK if total >= 16 else WARN,
                f"{total:.0f} GiB total, {(mem.available or 0) / hostinfo.GIB:.1f} GiB available",
                "" if total >= 16 else "16 GiB recommended; run the core profile only",
            )
        )
    if mem.swap_used is not None:
        swap = mem.swap_used / hostinfo.GIB
        findings.append(
            Finding(
                "host swap",
                OK if swap < 4 else WARN,
                f"{swap:.1f} GiB used",
                "" if swap < 4 else "close other heavy apps or restart before a demo",
            )
        )
    free = shutil.disk_usage(repo_root()).free / hostinfo.GIB
    findings.append(
        Finding(
            "disk free",
            OK if free >= MIN_DISK_GIB else FAIL,
            f"{free:.0f} GiB",
            "" if free >= MIN_DISK_GIB else f"free at least {MIN_DISK_GIB:.0f} GiB",
        )
    )
    return findings


def check_project() -> list[Finding]:
    findings = []
    if (secrets_dir() / "postgres.env").is_file() and compose_env_path().is_file():
        findings.append(Finding("credentials", OK, f"generated in {secrets_dir()}"))
    else:
        findings.append(Finding("credentials", FAIL, "not generated yet", "uv run sgw bootstrap"))
    env_file = llm_env_file()
    findings.append(
        Finding(
            "LLM key file",
            OK if env_file.exists() else WARN,
            f"{'present' if env_file.exists() else 'absent'} (not opened): {env_file}",
            ""
            if env_file.exists()
            else "optional: replay mode needs no key; live mode needs ANTHROPIC_API_KEY in that file",
        )
    )
    if platform_name() == "Windows":
        code, out = _run("git", "config", "--get", "core.autocrlf")
        bad = code == 0 and out.strip().lower() == "true"
        findings.append(
            Finding(
                "git line endings",
                WARN if bad else OK,
                f"core.autocrlf={out or 'unset'}",
                "git config --global core.autocrlf input, then re-clone" if bad else "",
            )
        )
    return findings


def check_audit() -> list[Finding]:
    from sgw.approval.signer import Keyring
    from sgw.cli.audit_setup import audit_dirs

    keyring_path, key_dir, anchors = audit_dirs()
    fix = "uv run sgw bootstrap"
    active = Keyring.load(keyring_path).active
    if not active:
        return [Finding("audit key", FAIL, f"no active key in {keyring_path}", fix)]
    pem = key_dir / f"{active.replace(':', '-')}.pem"
    findings = []
    if not pem.is_file():
        findings.append(Finding("audit key", FAIL, f"{active}: private key file missing", f"restore {pem}"))
    elif os.name != "nt" and pem.stat().st_mode & 0o077:
        findings.append(Finding("audit key", FAIL, f"{pem.name} readable by others", f"chmod 600 {pem}"))
    else:
        findings.append(Finding("audit key", OK, f"{active} (file 0600, not opened)"))
    pinned = (
        read_env_file(compose_env_path()).get("SGW_AUDIT_ACTIVE_KEY")
        if compose_env_path().is_file()
        else None
    )
    if pinned != active:
        findings.append(Finding("audit key pin", FAIL, f"compose.env pins {pinned or 'nothing'}", fix))
    if anchors.is_dir() and os.access(anchors, os.W_OK):
        count = sum(1 for _ in anchors.rglob("*.json"))
        findings.append(Finding("audit anchors", OK, f"{anchors} writable, {count} anchor file(s)"))
    else:
        findings.append(Finding("audit anchors", FAIL, f"{anchors} missing or not writable", fix))
    return findings


def run_checks() -> list[Finding]:
    return [
        check_python(),
        check_tool("uv", "uv", "--version"),
        check_tool("git", "git", "--version"),
        *check_docker(),
        *check_node(),
        *check_ports(),
        *check_host(),
        *check_project(),
        *check_audit(),
    ]


@app.command()
def doctor(
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Check this machine for everything the stack needs, with the fix for each gap on this OS."""
    findings = run_checks()
    if as_json:
        typer.echo(json.dumps([f.__dict__ for f in findings], indent=2))
    else:
        typer.echo(f"sgw doctor on {platform_name()}")
        width = max(len(f.check) for f in findings)
        colours = {OK: "green", WARN: "yellow", FAIL: "red"}
        for f in findings:
            mark = typer.style(f"{f.status:<4}", fg=colours[f.status])
            typer.echo(f"{mark} {f.check:<{width}}  {f.detail}")
            if f.fix:
                typer.echo(f"     {'':<{width}}  -> {f.fix}")
    failed = sum(f.status == FAIL for f in findings)
    warned = sum(f.status == WARN for f in findings)
    if not as_json:
        typer.echo(f"{len(findings)} checks: {failed} failed, {warned} warnings")
    if failed:
        raise typer.Exit(1)
