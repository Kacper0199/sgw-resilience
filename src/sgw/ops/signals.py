"""Degraded-mode signals: `FAULT_*` drill flags, health probes and the hysteresis that turns readings into
active signals.

Flags are deterministic and act at once both ways (a drill must start and end on cue). Probe readings need
`enter_after` consecutive failures to raise a signal and `exit_after` consecutive successes to clear it, so a
single slow answer neither flaps the mode nor ends an outage early. A signal raised by a flag and still
failing its probe stays active after the flag is removed.

    FAULT_LLM_DOWN=1         llm_down -> M2 (template path)
    FAULT_LLM_DEGRADED=1     llm_degraded -> M1
    FAULT_OPA_DOWN=1         opa_down -> M1, approvals/tokens/effects refused
    FAULT_AUDIT_DOWN=1       audit_down -> M1, approvals/tokens/effects refused
    FAULT_WEATHER_STALE=1    weather_stale -> banner, no crew-into-hazard proposals
    FAULT_TELEMETRY_SPOOF=1  telemetry_unverified -> M1
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from sgw.ops.levels import RULES_BY_SIGNAL, SIGNAL_RULES, SignalRule

TRUTHY = frozenset({"1", "true", "yes", "on"})
Source = Literal["fault_flag", "probe", "manual"]


def fault_flags(env: Mapping[str, str]) -> frozenset[str]:
    """Signals whose `FAULT_*` flag is set; unknown `FAULT_*` names are ignored (FAULT_FEED_* belong to
    ingest)."""
    return frozenset(
        rule.signal for rule in SIGNAL_RULES if env.get(rule.fault_flag, "").strip().lower() in TRUTHY
    )


@dataclass(frozen=True)
class Reading:
    signal: str
    failing: bool
    detail: str


class Probe(Protocol):
    name: str

    def read(self) -> Sequence[Reading]: ...


@dataclass(frozen=True)
class SignalState:
    signal: str
    active: bool = False
    source: Source = "probe"
    detail: str = ""
    fail_streak: int = 0
    ok_streak: int = 0

    @property
    def rule(self) -> SignalRule:
        return RULES_BY_SIGNAL[self.signal]


def step(previous: SignalState, *, flagged: bool, reading: Reading | None) -> SignalState:
    """Next state of one signal from its flag and its latest probe reading (None: no probe configured)."""
    rule = previous.rule
    state = previous
    if reading is not None:
        if reading.failing:
            state = replace(state, fail_streak=state.fail_streak + 1, ok_streak=0, detail=reading.detail)
        else:
            state = replace(state, ok_streak=state.ok_streak + 1, fail_streak=0)
    if flagged:
        return replace(state, active=True, source="fault_flag", detail=f"{rule.fault_flag}=1 (drill)")
    if reading is None:
        if state.active and state.source == "fault_flag":
            return replace(state, active=False, detail=f"{rule.fault_flag} cleared")
        return state
    if not state.active and state.fail_streak >= rule.enter_after:
        return replace(state, active=True, source="probe")
    if state.active and state.ok_streak >= rule.exit_after:
        return replace(state, active=False, source="probe", detail=f"{state.ok_streak} healthy probes")
    if state.active and state.source == "fault_flag" and reading.failing:
        return replace(state, source="probe")
    return state


def evaluate(
    previous: Mapping[str, SignalState], flags: frozenset[str], readings: Sequence[Reading]
) -> dict[str, SignalState]:
    by_signal = {r.signal: r for r in readings if r.signal in RULES_BY_SIGNAL}
    return {
        rule.signal: step(
            previous.get(rule.signal, SignalState(rule.signal)),
            flagged=rule.signal in flags,
            reading=by_signal.get(rule.signal),
        )
        for rule in SIGNAL_RULES
    }
