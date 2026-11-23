"""SEC-30 (STM 6.4, egress): a C3 or C4 item in the context of a call on route R1 or R2 is denied before any
network request. Checked through the gateway's HTTP route in live, record and replay mode, with the Python
reference policy and with `policy/egress.rego` on a pinned OPA; a recording that matches the request is not
served; an unreachable policy engine denies too. Every denial leaves an `llm_call` row with decision deny."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from services.llm_gateway.api import create_app
from services.llm_gateway.calls import MemorySink
from services.llm_gateway.canonical import canonical_request, request_hash
from services.llm_gateway.config import Mode, Settings
from services.llm_gateway.recording import Recording, RecordingStore
from services.llm_gateway.testkit import must_run_opa, opa_server
from tests.unit.gateway.gateway_testkit import BASE_HEADERS, FAKE_KEY, FakeUpstream, base_body, message_json

NO_OPA = "no OPA: set SGW_TEST_OPA_URL or start docker"
RESTRICTED = ("C3", "C3-N", "C4", "CX")
NODES = "nodes:\n  test.narrate:\n    models: [claude-sonnet-5-5]\n    class_ceiling: CX\n"


@pytest.fixture(scope="module")
def opa_url() -> Iterator[str]:
    with opa_server() as url:
        if url is None and must_run_opa():
            pytest.fail(f"{NO_OPA} (CI must run the OPA egress tests)")
        if url is None:
            pytest.skip(NO_OPA)  # sgw-allow-skip: OPA variant needs docker or SGW_TEST_OPA_URL
        yield url


def _settings(tmp_path: Path, mode: Mode, route: str, opa: str | None) -> Settings:
    nodes = tmp_path / "nodes.yaml"
    nodes.write_text(NODES)
    return Settings(
        accept_test_tokens=True,
        mode=mode,
        fixture_dir=tmp_path / "fixtures",
        spend_csv=tmp_path / "spend.csv",
        nodes_file=nodes,
        api_key=FAKE_KEY if mode is not Mode.REPLAY else None,
        upstream_base_url="https://upstream.invalid",
        allow_test_upstream=True,
        egress_route=route,
        opa_url=opa,
        egress_pdp="opa" if opa else "reference",
    )


def _client(settings: Settings, upstream: FakeUpstream, sink: MemorySink) -> httpx.AsyncClient:
    app = create_app(settings, transport=httpx.MockTransport(upstream), sink=sink)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")


def _seed_recording(settings: Settings, body: dict[str, Any], headers: dict[str, str]) -> None:
    lower = {k.lower(): v for k, v in headers.items()}
    canonical = canonical_request(body, lower)
    RecordingStore(settings.fixture_dir).save(
        Recording(
            node="test.narrate",
            request_sha256=request_hash(body, lower),
            prompt_version=None,
            model=body["model"],
            data_classes=["C1"],
            request=canonical["body"],
            request_headers=canonical["headers"],
            response=message_json("restricted plan"),
            cost_usd_at_record=0.0,
            latency_ms=1,
            recorded_at="2026-11-19T23:00:00Z",
        )
    )


async def _assert_denied(settings: Settings, label: str) -> None:
    upstream, sink = FakeUpstream(), MemorySink()
    headers = {**BASE_HEADERS, "x-sgw-classes": f"C1,{label}", "x-sgw-purpose": "dev"}
    body = base_body()
    if settings.mode is not Mode.LIVE:
        _seed_recording(settings, body, headers)
    async with _client(settings, upstream, sink) as client:
        r = await client.post("/v1/messages", json=body, headers=headers)
    assert r.status_code == 403, r.text
    assert r.json()["error"]["type"] == "sgw_class_denied"
    assert r.headers["x-sgw-egress"] == "deny"
    assert "restricted plan" not in r.text
    assert upstream.requests == []
    assert not settings.spend_csv.exists()
    [row] = sink.records
    assert (row.decision, row.stop_reason, row.billed, row.route) == (
        "deny",
        "sgw_class_denied",
        False,
        settings.egress_route,
    )
    assert label in row.classes and row.call_id == r.headers["x-sgw-call-id"]


@pytest.mark.parametrize("label", RESTRICTED)
@pytest.mark.parametrize("route", ["R1", "R2"])
@pytest.mark.parametrize("mode", [Mode.LIVE, Mode.RECORD, Mode.REPLAY])
async def test_sec_30_restricted_class_denied_before_egress_reference(tmp_path, mode, route, label):
    await _assert_denied(_settings(tmp_path, mode, route, None), label)


@pytest.mark.slow
@pytest.mark.parametrize("label", RESTRICTED)
@pytest.mark.parametrize("route", ["R1", "R2"])
@pytest.mark.parametrize("mode", [Mode.LIVE, Mode.REPLAY])
async def test_sec_30_restricted_class_denied_before_egress_opa(tmp_path, opa_url, mode, route, label):
    await _assert_denied(_settings(tmp_path, mode, route, opa_url), label)


async def test_sec_30_c1_still_allowed_so_the_gate_is_not_a_blanket_deny(tmp_path):
    upstream, sink = FakeUpstream(), MemorySink()
    settings = _settings(tmp_path, Mode.LIVE, "R1", None)
    async with _client(settings, upstream, sink) as client:
        r = await client.post(
            "/v1/messages", json=base_body(), headers={**BASE_HEADERS, "x-sgw-purpose": "dev"}
        )
    assert r.status_code == 200 and r.headers["x-sgw-egress"] == "allow"
    assert len(upstream.requests) == 1 and sink.records[0].decision == "allow"


async def test_sec_30_unreachable_policy_engine_denies_before_egress(tmp_path):
    upstream, sink = FakeUpstream(), MemorySink()
    settings = _settings(tmp_path, Mode.LIVE, "R1", "http://127.0.0.1:9")
    async with _client(settings, upstream, sink) as client:
        r = await client.post(
            "/v1/messages", json=base_body(), headers={**BASE_HEADERS, "x-sgw-purpose": "dev"}
        )
    assert r.status_code == 503 and r.json()["error"]["type"] == "sgw_egress_policy_unavailable"
    assert upstream.requests == [] and sink.records[0].decision == "deny"


def test_sec_30_live_against_the_real_api_requires_opa(tmp_path):
    with pytest.raises(ValueError, match="OPA"):
        Settings(mode=Mode.LIVE, fixture_dir=tmp_path, spend_csv=tmp_path / "s.csv")
