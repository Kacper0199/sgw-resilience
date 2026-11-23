from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from sgw.api.app import app_routes, create_app
from sgw.api.metrics import ApiMetrics, MetricsMiddleware
from sgw.api.settings import ApiSettings


def _client() -> tuple[TestClient, ApiMetrics]:
    app = FastAPI()

    @app.get("/api/runs/{run_id}")
    def run(run_id: str) -> dict[str, str]:
        return {"run": run_id}

    @app.get("/api/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    @app.get("/api/stream")
    def stream() -> StreamingResponse:
        return StreamingResponse(iter([b"data: x\n\n"]), media_type="text/event-stream")

    metrics = ApiMetrics()
    app.add_middleware(MetricsMiddleware, metrics=metrics)
    return TestClient(app, raise_server_exceptions=False), metrics


def _value(text: str, series: str) -> float:
    match = re.search(rf"^{re.escape(series)} (\S+)$", text, re.MULTILINE)
    assert match, f"{series} missing in:\n{text}"
    return float(match.group(1))


def test_requests_are_labelled_by_route_template_not_raw_path() -> None:
    client, _ = _client()
    for run_id in ("a", "b", "c"):
        assert client.get(f"/api/runs/{run_id}").status_code == 200
    client.get("/nowhere/123")
    text = client.get("/metrics").text
    assert _value(text, 'sgw_http_requests_total{method="GET",route="/api/runs/{run_id}",status="200"}') == 3
    assert _value(text, 'sgw_http_requests_total{method="GET",route="unmatched",status="404"}') == 1
    assert "/api/runs/a" not in text and "/nowhere/123" not in text
    count = 'sgw_http_request_duration_seconds_count{method="GET",route="/api/runs/{run_id}"}'
    inf = 'sgw_http_request_duration_seconds_bucket{method="GET",route="/api/runs/{run_id}",le="+Inf"}'
    assert _value(text, count) == _value(text, inf) == 3


def test_server_errors_are_counted_as_500() -> None:
    client, _ = _client()
    assert client.get("/api/boom").status_code == 500
    text = client.get("/metrics").text
    assert _value(text, 'sgw_http_requests_total{method="GET",route="/api/boom",status="500"}') == 1


def test_sse_streams_are_counted_but_not_timed() -> None:
    client, _ = _client()
    client.get("/api/stream")
    text = client.get("/metrics").text
    assert _value(text, 'sgw_http_requests_total{method="GET",route="/api/stream",status="200"}') == 1
    assert 'route="/api/stream",le=' not in text


def test_metrics_are_refused_through_the_caddy_relay() -> None:
    client, _ = _client()
    relayed = client.get("/metrics", headers={"X-Forwarded-For": "127.0.0.1"})
    assert relayed.status_code == 404
    direct = client.get("/metrics")
    assert direct.status_code == 200
    assert direct.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert "sgw_http_requests_in_flight 0" in direct.text


def test_histogram_buckets_are_cumulative() -> None:
    metrics = ApiMetrics()
    for seconds in (0.001, 0.02, 0.3, 20.0):
        metrics.record("GET", "/x", 200, seconds)
    text = metrics.render()
    assert _value(text, 'sgw_http_request_duration_seconds_bucket{method="GET",route="/x",le="0.005"}') == 1
    assert _value(text, 'sgw_http_request_duration_seconds_bucket{method="GET",route="/x",le="0.025"}') == 2
    assert _value(text, 'sgw_http_request_duration_seconds_bucket{method="GET",route="/x",le="10.0"}') == 3
    assert _value(text, 'sgw_http_request_duration_seconds_bucket{method="GET",route="/x",le="+Inf"}') == 4


def test_api_app_carries_the_middleware_without_a_contract_route() -> None:
    app = create_app(ApiSettings(database_url="postgresql://unused/unused", demo_mode=True))
    assert any(m.cls is MetricsMiddleware for m in app.user_middleware)
    assert ("GET", "/metrics") not in app_routes(app)


def test_unknown_methods_collapse_into_one_label() -> None:
    metrics = ApiMetrics()
    for i in range(50):
        metrics.record(f"X{i}", "unmatched", 405, 0.001)
    text = metrics.render()
    assert len(metrics.requests) == 1 and len(metrics.durations) == 1
    assert _value(text, 'sgw_http_requests_total{method="OTHER",route="unmatched",status="405"}') == 50
    assert "X1" not in text


def test_client_sent_methods_through_the_app_are_bounded() -> None:
    client, metrics = _client()
    for verb in ("BREW", "PROPFIND", "WHATEVER"):
        client.request(verb, "/api/runs/a")
    assert {key[0] for key in metrics.requests} == {"OTHER"}


def test_activity_counts_requests_errors_and_times_per_route() -> None:
    metrics = ApiMetrics()
    assert metrics.activity().typical_ms is None
    for ms in range(1, 101):
        metrics.record("GET", "/api/fast", 200, ms / 10_000)
    metrics.record("GET", "/api/slow", 500, 0.8)
    metrics.record("GET", "/api/stream", 200, None)
    metrics.record("GET", "unmatched", 404, 0.001)
    activity = metrics.activity()
    assert activity.requests == 103
    assert activity.server_errors == 1
    assert activity.window == 101
    assert activity.typical_ms == 5
    assert activity.slowest[0].route == "/api/slow" and activity.slowest[0].slow_ms == 800
    fast = activity.slowest[1]
    assert (fast.route, fast.requests, fast.typical_ms, fast.slow_ms) == ("/api/fast", 100, 5, 10)
