from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import anthropic
import httpx
import pytest
import uvicorn
from langchain_anthropic import ChatAnthropic
from services.llm_gateway.api import create_app
from services.llm_gateway.callers import TEST_TOKENS, token_sha256
from services.llm_gateway.config import Mode, Settings
from services.llm_gateway.sse import synthesize_events

from .gateway_testkit import BASE_HEADERS, ChunkStream, base_body

REPLY = {
    "id": "msg_sock",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-5-5",
    "content": [
        {"type": "thinking", "thinking": "", "signature": "EqQBCkYI"},
        {"type": "text", "text": "Feeder PS-17 stays locked out until patrol clears it."},
    ],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {
        "input_tokens": 40,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 12,
    },
}


def _upstream(request: httpx.Request) -> httpx.Response:
    if json.loads(request.content).get("stream"):
        payload = b"".join(synthesize_events(REPLY))
        return httpx.Response(200, stream=ChunkStream(payload), headers={"content-type": "text/event-stream"})
    return httpx.Response(200, json=REPLY)


@contextmanager
def serve(settings: Settings) -> Iterator[str]:
    app = create_app(settings, transport=httpx.MockTransport(_upstream))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("gateway did not start")
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


SGW = {k: v for k, v in BASE_HEADERS.items() if k.startswith("x-sgw-")}


@pytest.fixture
def gateways(tmp_path):
    common = {"fixture_dir": tmp_path / "fx", "spend_csv": tmp_path / "spend.csv"}
    record = Settings(
        mode=Mode.RECORD,
        api_key="placeholder-upstream-key",
        egress_pdp="reference",
        caller_token_digests=(("cli", token_sha256(TEST_TOKENS["cli"])),),
        **common,
    )
    replay = Settings(mode=Mode.REPLAY, api_key=None, accept_test_tokens=True, **common)
    with serve(record) as rec_url, serve(replay) as rep_url:
        yield rec_url, rep_url


def _sdk(url: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(base_url=url, api_key=TEST_TOKENS["cli"], max_retries=0, default_headers=SGW)


def _kwargs() -> dict:
    body = base_body()
    return {k: body[k] for k in ("model", "max_tokens", "output_config", "system", "messages")}


def test_sdk_non_stream_and_stream_through_gateway_socket(gateways):
    rec_url, rep_url = gateways
    live = _sdk(rec_url).messages.create(**_kwargs())
    assert live.content[-1].text.startswith("Feeder PS-17")
    for url in (rec_url, rep_url):
        with _sdk(url).messages.stream(**_kwargs()) as stream:
            final = stream.get_final_message()
        assert final.content[-1].text == live.content[-1].text
        assert final.usage.output_tokens == 12


def test_replay_miss_surfaces_as_typed_sdk_error(gateways):
    _, rep_url = gateways
    with pytest.raises(anthropic.APIStatusError) as exc:
        _sdk(rep_url).messages.create(**{**_kwargs(), "max_tokens": 77})
    assert exc.value.status_code == 424


def test_chat_anthropic_through_gateway_socket(gateways):
    rec_url, rep_url = gateways
    for url in (rec_url, rep_url):
        llm = ChatAnthropic(
            model="claude-sonnet-5-5",
            base_url=url,
            api_key=TEST_TOKENS["cli"],
            max_retries=0,
            max_tokens=512,
            reasoning_effort="medium",
            default_headers=SGW,
        )
        out = llm.invoke(
            [("system", "You brief a utility duty manager."), ("human", "Summarise feeder PS-17 status.")]
        )
        assert "PS-17" in out.text
        chunks = list(llm.stream([("human", "Summarise feeder PS-17 status.")]))
        assert chunks
