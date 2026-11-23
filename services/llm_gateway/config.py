from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .callers import parse_token_digests

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = REPO_ROOT / "data" / "fixtures"
K14_NODES_FILE = REPO_ROOT / "src" / "sgw" / "agent" / "llm_nodes.yaml"


class Mode(StrEnum):
    LIVE = "live"
    RECORD = "record"
    REPLAY = "replay"
    REPLAY_THEN_LIVE = "replay_then_live"


def _float(name: str, default: float | None) -> float | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def _cap(name: str, default: float | None) -> float | None:
    """A USD cap from the environment: a number, `off` for no cap, unset for the default."""
    raw = os.environ.get(name, "").strip().lower()
    if raw == "off":
        return None
    return _or(_float(name, None), default)


def _int(name: str, default: int | None) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _or[T](value: T | None, default: T) -> T:
    return default if value is None else value


ANTHROPIC_BASE_URL = "https://api.anthropic.com"
EGRESS_ROUTES = frozenset({"R1", "R2"})
EGRESS_PDPS = frozenset({"opa", "reference"})


@dataclass(frozen=True)
class Settings:
    mode: Mode = Mode.REPLAY
    upstream_base_url: str = ANTHROPIC_BASE_URL
    allow_test_upstream: bool = False
    fixture_dir: Path = REPO_ROOT / "data" / "fixtures" / "llm"
    spend_csv: Path = REPO_ROOT / "var" / "llm_spend.csv"
    nodes_file: Path | None = None
    soft_stop_usd: float = 40.0
    hard_stop_usd: float = 90.0
    budget_ack_usd: float | None = None
    console_balance_usd: float | None = None
    balance_floor_usd: float = 100.0
    daily_cap_usd: float | None = 30.0
    live_cache_dir: Path = REPO_ROOT / "var" / "llm" / "live_cache"
    wave_cap_usd: float | None = None
    wave_cap_calls: int | None = None
    default_deadline_s: float = 120.0
    replay_pace_max_s: float = 0.0
    attempt_timeout_s: float = 90.0
    max_attempts: int = 4
    backoff_base_s: float = 0.5
    backoff_max_s: float = 8.0
    breaker_threshold: int = 5
    breaker_cooldown_s: float = 30.0
    record_overwrite: bool = False
    opa_url: str | None = None
    egress_pdp: str | None = None
    egress_route: str = "R1"
    canary_tokens: tuple[str, ...] = ()
    llm_call_dsn: str | None = field(default=None, repr=False)
    caller_token_digests: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    accept_test_tokens: bool = False
    callers_file: Path | None = None
    admin_token: str | None = field(default=None, repr=False)
    api_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.upstream_base_url.rstrip("/") != ANTHROPIC_BASE_URL and not self.allow_test_upstream:
            raise ValueError(
                "upstream_base_url must be https://api.anthropic.com (LLM_ALLOW_TEST_UPSTREAM=1 for tests)"
            )
        cache = self.live_cache_dir.resolve()
        if any(cache.is_relative_to(root.resolve()) for root in (FIXTURES_ROOT, self.fixture_dir)):
            raise ValueError("the live cache must live outside data/fixtures and the replay fixture dir")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.egress_route not in EGRESS_ROUTES:
            raise ValueError(f"egress_route must be one of {sorted(EGRESS_ROUTES)}")
        if self.egress_pdp is not None and self.egress_pdp not in EGRESS_PDPS:
            raise ValueError(f"egress_pdp must be one of {sorted(EGRESS_PDPS)}")
        if self.egress_pdp == "opa" and not self.opa_url:
            raise ValueError("LLM_EGRESS_PDP=opa needs SGW_OPA_URL")
        real_api = self.mode is not Mode.REPLAY and not self.allow_test_upstream
        if real_api and self.accept_test_tokens:
            raise ValueError("public test caller tokens are refused for live and record runs against the API")
        if real_api and self.resolved_pdp() != "opa" and self.egress_pdp != "reference":
            raise ValueError(
                "live and record runs need the OPA egress gate: set SGW_OPA_URL "
                "(or LLM_EGRESS_PDP=reference explicitly for a host run without OPA)"
            )

    def resolved_pdp(self) -> str:
        if self.egress_pdp:
            return self.egress_pdp
        return "opa" if self.opa_url else "reference"

    @classmethod
    def from_env(cls) -> Settings:
        nodes = os.environ.get("LLM_NODES_FILE") or (
            str(K14_NODES_FILE) if K14_NODES_FILE.is_file() else None
        )
        return cls(
            mode=Mode(os.environ.get("LLM_MODE", Mode.REPLAY.value)),
            upstream_base_url=os.environ.get("LLM_UPSTREAM_BASE_URL", cls.upstream_base_url),
            allow_test_upstream=os.environ.get("LLM_ALLOW_TEST_UPSTREAM", "") == "1",
            fixture_dir=Path(os.environ.get("LLM_FIXTURE_DIR", str(cls.fixture_dir))),
            spend_csv=Path(os.environ.get("LLM_SPEND_CSV", str(cls.spend_csv))),
            nodes_file=Path(nodes) if nodes else None,
            soft_stop_usd=_or(_float("LLM_SOFT_STOP_USD", None), cls.soft_stop_usd),
            hard_stop_usd=_or(_float("LLM_HARD_STOP_USD", None), cls.hard_stop_usd),
            budget_ack_usd=_float("LLM_BUDGET_ACK", None),
            console_balance_usd=_float("LLM_CONSOLE_BALANCE_USD", None),
            balance_floor_usd=_or(_float("LLM_BALANCE_FLOOR_USD", None), cls.balance_floor_usd),
            daily_cap_usd=_cap("LLM_DAILY_CAP_USD", cls.daily_cap_usd),
            live_cache_dir=Path(os.environ.get("LLM_LIVE_CACHE_DIR", str(cls.live_cache_dir))),
            wave_cap_usd=_float("LLM_WAVE_CAP_USD", None),
            wave_cap_calls=_int("LLM_WAVE_CAP_CALLS", None),
            default_deadline_s=_or(_float("LLM_DEADLINE_S", None), cls.default_deadline_s),
            replay_pace_max_s=_or(_float("LLM_REPLAY_PACE_MAX_S", None), cls.replay_pace_max_s),
            max_attempts=_or(_int("LLM_MAX_ATTEMPTS", None), cls.max_attempts),
            record_overwrite=os.environ.get("LLM_RECORD_OVERWRITE", "") == "1",
            admin_token=os.environ.get("LLM_GATEWAY_ADMIN_TOKEN") or None,
            api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            opa_url=os.environ.get("SGW_OPA_URL") or None,
            egress_pdp=os.environ.get("LLM_EGRESS_PDP") or None,
            egress_route=os.environ.get("LLM_EGRESS_ROUTE") or cls.egress_route,
            canary_tokens=tuple(
                t.strip() for t in os.environ.get("LLM_CANARY_TOKENS", "").split(",") if t.strip()
            ),
            llm_call_dsn=os.environ.get("SGW_LLM_CALL_DSN") or None,
            caller_token_digests=parse_token_digests(os.environ.get("LLM_CALLER_TOKEN_SHA256", "")),
            accept_test_tokens=os.environ.get("LLM_ACCEPT_TEST_TOKENS", "") == "1",
            callers_file=Path(os.environ["LLM_CALLERS_FILE"]) if os.environ.get("LLM_CALLERS_FILE") else None,
        )
