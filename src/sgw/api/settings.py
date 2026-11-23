"""API settings, read from the environment once at start-up and validated (fail fast on bad values)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from sgw.contracts.identities import PASSWORD_ENV

STEP_UP_TTL_S = 300


class SettingsError(ValueError):
    pass


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    if raw.lower() in {"1", "true", "yes", "on"}:
        return True
    if raw.lower() in {"0", "false", "no", "off"}:
        return False
    raise SettingsError(f"{name} must be a boolean flag, got {raw!r}")


def _number(env: Mapping[str, str], name: str, default: float, *, low: float, high: float) -> float:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be a number, got {raw!r}") from exc
    if not low <= value <= high:
        raise SettingsError(f"{name} must be within [{low}, {high}], got {value}")
    return value


@dataclass(frozen=True)
class ApiSettings:
    database_url: str
    demo_mode: bool = False
    api_docs: bool = False
    demo_password: str | None = field(default=None, repr=False)
    scenario: str = "helene"
    cookie_secure: bool = False
    session_ttl_s: int = 12 * 3600
    step_up_ttl_s: int = STEP_UP_TTL_S
    heartbeat_s: float = 10.0
    ledger_poll_s: float = 0.25
    gap_hold_s: float = 1.0
    client_queue_max: int = 1000
    max_stream_clients: int = 200
    pool_max: int = 6
    users_path: str | None = None
    login_ip_burst: int = 30
    login_ip_per_min: float = 30.0
    login_user_burst: int = 5
    login_user_per_min: float = 5.0

    def __post_init__(self) -> None:
        if not self.demo_mode and not self.cookie_secure:
            raise SettingsError(
                "refusing to start: outside DEMO_MODE the session cookie must be Secure (SGW_COOKIE_SECURE=1)"
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ApiSettings:
        env = os.environ if env is None else env
        url = env.get("SGW_DATABASE_URL", "")
        if not url:
            raise SettingsError("SGW_DATABASE_URL is not set")
        return cls(
            database_url=url,
            demo_mode=_flag(env, "DEMO_MODE", False),
            api_docs=_flag(env, "SGW_API_DOCS", False),
            demo_password=env.get(PASSWORD_ENV) or None,
            scenario=env.get("SGW_SCENARIO", "helene"),
            cookie_secure=_flag(env, "SGW_COOKIE_SECURE", False),
            session_ttl_s=int(_number(env, "SGW_SESSION_TTL_S", 12 * 3600, low=60, high=7 * 86400)),
            heartbeat_s=_number(env, "SGW_SSE_HEARTBEAT_S", 10.0, low=0.05, high=60),
            ledger_poll_s=_number(env, "SGW_LEDGER_POLL_S", 0.25, low=0.01, high=10),
            gap_hold_s=_number(env, "SGW_LEDGER_GAP_HOLD_S", 1.0, low=0.0, high=30),
            client_queue_max=int(_number(env, "SGW_SSE_QUEUE_MAX", 1000, low=1, high=100_000)),
            max_stream_clients=int(_number(env, "SGW_SSE_MAX_CLIENTS", 200, low=1, high=10_000)),
            pool_max=int(_number(env, "SGW_DB_POOL_MAX", 6, low=1, high=50)),
            users_path=env.get("SGW_USERS_PATH") or None,
            login_ip_burst=int(_number(env, "SGW_LOGIN_IP_BURST", 30, low=1, high=100_000)),
            login_ip_per_min=_number(env, "SGW_LOGIN_IP_PER_MIN", 30.0, low=0.1, high=100_000),
            login_user_burst=int(_number(env, "SGW_LOGIN_USER_BURST", 5, low=1, high=100_000)),
            login_user_per_min=_number(env, "SGW_LOGIN_USER_PER_MIN", 5.0, low=0.1, high=100_000),
        )
