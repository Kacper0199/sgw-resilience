"""Platform control gate: before every model call the gateway reads the kill level
and the degraded mode from `control_state` and refuses at K2 or above and in M2 or above, so the agent nodes
take their template path. The row is read through `SGW_LLM_CALL_DSN` (role `sgw_llm_writer`, SELECT granted by
migration 5001) and cached for one second. A row that cannot be read refuses the call (fail closed); without a
DSN (unit tests, a laptop replay gateway) the gate is open."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

import psycopg

from .policy import PolicyViolation

LLM_DISABLED_CODE = "sgw_llm_disabled"
CACHE_S = 1.0
KILL_STOPS_AI = 2
MODE_STOPS_AI = 2


@dataclass(frozen=True)
class ControlReading:
    kill_level: str
    degraded_mode: str

    @property
    def llm_allowed(self) -> bool:
        return int(self.kill_level[1:]) < KILL_STOPS_AI and int(self.degraded_mode[1:]) < MODE_STOPS_AI


class ControlGate(Protocol):
    def check(self) -> None: ...


class OpenGate:
    def check(self) -> None:
        return None


def refuse(reason: str) -> PolicyViolation:
    return PolicyViolation(LLM_DISABLED_CODE, f"LLM calls are off: {reason}; use the template path", 503)


@dataclass
class DbControlGate:
    dsn: str
    cache_s: float = CACHE_S
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _cached: tuple[float, ControlReading | None] | None = None

    def read(self) -> ControlReading | None:
        now = time.monotonic()
        with self._lock:
            if self._cached is not None and now - self._cached[0] < self.cache_s:
                return self._cached[1]
        try:
            with psycopg.connect(self.dsn, autocommit=True, connect_timeout=2) as conn:
                row = conn.execute(
                    "SELECT kill_level, degraded_mode FROM control_state WHERE id = 1"
                ).fetchone()
            reading = ControlReading(str(row[0]), str(row[1])) if row else None
        except psycopg.Error:
            reading = None
        with self._lock:
            self._cached = (now, reading)
        return reading

    def check(self) -> None:
        reading = self.read()
        if reading is None:
            raise refuse("the control state cannot be read")
        if not reading.llm_allowed:
            raise refuse(f"kill level {reading.kill_level}, degraded mode {reading.degraded_mode}")


def make_gate(dsn: str | None) -> ControlGate:
    return DbControlGate(dsn) if dsn else OpenGate()
