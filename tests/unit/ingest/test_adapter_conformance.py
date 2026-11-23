from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from sgw.contracts.adapter import Adapter, FaultKind
from sgw.contracts.conformance import check_adapter
from sgw.ingest.adapters.nws import NwsAlertsAdapter
from sgw.ingest.adapters.registry import scenario_adapters
from sgw.ingest.scenario import load_scenario

PAYLOADS = Path(__file__).resolve().parent / "payloads"
FETCH_TIME = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)


def recorded_transport(name: str) -> httpx.MockTransport:
    body = json.loads((PAYLOADS / name).read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/alerts/active"
        assert request.headers["User-Agent"]
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


def nws_recorded(name: str = "nws_alerts_active_sc_ga.json") -> NwsAlertsAdapter:
    client = httpx.Client(base_url="https://api.weather.gov", transport=recorded_transport(name))
    return NwsAlertsAdapter(client=client, clock=lambda: FETCH_TIME)


def _replay_factory(source_id: str) -> Callable[[], Adapter]:
    def make() -> Adapter:
        adapters = scenario_adapters(load_scenario("helene_micro"), page_size=7, env={})
        return next(a for a in adapters if a.source_id == source_id)

    return make


MICRO_SOURCES = sorted(load_scenario("helene_micro").by_source())
FACTORIES: dict[str, Callable[[], Adapter]] = {
    **{f"replay:{s}": _replay_factory(s) for s in MICRO_SOURCES},
    "live:nws-alerts(recorded)": nws_recorded,
}


def test_every_micro_source_has_an_adapter() -> None:
    assert {
        "oms",
        "ami-headend",
        "scada-electric",
        "scada-water",
        "fsm-crews",
        "nws-alerts",
    } <= set(MICRO_SOURCES)


@pytest.mark.parametrize("name", sorted(FACTORIES))
def test_k6_conformance(name: str) -> None:
    check_adapter(FACTORIES[name])


@pytest.mark.parametrize("name", sorted(FACTORIES))
def test_faulted_adapter_keeps_cursor_semantics(name: str) -> None:
    clean = FACTORIES[name]()
    clean_keys = _all_keys(clean)
    for kind in (FaultKind.DUPLICATE, FaultKind.OUT_OF_ORDER, FaultKind.FLOOD_10X):
        faulted = FACTORIES[name]()
        faulted.inject_fault(kind)
        assert set(_all_keys(faulted)) == set(clean_keys), kind


def _all_keys(adapter: Adapter) -> list[str]:
    keys: list[str] = []
    cursor: str | None = None
    for _ in range(1000):
        result = adapter.fetch_since(cursor)
        if not result.events and result.next_cursor == (cursor or ""):
            break
        keys.extend(e.dedup_key for e in result.events)
        if result.next_cursor == cursor or not result.events:
            break
        cursor = result.next_cursor
    return keys
