"""Prometheus metrics for the API: request rate, latency and status per route template.

`GET /metrics` is answered only for direct requests on the internal `app` network (Prometheus in the `obs`
profile). Requests relayed by Caddy always carry `X-Forwarded-For`, so the host relays get the normal 404.
Routes are labelled by their template (`/api/runs/{run_id}`), unmatched paths as `unmatched`, so label
cardinality stays bounded. SSE responses are counted but kept out of the latency histogram.
Plain text exposition format 0.0.4; no client library needed.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sgw.contracts.api_models import ApiActivity, RouteTiming

METRICS_PATH = "/metrics"
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
CONTENT_TYPE = b"text/plain; version=0.0.4; charset=utf-8"
UNMATCHED = "unmatched"
RECENT = 2000
SLOWEST = 5
KNOWN_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
OTHER_METHOD = "OTHER"


def _ms(values: list[float], q: float) -> int:
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(q * len(ordered)) - 1)] * 1000)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(pairs: dict[str, str]) -> str:
    return "{" + ",".join(f'{key}="{_escape(value)}"' for key, value in pairs.items()) + "}"


def _number(value: float) -> str:
    return "+Inf" if value == float("inf") else repr(float(value))


@dataclass
class _Histogram:
    counts: list[int] = field(default_factory=lambda: [0] * len(BUCKETS))
    total: float = 0.0
    observations: int = 0

    def observe(self, seconds: float) -> None:
        for index, bound in enumerate(BUCKETS):
            if seconds <= bound:
                self.counts[index] += 1
        self.total += seconds
        self.observations += 1


@dataclass
class ApiMetrics:
    requests: dict[tuple[str, str, str], int] = field(default_factory=lambda: defaultdict(int))
    durations: dict[tuple[str, str], _Histogram] = field(default_factory=lambda: defaultdict(_Histogram))
    in_flight: int = 0
    recent: deque[tuple[str, float]] = field(default_factory=lambda: deque(maxlen=RECENT))

    def record(self, method: str, route: str, status: int, seconds: float | None) -> None:
        method = method if method in KNOWN_METHODS else OTHER_METHOD
        self.requests[(method, route, str(status))] += 1
        if seconds is not None:
            self.durations[(method, route)].observe(seconds)
            if route != UNMATCHED:
                self.recent.append((route, seconds))

    def activity(self) -> ApiActivity:
        recent = list(self.recent)
        by_route: dict[str, list[float]] = defaultdict(list)
        for route, seconds in recent:
            by_route[route].append(seconds)
        timings = [
            RouteTiming(route=route, requests=len(v), typical_ms=_ms(v, 0.5), slow_ms=_ms(v, 0.95))
            for route, v in by_route.items()
        ]
        timings.sort(key=lambda t: (-t.slow_ms, t.route))
        every = [seconds for _, seconds in recent]
        return ApiActivity(
            requests=sum(self.requests.values()),
            server_errors=sum(n for (_, _, status), n in self.requests.items() if status.startswith("5")),
            window=len(every),
            typical_ms=_ms(every, 0.5) if every else None,
            slow_ms=_ms(every, 0.95) if every else None,
            slowest=timings[:SLOWEST],
        )

    def render(self) -> str:
        lines = [
            "# HELP sgw_http_requests_total HTTP requests handled by the API, by route template and status.",
            "# TYPE sgw_http_requests_total counter",
        ]
        for (method, route, status), count in sorted(self.requests.items()):
            labels = _labels({"method": method, "route": route, "status": status})
            lines.append(f"sgw_http_requests_total{labels} {count}")
        lines += [
            "# HELP sgw_http_request_duration_seconds API request latency (SSE streams excluded).",
            "# TYPE sgw_http_request_duration_seconds histogram",
        ]
        for (method, route), hist in sorted(self.durations.items()):
            base = {"method": method, "route": route}
            for bound, count in zip((*BUCKETS, float("inf")), (*hist.counts, hist.observations), strict=True):
                labels = _labels({**base, "le": _number(bound)})
                lines.append(f"sgw_http_request_duration_seconds_bucket{labels} {count}")
            lines.append(f"sgw_http_request_duration_seconds_sum{_labels(base)} {_number(hist.total)}")
            lines.append(f"sgw_http_request_duration_seconds_count{_labels(base)} {hist.observations}")
        lines += [
            "# HELP sgw_http_requests_in_flight API requests currently being handled.",
            "# TYPE sgw_http_requests_in_flight gauge",
            f"sgw_http_requests_in_flight {self.in_flight}",
        ]
        return "\n".join(lines) + "\n"


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else UNMATCHED


def _is_direct(scope: Scope) -> bool:
    return not any(name == b"x-forwarded-for" for name, _ in scope.get("headers") or [])


class MetricsMiddleware:
    def __init__(self, app: ASGIApp, metrics: ApiMetrics | None = None) -> None:
        self.app = app
        self.metrics = metrics or ApiMetrics()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("path") == METRICS_PATH and scope.get("method") == "GET" and _is_direct(scope):
            await self._serve(send)
            return
        status = 500
        streaming = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, streaming
            if message["type"] == "http.response.start":
                status = int(message["status"])
                for name, value in message.get("headers", []):
                    if name.lower() == b"content-type" and value.startswith(b"text/event-stream"):
                        streaming = True
            await send(message)

        started = time.perf_counter()
        self.metrics.in_flight += 1
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            self.metrics.in_flight -= 1
            elapsed = None if streaming else time.perf_counter() - started
            self.metrics.record(scope.get("method", "GET"), _route_template(scope), status, elapsed)

    async def _serve(self, send: Send) -> None:
        body = self.metrics.render().encode()
        headers = [(b"content-type", CONTENT_TYPE), (b"content-length", str(len(body)).encode())]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": body})
