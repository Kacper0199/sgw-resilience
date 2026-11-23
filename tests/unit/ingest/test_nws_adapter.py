from __future__ import annotations

import httpx
import pytest

from sgw.contracts.vocab import FeedMode, UiSeverity
from sgw.ingest.adapters.nws import AdapterFetchError, NwsAlertsAdapter, alert_event_id, decode_cursor

from .test_adapter_conformance import FETCH_TIME, nws_recorded


def test_cap_properties_map_to_weather_alert() -> None:
    events = nws_recorded().fetch_since(None).events
    assert [e.payload.event_name for e in events] == [  # type: ignore[attr-defined]
        "Tropical Storm Watch",
        "Tropical Storm Warning",
        "Flash Flood Warning",
    ]
    watch, warning, flood = events
    assert watch.payload.product == "watch" and watch.payload.severity is UiSeverity.ELEVATED  # type: ignore[attr-defined]
    assert warning.supersedes == watch.event_id == alert_event_id(watch.payload.alert_id)  # type: ignore[attr-defined]
    assert flood.payload.severity is UiSeverity.CRITICAL  # type: ignore[attr-defined]
    assert flood.payload.expires_utc.hour == 12  # type: ignore[attr-defined]
    assert watch.payload.area_fips == ["13245", "45003"]  # type: ignore[attr-defined]
    assert watch.region_id == "GA-13245"
    assert all(e.feed_mode is FeedMode.LIVE and e.known_at == FETCH_TIME for e in events)


def test_cursor_returns_only_new_alerts() -> None:
    adapter = nws_recorded()
    first = adapter.fetch_since(None)
    sent, ids = decode_cursor(first.next_cursor)
    assert sent is not None and sent.hour == 15 and len(ids) == 1
    assert adapter.fetch_since(first.next_cursor).events == []


def test_malformed_alert_is_rejected_not_fatal() -> None:
    adapter = nws_recorded("nws_alerts_active_malformed.json")
    result = adapter.fetch_since(None)
    assert len(result.events) == 3
    assert not result.coverage.complete
    rejects = adapter.drain_rejects()
    assert len(rejects) == 1 and rejects[0].reason.startswith("mapping:")


@pytest.mark.parametrize("status", [429, 503])
def test_http_failure_raises_and_counts_in_health(status: int) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={"title": "busy"}))
    adapter = NwsAlertsAdapter(
        client=httpx.Client(base_url="https://api.weather.gov", transport=transport), clock=lambda: FETCH_TIME
    )
    with pytest.raises(AdapterFetchError):
        adapter.fetch_since(None)
    assert adapter.health().error_rate_ppm == 1_000_000
    assert adapter.health().last_success_at is None


def test_payload_without_features_is_an_error() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"type": "FeatureCollection"}))
    adapter = NwsAlertsAdapter(client=httpx.Client(base_url="https://api.weather.gov", transport=transport))
    with pytest.raises(AdapterFetchError, match="features"):
        adapter.fetch_since(None)


def _serve(features: list[object]) -> NwsAlertsAdapter:
    body = {"type": "FeatureCollection", "features": features}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    client = httpx.Client(base_url="https://api.weather.gov", transport=transport)
    return NwsAlertsAdapter(client=client, clock=lambda: FETCH_TIME)


def _good(alert_id: str, **overrides: object) -> dict[str, object]:
    props: dict[str, object] = {
        "id": alert_id,
        "sent": "2024-09-26T03:00:00+00:00",
        "effective": "2024-09-26T03:00:00+00:00",
        "expires": "2024-09-26T21:00:00+00:00",
        "event": "Tropical Storm Watch",
        "severity": "Moderate",
        "geocode": {"SAME": ["045003"]},
    }
    props.update(overrides)
    return {"type": "Feature", "properties": props}


def test_hostile_cap_shapes_are_rejected_or_tolerated_never_fatal() -> None:
    features: list[object] = [
        _good("urn:bad:geocode-null", geocode=None),
        _good("urn:ok:refs-string", references="urn:x"),
        _good("urn:ok:refs-empty-object", references=[{}]),
        _good("urn:ok:refs-dict", references={}),
        _good("urn:ok:event-number", event=7, headline=["x"]),
        _good("urn:bad:sent-number", sent=1727319600),
        _good("urn:bad:sent-naive", sent="2024-09-26T03:00:00"),
        {"type": "Feature", "properties": ["not", "a", "dict"]},
        ["not", "a", "feature"],
        "plain string",
        _good("", id=12345),
    ]
    adapter = _serve(features)
    result = adapter.fetch_since(None)
    accepted = sorted(e.payload.alert_id for e in result.events)  # type: ignore[attr-defined]
    assert accepted == [
        "urn:ok:event-number",
        "urn:ok:refs-dict",
        "urn:ok:refs-empty-object",
        "urn:ok:refs-string",
    ]
    assert all(e.supersedes is None for e in result.events)
    rejects = adapter.drain_rejects()
    assert len(rejects) == 7
    assert all(r.reason.startswith("mapping:") and isinstance(r.record, dict) for r in rejects)
    assert not result.coverage.complete
