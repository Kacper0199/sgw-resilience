from __future__ import annotations

import functools
import os
import secrets
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import typer

PROJECT = "sgw"
HOST_PORTS = {"caddy (UI)": 8080, "api": 8000, "postgres": 5434, "mlflow": 5001}
DB_HOST_PORT = HOST_PORTS["postgres"]
DB_NAME = "sgw"
DB_OWNER = "sgw"
DB_SUPERUSER = "postgres"
DB_RUNTIME = "sgw_runtime"
DB_GATEWAY = "sgw_gateway"
DB_DEMO_GOTO = "sgw_demo_goto"
LLM_WRITER_ROLE = "sgw_llm_writer"
GROUP_ROLES = ("sgw_app", "sgw_readonly", "sgw_llm_writer")
REQUIRED_EXTENSIONS = (
    "timescaledb",
    "postgis",
    "vector",
    "vectorscale",
    "h3",
    "pgrouting",
    "btree_gist",
    "pgcrypto",
)
_MARKERS = ("compose.yaml", "pyproject.toml")


class CliError(RuntimeError):
    pass


def _has_markers(path: Path) -> bool:
    return all((path / marker).is_file() for marker in _MARKERS)


def repo_root() -> Path:
    override = os.environ.get("SGW_ROOT")
    if override:
        return Path(override).resolve()
    starts = [Path(__file__).resolve(), Path.cwd().resolve()]
    for start in starts:
        for candidate in (start, *start.parents):
            if _has_markers(candidate):
                return candidate
    raise CliError("cannot find the repository root (compose.yaml + pyproject.toml); set SGW_ROOT")


def git_common_dir(root: Path) -> Path | None:
    """The repository's common git dir, read from files (no git subprocess): `.git` is a directory in the
    main checkout and a `gitdir: <path>` file in a worktree, whose `commondir` points back to the main one."""
    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git.resolve()
    if not dot_git.is_file():
        return None
    line = dot_git.read_text(encoding="utf-8").strip()
    if not line.startswith("gitdir:"):
        return None
    gitdir = Path(line.removeprefix("gitdir:").strip())
    gitdir = gitdir if gitdir.is_absolute() else (root / gitdir)
    commondir = gitdir / "commondir"
    if commondir.is_file():
        target = Path(commondir.read_text(encoding="utf-8").strip())
        return (target if target.is_absolute() else gitdir / target).resolve()
    return gitdir.resolve()


def state_root() -> Path:
    """Folder that holds `var/` and `.env` for the one shared stack, also when run from a git worktree."""
    override = os.environ.get("SGW_STATE_ROOT")
    if override:
        return Path(override).resolve()
    root = repo_root()
    common = git_common_dir(root)
    return common.parent if common is not None and common.name == ".git" else root


def var_dir() -> Path:
    return state_root() / "var"


def secrets_dir() -> Path:
    return var_dir() / "secrets"


def demo_env_path() -> Path:
    return var_dir() / "demo.env"


def load_demo_env() -> dict[str, str]:
    """var/demo.env (per-persona DEMO_PASSWORD_<USER_ID>, written by `sgw bootstrap`) under the process
    environment, which wins. Values are passed on by name and never printed."""
    path = demo_env_path()
    values = read_env_file(path) if path.is_file() else {}
    return {**values, **{k: v for k, v in os.environ.items() if k.startswith("DEMO_PASSWORD")}}


def compose_env_path() -> Path:
    return var_dir() / "compose.env"


def llm_env_file() -> Path:
    """Key file for llm-gateway only: SGW_ENV_FILE if set, else the path stored by an earlier
    `sgw bootstrap` in var/compose.env, else the package key file llm.env at the root (shipped with
    an empty ANTHROPIC_API_KEY line), else the empty placeholder var/llm.env."""
    override = os.environ.get("SGW_ENV_FILE")
    if override:
        return Path(override).resolve()
    placeholder = var_dir() / "llm.env"
    package_file = state_root() / "llm.env"
    stored_env = compose_env_path()
    if stored_env.is_file():
        stored = read_env_file(stored_env).get("SGW_ENV_FILE")
        if stored and not (Path(stored) == placeholder and package_file.is_file()):
            return Path(stored)
    if package_file.is_file():
        return package_file
    return placeholder


def llm_spend_dir() -> Path:
    return var_dir() / "llm"


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_private(path: Path, lines: Mapping[str, str], header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    secure_state_dirs()
    body = [f"# {header}", *(f"{key}={value}" for key, value in lines.items())]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(body) + "\n", encoding="utf-8", newline="\n")
    if os.name != "nt":
        tmp.chmod(0o600)
    tmp.replace(path)


def secure_state_dirs() -> None:
    if os.name == "nt":
        return
    for folder in (var_dir(), secrets_dir()):
        if folder.is_dir():
            folder.chmod(0o700)


def new_password() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class Credentials:
    superuser_password: str
    owner_password: str
    runtime_password: str
    gateway_password: str

    def admin_dsn(self, database: str = "postgres") -> str:
        return f"postgresql://{DB_SUPERUSER}:{self.superuser_password}@127.0.0.1:{DB_HOST_PORT}/{database}"

    def owner_dsn(self, database: str = DB_NAME) -> str:
        return f"postgresql://{DB_OWNER}:{self.owner_password}@127.0.0.1:{DB_HOST_PORT}/{database}"

    def runtime_dsn(self, database: str = DB_NAME) -> str:
        return f"postgresql://{DB_RUNTIME}:{self.runtime_password}@127.0.0.1:{DB_HOST_PORT}/{database}"

    def gateway_dsn(self, database: str = DB_NAME) -> str:
        return f"postgresql://{DB_GATEWAY}:{self.gateway_password}@127.0.0.1:{DB_HOST_PORT}/{database}"


def load_credentials() -> Credentials:
    path = secrets_dir() / "postgres.env"
    if not path.is_file():
        raise CliError(f"no generated credentials at {path}; run `uv run sgw bootstrap` first")
    values = read_env_file(path)
    missing = [key for key in ("SGW_RUNTIME_PASSWORD", "SGW_GATEWAY_PASSWORD") if key not in values]
    if missing:
        raise CliError(
            f"credentials lack {', '.join(missing)}; run `uv run sgw bootstrap` (existing passwords are kept)"
        )
    return Credentials(
        values["POSTGRES_PASSWORD"],
        values["SGW_DB_PASSWORD"],
        values["SGW_RUNTIME_PASSWORD"],
        values["SGW_GATEWAY_PASSWORD"],
    )


def docker_bin() -> str:
    found = shutil.which("docker")
    if not found:
        raise CliError("docker is not on PATH; run `uv run sgw doctor` for install hints")
    return found


def compose_cmd(*args: str, profile: str = "core") -> list[str]:
    root = repo_root()
    env_file = compose_env_path()
    if not env_file.is_file():
        raise CliError(f"{env_file} is missing; run `uv run sgw bootstrap` first")
    return [
        docker_bin(),
        "compose",
        "--project-directory",
        str(root),
        "-f",
        str(root / "compose.yaml"),
        "--env-file",
        str(env_file),
        "--profile",
        profile,
        *args,
    ]


def echo_cmd(cmd: Sequence[str]) -> None:
    shown = " ".join(Path(cmd[0]).name if i == 0 else part for i, part in enumerate(cmd))
    typer.secho(f"$ {shown}", fg=typer.colors.BRIGHT_BLACK, err=True)


def run(
    cmd: Sequence[str], *, check: bool = True, capture: bool = False, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    echo_cmd(cmd)
    full_env = {**os.environ, **env} if env else None
    result = subprocess.run(list(cmd), capture_output=capture, text=True, check=False, env=full_env)  # noqa: S603
    if check and result.returncode != 0:
        detail = (result.stderr or "").strip() if capture else ""
        raise CliError(f"command failed with exit {result.returncode}" + (f": {detail}" if detail else ""))
    return result


def fail(message: str, code: int = 1) -> typer.Exit:
    typer.secho(message, fg=typer.colors.RED, err=True)
    return typer.Exit(code)


def guard(func):  # type: ignore[no-untyped-def]
    """Turn CliError into a one-line message and a non-zero exit."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            return func(*args, **kwargs)
        except CliError as error:
            raise fail(f"error: {error}") from None

    return wrapper


def platform_name() -> str:
    return {"darwin": "macOS", "win32": "Windows"}.get(
        sys.platform, "Linux" if sys.platform.startswith("linux") else sys.platform
    )
