"""Retry schedule for webhook deliveries: exponential backoff with equal jitter and a dead-letter cap.

Attempt n (1-based) that fails waits `min(cap, base * 2**(n-1))`, half of it fixed and half random, so
retries from many deliveries spread out instead of arriving in waves. After `max_attempts` failures the
delivery is dead-lettered (state `failed`) and can be replayed by an operator. A `Retry-After` from the
receiver (429/503) is honoured when it is longer than the computed delay, up to the cap.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

GONE = 410


@dataclass(frozen=True)
class RetryPolicy:
    base_s: float = 10.0
    cap_s: float = 3600.0
    max_attempts: int = 8
    jitter: Callable[[], float] = field(default=random.random, compare=False)

    def delay_s(self, attempt: int, retry_after_s: float | None = None) -> float:
        if attempt < 1:
            raise ValueError("attempt is 1-based")
        ceiling = float(min(self.cap_s, self.base_s * 2.0 ** (attempt - 1)))
        delay = ceiling / 2 + float(self.jitter()) * ceiling / 2
        if retry_after_s is not None and retry_after_s > delay:
            delay = min(self.cap_s, retry_after_s)
        return delay

    def exhausted(self, attempts: int) -> bool:
        return attempts >= self.max_attempts

    def worst_case_total_s(self) -> float:
        return float(sum(min(self.cap_s, self.base_s * 2.0 ** (n - 1)) for n in range(1, self.max_attempts)))


def outcome(status: int | None) -> str:
    """`delivered` for 2xx, `gone` for 410 (the receiver asks us to stop), else `retry`."""
    if status is not None and 200 <= status < 300:
        return "delivered"
    if status == GONE:
        return "gone"
    return "retry"


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if 0 <= seconds <= 86_400 else None
