"""In-process token buckets for login and step-up attempts (per client IP and per user id)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class _Bucket:
    tokens: float
    updated: float


@dataclass
class TokenBuckets:
    capacity: float
    refill_per_s: float
    clock: Callable[[], float] = time.monotonic
    max_keys: int = 50_000
    _buckets: dict[str, _Bucket] = field(default_factory=dict)

    def take(self, key: str) -> float:
        """Spend one token; returns 0 when allowed, else the seconds until the next token."""
        now = self.clock()
        b = self._buckets.get(key)
        if b is None:
            if len(self._buckets) >= self.max_keys:
                self._prune(now)
            b = self._buckets[key] = _Bucket(self.capacity, now)
        b.tokens = min(self.capacity, b.tokens + (now - b.updated) * self.refill_per_s)
        b.updated = now
        if b.tokens >= 1.0:
            b.tokens -= 1.0
            return 0.0
        return (1.0 - b.tokens) / self.refill_per_s

    def _prune(self, now: float) -> None:
        full = [
            k
            for k, b in self._buckets.items()
            if b.tokens + (now - b.updated) * self.refill_per_s >= self.capacity
        ]
        for k in full:
            del self._buckets[k]
        if len(self._buckets) >= self.max_keys:
            self._buckets.clear()


@dataclass
class LoginLimiter:
    per_ip: TokenBuckets
    per_user: TokenBuckets

    def check(self, ip: str, user_id: str) -> float:
        """Seconds to wait (0 = allowed). Both buckets are charged, so neither key can be used to bypass."""
        wait_ip = self.per_ip.take(f"ip:{ip}")
        wait_user = self.per_user.take(f"user:{user_id[:64]}")
        return max(wait_ip, wait_user)
