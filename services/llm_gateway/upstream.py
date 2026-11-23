from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

from .config import Settings
from .policy import PolicyViolation

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 529})
FORWARDED_HEADERS = ("anthropic-version", "anthropic-beta")
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
PRE_SEND_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


class UpstreamPostSendError(Exception):
    """The request body may have reached the API (read timeout, dropped connection): never retried."""

    def __init__(self, attempts: int, cause: Exception) -> None:
        super().__init__(f"{type(cause).__name__} after the request was sent (attempt {attempts})")
        self.attempts = attempts
        self.cause = cause


@dataclass
class CircuitBreaker:
    threshold: int
    cooldown_s: float
    clock: Callable[[], float] = time.monotonic
    state: str = "closed"
    failures: int = 0
    opened_at: float = 0.0
    generation: int = 0
    probe_in_flight: bool = field(default=False)

    def acquire(self) -> int:
        if self.state == "open":
            if self.clock() - self.opened_at < self.cooldown_s:
                raise PolicyViolation("sgw_breaker_open", "upstream breaker is open", 503)
            self.state = "half_open"
            self.generation += 1
            self.probe_in_flight = False
        if self.state == "half_open":
            if self.probe_in_flight:
                raise PolicyViolation("sgw_breaker_half_open", "a probe request is already in flight", 503)
            self.probe_in_flight = True
        return self.generation

    def snapshot(self) -> dict[str, object]:
        retry_in = 0.0
        if self.state == "open":
            retry_in = max(0.0, round(self.cooldown_s - (self.clock() - self.opened_at), 3))
        return {
            "state": self.state,
            "consecutive_failures": self.failures,
            "threshold": self.threshold,
            "cooldown_s": self.cooldown_s,
            "retry_in_s": retry_in,
            "probe_in_flight": self.probe_in_flight,
        }

    def end_attempt(self, generation: int) -> None:
        if generation == self.generation and self.state == "half_open":
            self.probe_in_flight = False

    def success(self, generation: int) -> None:
        if generation != self.generation:
            return
        self.state = "closed"
        self.failures = 0
        self.probe_in_flight = False

    def failure(self, generation: int) -> None:
        if generation != self.generation:
            return
        self.failures += 1
        if self.state == "half_open" or self.failures >= self.threshold:
            self.state = "open"
            self.opened_at = self.clock()
            self.generation += 1
            self.probe_in_flight = False


@dataclass
class UpstreamResult:
    response: httpx.Response
    attempts: int


class Upstream:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._sleep = sleep
        self._clock = clock
        self.breaker = CircuitBreaker(settings.breaker_threshold, settings.breaker_cooldown_s, clock=clock)
        self.client = httpx.AsyncClient(
            base_url=settings.upstream_base_url,
            transport=transport,
            timeout=httpx.Timeout(settings.attempt_timeout_s, connect=10.0),
            trust_env=False,
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    def _headers(self, client_headers: dict[str, str]) -> dict[str, str]:
        if not self.settings.api_key:
            raise PolicyViolation("sgw_no_key", "gateway has no ANTHROPIC_API_KEY for a live call", 503)
        lower = {k.lower(): v for k, v in client_headers.items()}
        out = {
            "content-type": "application/json",
            "accept-encoding": "identity",
            "x-api-key": self.settings.api_key,
        }
        out["anthropic-version"] = lower.get("anthropic-version", DEFAULT_ANTHROPIC_VERSION)
        if lower.get("anthropic-beta"):
            out["anthropic-beta"] = lower["anthropic-beta"]
        return out

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        cap = min(self.settings.backoff_max_s, self.settings.backoff_base_s * (2**attempt))
        delay = random.uniform(0, cap)  # noqa: S311
        if retry_after:
            with contextlib.suppress(ValueError):
                delay = max(delay, float(retry_after))
        return delay

    async def send(
        self, body: bytes, client_headers: dict[str, str], *, stream: bool, deadline_s: float
    ) -> UpstreamResult:
        headers = self._headers(client_headers)
        start = self._clock()
        attempt = 0
        last_exc: Exception | None = None
        while True:
            generation = self.breaker.acquire()
            attempt += 1
            response: httpx.Response | None = None
            try:
                request = self.client.build_request("POST", "/v1/messages", content=body, headers=headers)
                response = await self.client.send(request, stream=stream)
            except PRE_SEND_ERRORS as exc:
                last_exc = exc
                self.breaker.failure(generation)
            except httpx.TransportError as exc:
                self.breaker.failure(generation)
                raise UpstreamPostSendError(attempt, exc) from exc
            else:
                if response.status_code not in RETRY_STATUSES:
                    if response.status_code < 500:
                        self.breaker.success(generation)
                    else:
                        self.breaker.failure(generation)
                    return UpstreamResult(response, attempt)
                self.breaker.failure(generation)
            finally:
                self.breaker.end_attempt(generation)
            remaining = deadline_s - (self._clock() - start)
            retry_after = response.headers.get("retry-after") if response is not None else None
            delay = self._backoff(attempt - 1, retry_after)
            if attempt >= self.settings.max_attempts or delay >= remaining:
                if response is not None:
                    if stream:
                        await response.aread()
                    return UpstreamResult(response, attempt)
                raise PolicyViolation(
                    "sgw_upstream_unreachable",
                    f"upstream unreachable after {attempt} attempts: {type(last_exc).__name__}",
                    502,
                )
            if response is not None:
                await response.aclose()
            await self._sleep(delay)
