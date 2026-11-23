from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import httpx
import pytest
from services.llm_gateway.api import create_app
from services.llm_gateway.callers import TEST_TOKENS
from services.llm_gateway.canonical import request_hash
from services.llm_gateway.config import K14_NODES_FILE, Mode, Settings
from services.llm_gateway.sse import SSEAccumulator

FIXTURES = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "llm"
MIN_FIXTURES = 10


def _fixtures() -> list[dict]:
    out = []
    for path in sorted(FIXTURES.glob("*/*.json")):
        data = json.loads(path.read_text())
        if data.get("request") is not None:
            out.append(data)
    return out


def _shuffle(obj, rng: random.Random):
    if isinstance(obj, dict):
        items = list(obj.items())
        rng.shuffle(items)
        return {k: _shuffle(v, rng) for k, v in items}
    if isinstance(obj, list):
        return [_shuffle(v, rng) for v in obj]
    return obj


def _with_fresh_volatile_ids(body: dict, rng: random.Random) -> dict:
    body = copy.deepcopy(body)
    mapping: dict[str, str] = {}
    for message in body.get("messages", []):
        if not isinstance(message.get("content"), list):
            continue
        for block in message["content"]:
            for key in ("id", "tool_use_id"):
                if isinstance(block.get(key), str):
                    block[key] = mapping.setdefault(block[key], f"toolu_{rng.getrandbits(64):016x}")
            if block.get("type") == "thinking":
                block["signature"] = f"sig{rng.getrandbits(32):08x}"
    return body


def test_committed_fixture_set_is_large_enough_and_hash_consistent():
    fixtures = _fixtures()
    assert len(fixtures) >= MIN_FIXTURES
    for fx in fixtures:
        assert request_hash(fx["request"], fx["request_headers"]) == fx["request_sha256"]


@pytest.mark.parametrize("stream", [False, True])
async def test_every_committed_fixture_replays(tmp_path, stream):
    settings = Settings(
        accept_test_tokens=True,
        mode=Mode.REPLAY,
        fixture_dir=FIXTURES,
        spend_csv=tmp_path / "s.csv",
        api_key=None,
        nodes_file=K14_NODES_FILE,
    )
    app = create_app(settings, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    rng = random.Random(20261119)  # noqa: S311
    hits = 0
    fixtures = _fixtures()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw") as client:
        for fx in fixtures:
            body = _shuffle(_with_fresh_volatile_ids(fx["request"], rng), rng)
            body["stream"] = stream
            body["metadata"] = {"user_id": f"u{rng.random()}"}
            headers = {
                **{k: (",".join(v) if isinstance(v, list) else v) for k, v in fx["request_headers"].items()},
                "x-sgw-node": fx["node"],
                "x-sgw-run": f"replay-{rng.random()}",
                "x-sgw-purpose": "test",
                "x-sgw-wave": "CI",
                "x-sgw-classes": ",".join(fx["data_classes"]),
                "user-agent": f"agent/{rng.random()}",
                "x-api-key": TEST_TOKENS["cli"],
            }
            r = await client.post("/v1/messages", json=body, headers=headers)
            assert r.status_code == 200, (fx["node"], r.text)
            if stream:
                acc = SSEAccumulator()
                acc.feed(r.content)
                got, want = acc.message, fx["response"]
                diff = {k for k in set(got) | set(want) if got.get(k) != want.get(k)}
                assert not diff, (fx["node"], {k: (got.get(k), want.get(k)) for k in diff})
            else:
                assert r.json() == fx["response"]
            hits += 1
    counters = app.state.gateway.counters
    assert (counters["replay_hits"], counters["replay_misses"], counters["live_calls"]) == (hits, 0, 0)
    assert counters["egress_denied"] == 0 and counters["output_blocked"] == 0
    assert hits == len(fixtures) >= MIN_FIXTURES
    print(f"replay hits {hits}/{len(fixtures)} stream={stream}")
