from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from typing import Any

import httpx
from services.llm_gateway.callers import TEST_TOKENS

KEY_PREFIX = "sk-" + "ant-"
FAKE_KEY = KEY_PREFIX + "api03-" + secrets.token_urlsafe(70)[:93] + "AA"

BASE_HEADERS = {
    "x-api-key": TEST_TOKENS["cli"],
    "anthropic-version": "2023-06-01",
    "x-sgw-node": "test.narrate",
    "x-sgw-run": "run-0001",
    "x-sgw-purpose": "test",
    "x-sgw-wave": "W0",
    "x-sgw-classes": "C1",
}


def base_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "claude-sonnet-5-5",
        "max_tokens": 512,
        "output_config": {"effort": "medium"},
        "system": [{"type": "text", "text": "You brief a utility duty manager."}],
        "messages": [{"role": "user", "content": "Summarise feeder PS-17 status."}],
    }
    body.update(overrides)
    return body


def message_json(text: str = "PS-17 is de-energised.", **usage: int) -> dict[str, Any]:
    return {
        "id": "msg_fake",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("input_tokens", 100),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 20),
        },
    }


class FakeUpstream:
    def __init__(
        self, script: list[httpx.Response | Callable[[httpx.Request], httpx.Response]] | None = None
    ):
        self.script = list(script or [])
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.script:
            return httpx.Response(200, json=message_json())
        item = self.script.pop(0)
        return item(request) if callable(item) else item


def dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True)


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, payload: bytes, size: int = 37) -> None:
        self.payload = payload
        self.size = size

    async def __aiter__(self):
        for i in range(0, len(self.payload), self.size):
            yield self.payload[i : i + self.size]
