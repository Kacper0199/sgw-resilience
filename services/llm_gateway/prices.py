from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PRICE_TABLE_VERSION = "anthropic-pricing-2026-11-19"
PRICE_SOURCE = (
    "https://platform.claude.com/docs/en/about-claude/pricing (read 2026-11-19) + claude-api skill table"
)
HAIKU_LONG_PROMPT_THRESHOLD = 100_000
BATCH_DISCOUNT = 0.5


@dataclass(frozen=True)
class Price:
    input: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float
    output: float


PRICES_PER_MTOK: dict[str, Price] = {
    "claude-sonnet-5-5": Price(2.00, 2.50, 4.00, 0.10, 10.00),
    "claude-haiku-5-5": Price(0.10, 0.125, 0.20, 0.01, 0.50),
    "claude-opus-5-5": Price(4.00, 5.00, 8.00, 0.20, 20.00),
}
HAIKU_LONG_PROMPT = Price(0.50, 0.625, 1.00, 0.05, 2.50)


class UnknownModelPrice(KeyError):
    pass


def price_for(model: str, prompt_tokens: int) -> Price:
    if model not in PRICES_PER_MTOK:
        raise UnknownModelPrice(model)
    if model == "claude-haiku-5-5" and prompt_tokens > HAIKU_LONG_PROMPT_THRESHOLD:
        return HAIKU_LONG_PROMPT
    return PRICES_PER_MTOK[model]


def usage_tokens(usage: dict[str, Any]) -> dict[str, int]:
    creation = usage.get("cache_creation") or {}
    total_creation = int(usage.get("cache_creation_input_tokens") or 0)
    write_1h = int(creation.get("ephemeral_1h_input_tokens") or 0)
    write_5m = int(creation.get("ephemeral_5m_input_tokens") or (total_creation - write_1h))
    return {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "cache_creation_input_tokens": total_creation,
        "cache_write_5m": max(write_5m, 0),
        "cache_write_1h": write_1h,
        "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
    }


def cost_usd(model: str, usage: dict[str, Any], *, batch: bool = False) -> float:
    t = usage_tokens(usage)
    prompt = t["input_tokens"] + t["cache_creation_input_tokens"] + t["cache_read_input_tokens"]
    p = price_for(model, prompt)
    total = (
        t["input_tokens"] * p.input
        + t["cache_write_5m"] * p.cache_write_5m
        + t["cache_write_1h"] * p.cache_write_1h
        + t["cache_read_input_tokens"] * p.cache_read
        + t["output_tokens"] * p.output
    ) / 1_000_000
    if batch:
        total *= BATCH_DISCOUNT
    return round(total, 6)


def worst_case_cost_usd(model: str, prompt_tokens_estimate: int, max_tokens: int) -> float:
    p = price_for(model, prompt_tokens_estimate)
    return round((prompt_tokens_estimate * p.cache_write_5m + max_tokens * p.output) / 1_000_000, 6)
