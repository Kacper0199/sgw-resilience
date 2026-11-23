"""Turn caps for the copilot team (AX §2): at most `MAX_LLM_CALLS` model calls and `MAX_TURN_USD` per turn,
`MAX_WAVES` waves, `TURN_TIMEOUT_S` wall clock. The gateway enforces money for real (its worst-case reserve);
here the graph plans within the caps so a cap is met by a code fallback, never by an error.

Spend is priced from each response's `usage` at the K13 list prices; a step is allowed only when the spend so
far plus that step's worst case (input estimate plus `max_tokens` of output) stays inside its share. Recorded
usage makes this deterministic in replay."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sgw.contracts.llm_nodes import NodeConfig

MAX_LLM_CALLS = 12
MAX_TURN_USD = 0.25
MAX_WAVES = 2
TURN_TIMEOUT_S = 30.0
SYNTH_CALLS = 3
INPUT_ESTIMATE_TOKENS = 8_000
TYPICAL_STEP_USD = 0.012

PER_MTOK: Mapping[str, tuple[float, float, float, float]] = {
    "haiku": (0.10, 0.50, 0.01, 0.125),
    "sonnet": (2.00, 10.00, 0.10, 2.50),
    "opus": (4.00, 20.00, 0.20, 5.00),
}


def cost(alias: str, usage: Mapping[str, Any]) -> float:
    inp, out, read, write = PER_MTOK[alias]
    tokens = (
        int(usage.get("input_tokens") or 0) * inp
        + int(usage.get("output_tokens") or 0) * out
        + int(usage.get("cache_read_input_tokens") or 0) * read
        + int(usage.get("cache_creation_input_tokens") or 0) * write
    )
    return tokens / 1_000_000


def spent(alias: str, usages: Iterable[Mapping[str, Any]]) -> float:
    return sum(cost(alias, u) for u in usages)


def worst_case(config: NodeConfig) -> float:
    inp, out, _, _ = PER_MTOK[config.model.value]
    return (INPUT_ESTIMATE_TOKENS * inp + config.max_tokens * out) / 1_000_000


def steps_within(config: NodeConfig, share_usd: float, typical_usd: float, cap: int) -> int:
    """How many steps a node may take inside its USD share: each step needs its worst case free, and the
    steps before it are assumed to cost `typical_usd` (the measured median)."""
    n = 0
    while n < cap and n * typical_usd + worst_case(config) <= share_usd:
        n += 1
    return n
