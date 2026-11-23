from __future__ import annotations

import json

import httpx
from services.llm_gateway.config import Mode
from services.llm_gateway.sse import synthesize_events

from .gateway_testkit import BASE_HEADERS, ChunkStream, FakeUpstream, base_body, message_json


async def test_record_then_replay_roundtrip(client_factory, tmp_path):
    client, _ = client_factory(mode=Mode.RECORD)
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 200, r.text
    req_hash = r.headers["x-sgw-request-hash"]
    fixture = tmp_path / "fixtures" / "test.narrate" / f"{req_hash}.json"
    assert fixture.is_file()
    data = json.loads(fixture.read_text())
    assert data["format"] == "sgw.llm_recording/v1"
    assert data["request"]["model"] == "claude-sonnet-5-5"

    replay, _ = client_factory(upstream=FakeUpstream([httpx.Response(500)]), mode=Mode.REPLAY, api_key=None)
    r2 = await replay.post("/v1/messages", json=base_body(), headers={**BASE_HEADERS, "x-sgw-run": "other"})
    assert r2.status_code == 200
    assert r2.headers["x-sgw-replay"] == "hit"
    assert r2.json()["content"][0]["text"] == "PS-17 is de-energised."


async def test_replay_miss_fails_loudly(client_factory):
    upstream = FakeUpstream()
    client, app = client_factory(upstream=upstream, mode=Mode.REPLAY, api_key=None)
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 424
    assert r.json()["error"]["type"] == "sgw_replay_miss"
    assert upstream.requests == []
    assert app.state.gateway.counters["replay_misses"] == 1


async def test_replay_stream_synthesises_sse(client_factory):
    rec, _ = client_factory(mode=Mode.RECORD)
    await rec.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    replay, _ = client_factory(mode=Mode.REPLAY, api_key=None)
    r = await replay.post("/v1/messages", json={**base_body(), "stream": True}, headers=BASE_HEADERS)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    names = [line.split(": ", 1)[1] for line in r.text.splitlines() if line.startswith("event: ")]
    assert names[0] == "message_start" and names[-1] == "message_stop"
    assert "content_block_delta" in names


async def test_live_stream_is_proxied_and_accounted(client_factory, tmp_path):
    payload = b"".join(synthesize_events(message_json("streamed", output_tokens=7)))
    upstream = FakeUpstream(
        [httpx.Response(200, stream=ChunkStream(payload), headers={"content-type": "text/event-stream"})]
    )
    client, app = client_factory(upstream=upstream, mode=Mode.RECORD)
    r = await client.post("/v1/messages", json={**base_body(), "stream": True}, headers=BASE_HEADERS)
    assert r.status_code == 200
    assert r.content == payload
    rows = app.state.gateway.ledger.rows()
    assert rows[-1]["output_tokens"] == "7" and rows[-1]["billed"] == "True"
    assert list((tmp_path / "fixtures" / "test.narrate").glob("*.json"))


async def test_retries_owned_by_gateway(client_factory):
    upstream = FakeUpstream(
        [
            httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error"}}),
            httpx.Response(429, headers={"retry-after": "0"}, json={"type": "error"}),
            httpx.Response(200, json=message_json()),
        ]
    )
    client, _ = client_factory(upstream=upstream)
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 200
    assert r.headers["x-sgw-attempts"] == "3"
    assert len(upstream.requests) == 3


async def test_non_retryable_400_passes_through_once(client_factory):
    err = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}
    upstream = FakeUpstream([httpx.Response(400, json=err)])
    client, app = client_factory(upstream=upstream)
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 400 and r.json() == err
    assert len(upstream.requests) == 1
    assert app.state.gateway.ledger.rows()[-1]["billed"] == "False"


async def test_retries_stop_at_max_attempts(client_factory):
    upstream = FakeUpstream([httpx.Response(503)] * 10)
    client, _ = client_factory(upstream=upstream, max_attempts=3)
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 503
    assert len(upstream.requests) == 3


async def test_retry_respects_deadline(client_factory):
    upstream = FakeUpstream([httpx.Response(429, headers={"retry-after": "30"})] * 5)
    client, _ = client_factory(upstream=upstream)
    r = await client.post("/v1/messages", json=base_body(), headers={**BASE_HEADERS, "x-sgw-deadline-s": "5"})
    assert r.status_code == 429
    assert len(upstream.requests) == 1


async def test_breaker_opens_after_repeated_failures(client_factory):
    upstream = FakeUpstream([httpx.Response(500)] * 20)
    client, app = client_factory(upstream=upstream, max_attempts=2, breaker_threshold=4)
    for _ in range(2):
        await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert app.state.gateway.upstream.breaker.state == "open"
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 503 and r.json()["error"]["type"] == "sgw_breaker_open"
    assert len(upstream.requests) == 4


async def test_sdk_key_never_forwarded_gateway_key_used(client_factory):
    from .gateway_testkit import FAKE_KEY

    upstream = FakeUpstream()
    client, _ = client_factory(upstream=upstream)
    await client.post("/v1/messages", json=base_body(), headers={**BASE_HEADERS, "x-sgw-classes": "C0"})
    sent = upstream.requests[0]
    assert sent.headers["x-api-key"] == FAKE_KEY
    assert not any(k.startswith("x-sgw-") for k in sent.headers)
    assert "x-stainless" not in " ".join(sent.headers)


async def test_c3_denied_before_any_egress(client_factory):
    upstream = FakeUpstream()
    client, _ = client_factory(upstream=upstream)
    r = await client.post(
        "/v1/messages", json=base_body(), headers={**BASE_HEADERS, "x-sgw-classes": "C1,C3"}
    )
    assert r.status_code == 403 and r.json()["error"]["type"] == "sgw_class_denied"
    assert upstream.requests == []


async def test_c2_denied_on_r1_and_recorded_without_verbatim_request_on_r2(client_factory, tmp_path):
    upstream = FakeUpstream()
    client, _ = client_factory(upstream=upstream)
    r = await client.post("/v1/messages", json=base_body(), headers={**BASE_HEADERS, "x-sgw-classes": "C2"})
    assert r.status_code == 403 and r.json()["error"]["type"] == "sgw_class_denied"
    assert upstream.requests == []
    nodes = tmp_path / "nodes.yaml"
    nodes.write_text(
        "nodes:\n  test.narrate:\n    models: [claude-sonnet-5-5]\n"
        "    class_ceiling: C2\n    routes: [R1, R2]\n"
    )
    callers = tmp_path / "callers.yaml"
    callers.write_text("services:\n  cli:\n    may_send_c2: true\n    nodes: ['*']\n")
    client, _ = client_factory(egress_route="R2", nodes_file=nodes, callers_file=callers)
    headers = {**BASE_HEADERS, "x-sgw-classes": "C2", "x-sgw-pseudonymized": "1"}
    r = await client.post("/v1/messages", json=base_body(), headers=headers)
    data = json.loads(
        (tmp_path / "fixtures" / "test.narrate" / f"{r.headers['x-sgw-request-hash']}.json").read_text()
    )
    assert data["request"] is None and data["request_redacted"] is True


async def test_unknown_node_and_disallowed_model(client_factory):
    client, _ = client_factory()
    r = await client.post("/v1/messages", json=base_body(), headers={**BASE_HEADERS, "x-sgw-node": "narrate"})
    assert r.json()["error"]["type"] == "sgw_node_not_allowed"
    r = await client.post("/v1/messages", json=base_body(model="claude-opus-5-5"), headers=BASE_HEADERS)
    assert r.status_code == 403 and r.json()["error"]["type"] == "sgw_model_not_allowed"


async def test_missing_tags_rejected(client_factory):
    client, _ = client_factory()
    headers = {k: v for k, v in BASE_HEADERS.items() if k != "x-sgw-wave"}
    r = await client.post("/v1/messages", json=base_body(), headers=headers)
    assert r.status_code == 400 and r.json()["error"]["type"] == "sgw_wave"


async def test_soft_stop_and_ack(client_factory, settings_factory):
    upstream = FakeUpstream([httpx.Response(200, json=message_json(output_tokens=2_000_000))] + [None] * 0)
    client, app = client_factory(
        upstream=upstream,
        soft_stop_usd=1.0,
        hard_stop_usd=50.0,
        admin_token="maintainer-token",  # noqa: S106
    )
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 200
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 402 and r.json()["error"]["type"] == "sgw_budget_soft_stop"
    denied = await client.post("/budget/ack", json={"ack_usd": 1.0}, headers={"x-sgw-admin-token": "nope"})
    assert denied.status_code == 403
    ok = await client.post(
        "/budget/ack", json={"ack_usd": 1.0}, headers={"x-sgw-admin-token": "maintainer-token"}
    )
    assert ok.status_code == 200
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 200


async def test_hard_stop_is_not_ackable(client_factory):
    upstream = FakeUpstream([httpx.Response(200, json=message_json(output_tokens=3_000_000))])
    client, _ = client_factory(upstream=upstream, soft_stop_usd=10.0, hard_stop_usd=20.0, budget_ack_usd=10.0)
    await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 402 and r.json()["error"]["type"] == "sgw_budget_hard_stop"


async def test_balance_floor(client_factory):
    client, _ = client_factory(console_balance_usd=100.0)
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 402 and r.json()["error"]["type"] == "sgw_balance_floor"


async def test_wave_cap_calls(client_factory):
    client, _ = client_factory(wave_cap_calls=2)
    for _ in range(2):
        assert (await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)).status_code == 200
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.json()["error"]["type"] == "sgw_wave_cap_calls"
    other = await client.post("/v1/messages", json=base_body(), headers={**BASE_HEADERS, "x-sgw-wave": "W1"})
    assert other.status_code == 200


async def test_replay_never_touches_budget(client_factory):
    rec, _ = client_factory()
    await rec.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    replay, app = client_factory(mode=Mode.REPLAY, api_key=None, hard_stop_usd=0.0000001)
    r = await replay.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 200


async def test_live_without_key_is_typed_error(client_factory):
    client, _ = client_factory(mode=Mode.LIVE, api_key=None)
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 503 and r.json()["error"]["type"] == "sgw_no_key"


async def test_healthz_and_budget(client_factory):
    client, _ = client_factory()
    h = (await client.get("/healthz")).json()
    assert h["mode"] == "record" and h["key_present"] is True and "sk-" not in json.dumps(h)
    b = (await client.get("/budget", params={"wave": "W0"})).json()
    assert b["soft_stop_usd"] == 40.0 and b["hard_stop_usd"] == 90.0


async def test_record_mode_reuses_existing_recording(client_factory):
    upstream = FakeUpstream()
    client, _ = client_factory(upstream=upstream, record_overwrite=False)
    await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.headers["x-sgw-replay"] == "hit"
    assert len(upstream.requests) == 1


async def test_record_overwrite_forces_live(client_factory):
    upstream = FakeUpstream()
    client, _ = client_factory(upstream=upstream)
    for _ in range(2):
        await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert len(upstream.requests) == 2


async def test_gzip_stream_is_decoded_and_identity_requested(client_factory):
    import gzip

    payload = gzip.compress(b"".join(synthesize_events(message_json("zipped", output_tokens=3))))
    upstream = FakeUpstream(
        [
            httpx.Response(
                200,
                stream=ChunkStream(payload),
                headers={"content-type": "text/event-stream", "content-encoding": "gzip"},
            )
        ]
    )
    client, app = client_factory(upstream=upstream)
    r = await client.post("/v1/messages", json={**base_body(), "stream": True}, headers=BASE_HEADERS)
    assert r.content.startswith(b"event: message_start")
    assert upstream.requests[0].headers["accept-encoding"] == "identity"
    assert app.state.gateway.ledger.rows()[-1]["output_tokens"] == "3"


async def test_incomplete_stream_billed_at_worst_case(client_factory):
    events = b"".join(synthesize_events(message_json(output_tokens=3)))
    truncated = events[: events.index(b"event: message_delta")]
    upstream = FakeUpstream(
        [httpx.Response(200, stream=ChunkStream(truncated), headers={"content-type": "text/event-stream"})]
    )
    client, app = client_factory(upstream=upstream)
    await client.post("/v1/messages", json={**base_body(), "stream": True}, headers=BASE_HEADERS)
    row = app.state.gateway.ledger.rows()[-1]
    assert row["billed"] == "True" and float(row["cost_usd"]) > 0
    assert row["stop_reason"] == "incomplete_stream_worst_case"


async def test_refusal_passes_through_with_stop_details_and_is_billed(client_factory):
    refusal = {
        **message_json(""),
        "content": [],
        "stop_reason": "refusal",
        "stop_details": {"type": "refusal", "category": None, "explanation": "declined"},
    }
    client, app = client_factory(upstream=FakeUpstream([httpx.Response(200, json=refusal)]))
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.json()["stop_reason"] == "refusal"
    row = app.state.gateway.ledger.rows()[-1]
    assert row["stop_reason"] == "refusal" and row["billed"] == "True"
    replay, _ = client_factory(mode=Mode.REPLAY, api_key=None)
    s = await replay.post("/v1/messages", json={**base_body(), "stream": True}, headers=BASE_HEADERS)
    from services.llm_gateway.sse import SSEAccumulator

    acc = SSEAccumulator()
    acc.feed(s.content)
    assert acc.message["stop_reason"] == "refusal"
    assert acc.message["stop_details"]["type"] == "refusal"
