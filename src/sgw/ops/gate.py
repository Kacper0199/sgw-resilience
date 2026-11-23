"""LLM gate for agent nodes (WP-14b calls this before each LLM node). Two checks, either one sends the node to
its deterministic template path with the same slot values: the platform state (`llm_gate`: kill level,
degraded mode and signals from the database, fail closed) and the gateway's own refusal (`sgw_llm_disabled`,
HTTP 503), which covers a state change between the check and the call.

    decision = llm_gate(conn)
    text = run_llm_node(decision, call=lambda: narrate(slots), template=lambda: render(slots))
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg

from sgw.contracts.vocab import DegradedMode, KillLevel
from sgw.ops.control import capability_map, load_signals, read_control
from sgw.ops.levels import Capability

LLM_DISABLED_CODE = "sgw_llm_disabled"


@dataclass(frozen=True)
class LlmGate:
    allowed: bool
    reason: str
    kill_level: KillLevel
    degraded_mode: DegradedMode


class LlmDisabledError(RuntimeError):
    """Raise from an LLM call when the gateway answered `sgw_llm_disabled`."""


def llm_gate(conn: psycopg.Connection[Any]) -> LlmGate:
    view = read_control(conn)
    try:
        signals = load_signals(conn)
    except psycopg.Error:
        signals = {}
    allowed = view.readable and capability_map(view, signals)[Capability.LLM_CALLS]
    if not view.readable:
        reason = "control state unreadable"
    elif allowed:
        reason = "ok"
    else:
        reason = f"kill level {view.kill_level.value}, degraded mode {view.degraded_mode.value}"
    return LlmGate(allowed, reason, view.kill_level, view.degraded_mode)


def is_llm_disabled(status: int, body: Any) -> bool:
    """True for the gateway's typed refusal: HTTP 503 with error type `sgw_llm_disabled`."""
    error = body.get("error") if isinstance(body, dict) else None
    return status == 503 and isinstance(error, dict) and error.get("type") == LLM_DISABLED_CODE


def run_llm_node[T](gate: LlmGate, *, call: Callable[[], T], template: Callable[[], T]) -> tuple[T, str]:
    """The node's output and the path taken: `llm`, or `template` when the gate is closed or the gateway
    refused."""
    if not gate.allowed:
        return template(), "template"
    try:
        return call(), "llm"
    except LlmDisabledError:
        return template(), "template"
