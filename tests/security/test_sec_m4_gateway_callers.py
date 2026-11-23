"""Security audit M4 (SEC-21 family: caller-forged attributes ignored): the LLM gateway trusts nothing a
caller asserts about itself. With the shipped node allowlist (src/sgw/agent/llm_nodes.yaml) and service
binding (services/llm_gateway/callers.yaml), and production-style tokens known to the gateway only as
digests: a request without a valid token never reaches a node; a valid token reaches only its service's
nodes; declared classes cannot lift a node above its ceiling; a pseudonymized-C2 claim from a service that may
not send C2 is ignored even on route R2. The upstream is never contacted in any refused case."""

from __future__ import annotations

import secrets
from pathlib import Path

import httpx
import pytest
from services.llm_gateway.api import create_app
from services.llm_gateway.callers import TEST_TOKENS, token_sha256
from services.llm_gateway.calls import MemorySink
from services.llm_gateway.config import Mode, Settings
from tests.unit.gateway.gateway_testkit import FakeUpstream, base_body

from sgw.agent.nodes.llm import NODES_FILE

TOKENS = {service: secrets.token_urlsafe(32) for service in ("api", "worker", "cli")}
TAGS = {
    "anthropic-version": "2023-06-01",
    "x-sgw-purpose": "redteam",
    "x-sgw-wave": "W6",
    "x-sgw-classes": "C1",
}


def _client(tmp_path: Path, upstream: FakeUpstream, sink: MemorySink, route: str = "R1") -> httpx.AsyncClient:
    settings = Settings(
        mode=Mode.LIVE,
        fixture_dir=tmp_path / "fixtures",
        spend_csv=tmp_path / "spend.csv",
        nodes_file=NODES_FILE,
        api_key="upstream-placeholder",
        upstream_base_url="https://upstream.invalid",
        allow_test_upstream=True,
        egress_route=route,
        caller_token_digests=tuple((s, token_sha256(t)) for s, t in TOKENS.items()),
    )
    app = create_app(settings, transport=httpx.MockTransport(upstream), sink=sink)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")


def _body(node: str) -> dict:
    model = (
        "claude-haiku-5-5"
        if node in {"rag_chunk_header", "extract_note", "route_intent"}
        else "claude-sonnet-5-5"
    )
    return base_body(
        model=model, output_config={"effort": "low" if model.startswith("claude-haiku") else "medium"}
    )


def _headers(token: str | None, node: str, **extra: str) -> dict[str, str]:
    out = {**TAGS, "x-sgw-node": node, **extra}
    if token is not None:
        out["authorization"] = f"Bearer {token}"
    return out


@pytest.mark.parametrize(
    "token",
    [None, "", TEST_TOKENS["cli"], "Bearer-looking-junk", TOKENS["api"][:-1]],
    ids=["none", "empty", "public_test", "junk", "truncated"],
)
async def test_m4_no_valid_token_no_model_call(tmp_path, token):
    upstream, sink = FakeUpstream(), MemorySink()
    async with _client(tmp_path, upstream, sink) as client:
        r = await client.post("/v1/messages", json=_body("narrate"), headers=_headers(token, "narrate"))
    assert r.status_code == 401 and upstream.requests == [] and sink.records == []


@pytest.mark.parametrize(
    ("service", "node"),
    [
        ("worker", "investigate"),
        ("worker", "narrate"),
        ("api", "rag_chunk_header"),
        ("api", "spike.anything"),
        ("api", "test.narrate"),
    ],
)
async def test_m4_a_stolen_service_token_reaches_only_that_services_nodes(tmp_path, service, node):
    upstream, sink = FakeUpstream(), MemorySink()
    async with _client(tmp_path, upstream, sink) as client:
        r = await client.post("/v1/messages", json=_body(node), headers=_headers(TOKENS[service], node))
    assert r.status_code == 403 and r.json()["error"]["type"] == "sgw_node_not_allowed_for_caller"
    assert upstream.requests == [] and sink.records[0].decision == "deny"


async def test_m4_the_rightful_service_still_gets_through(tmp_path):
    upstream, sink = FakeUpstream(), MemorySink()
    async with _client(tmp_path, upstream, sink) as client:
        r = await client.post(
            "/v1/messages", json=_body("narrate"), headers=_headers(TOKENS["api"], "narrate")
        )
    assert r.status_code == 200 and len(upstream.requests) == 1
    assert TOKENS["api"] not in upstream.requests[0].headers.get("authorization", "")
    assert TOKENS["api"] not in str(dict(upstream.requests[0].headers))


@pytest.mark.parametrize("route", ["R1", "R2"])
@pytest.mark.parametrize("service", ["api", "cli"])
async def test_m4_forged_classes_and_pseudonymized_claims_do_not_widen_egress(tmp_path, route, service):
    upstream, sink = FakeUpstream(), MemorySink()
    forged = _headers(TOKENS[service], "narrate", **{"x-sgw-classes": "C2", "x-sgw-pseudonymized": "1"})
    async with _client(tmp_path, upstream, sink, route) as client:
        r = await client.post("/v1/messages", json=_body("narrate"), headers=forged)
    assert r.status_code == 403 and r.json()["error"]["type"] == "sgw_class_denied"
    assert upstream.requests == []
