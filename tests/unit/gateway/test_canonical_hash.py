from __future__ import annotations

import copy
import random

from hypothesis import given, settings
from hypothesis import strategies as st
from services.llm_gateway.canonical import request_hash

from .gateway_testkit import BASE_HEADERS, base_body


def _tool_conversation(tool_id: str, signature: str) -> dict:
    return base_body(
        messages=[
            {"role": "user", "content": "Which SOP covers feeder lockout?"},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "", "signature": signature},
                    {"type": "tool_use", "id": tool_id, "name": "search_sop", "input": {"q": "lockout"}},
                ],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": "SOP-LK-4"}],
            },
        ]
    )


def _shuffle(obj):
    if isinstance(obj, dict):
        items = list(obj.items())
        random.shuffle(items)
        return {k: _shuffle(v) for k, v in items}
    if isinstance(obj, list):
        return [_shuffle(v) for v in obj]
    return obj


def test_hash_ignores_key_order_and_volatile_headers():
    body = base_body()
    h1 = request_hash(body, BASE_HEADERS)
    volatile = {
        **BASE_HEADERS,
        "x-sgw-run": "run-9999",
        "user-agent": "Anthropic/Python 9.9",
        "x-stainless-retry-count": "3",
        "x-api-key": "other",
        "idempotency-key": "abc",
        "x-sgw-purpose": "demo",
        "x-sgw-wave": "W4",
    }
    assert request_hash(_shuffle(copy.deepcopy(body)), volatile) == h1


def test_hash_ignores_stream_flag_and_metadata():
    body = base_body()
    assert request_hash(
        {**body, "stream": True, "metadata": {"user_id": "u-1"}}, BASE_HEADERS
    ) == request_hash(body, BASE_HEADERS)


def test_hash_normalises_tool_ids_and_thinking_signatures():
    a = _tool_conversation("toolu_01AAA", "sigA")
    b = _tool_conversation("toolu_01ZZZ", "sigB")
    assert request_hash(a, BASE_HEADERS) == request_hash(b, BASE_HEADERS)


def test_hash_changes_with_semantic_fields():
    body = base_body()
    h = request_hash(body, BASE_HEADERS)
    assert request_hash({**body, "model": "claude-haiku-5-5"}, BASE_HEADERS) != h
    assert request_hash({**body, "output_config": {"effort": "high"}}, BASE_HEADERS) != h
    assert request_hash({**body, "max_tokens": 513}, BASE_HEADERS) != h
    assert request_hash(body, {**BASE_HEADERS, "x-sgw-prompt-version": "narrate@2"}) != h
    assert request_hash(body, {**BASE_HEADERS, "x-sgw-node": "test.other"}) != h
    assert request_hash(body, {**BASE_HEADERS, "anthropic-beta": "x-2026"}) != h


def test_beta_header_order_is_irrelevant():
    body = base_body()
    assert request_hash(body, {**BASE_HEADERS, "anthropic-beta": "b,a"}) == request_hash(
        body, {**BASE_HEADERS, "anthropic-beta": "a, b"}
    )


def test_hash_is_pinned_across_processes():
    assert request_hash(base_body(), BASE_HEADERS) == (
        "32d6ffdaae7236cf4efac4f4bc92908a05fcee062f1d0c3f2d542387a23890f4"
    )


@settings(max_examples=50, deadline=None)
@given(text=st.text(min_size=1, max_size=200), run=st.text(max_size=20))
def test_hash_stable_property(text: str, run: str):
    body = base_body(messages=[{"role": "user", "content": text}])
    assert request_hash(body, BASE_HEADERS) == request_hash(
        _shuffle(copy.deepcopy(body)), {**BASE_HEADERS, "x-sgw-run": run}
    )
