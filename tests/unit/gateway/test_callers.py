"""Security audit M4: caller tokens, node binding, class ceiling from the node rule, and who may claim
pseudonymized C2 content."""

from __future__ import annotations

from pathlib import Path

import pytest
from services.llm_gateway.callers import (
    TEST_TOKENS,
    Caller,
    CallerRegistry,
    load_callers,
    parse_token_digests,
    token_sha256,
)
from services.llm_gateway.calls import MemorySink
from services.llm_gateway.config import Mode, Settings
from services.llm_gateway.policy import PolicyViolation

from .gateway_testkit import BASE_HEADERS, FakeUpstream, base_body

NO_KEY = {k: v for k, v in BASE_HEADERS.items() if k != "x-api-key"}
REAL = "x" * 43


def _as(service: str, node: str = "test.narrate", **extra: str) -> dict[str, str]:
    return {**NO_KEY, "authorization": f"Bearer {TEST_TOKENS[service]}", "x-sgw-node": node, **extra}


def _nodes(tmp_path: Path) -> Path:
    path = tmp_path / "nodes.yaml"
    path.write_text(
        "nodes:\n"
        "  narrate:\n    models: [claude-sonnet-5-5]\n    class_ceiling: C1\n"
        "  rag_chunk_header:\n    models: [claude-sonnet-5-5]\n    class_ceiling: C1\n"
        "  pseudo_brief:\n    models: [claude-sonnet-5-5]\n    class_ceiling: C2\n    routes: [R1, R2]\n"
        "  plain_c2:\n    models: [claude-sonnet-5-5]\n    class_ceiling: C2\n"
    )
    return path


def _callers(tmp_path: Path, c2_service: str = "api") -> Path:
    path = tmp_path / "callers.yaml"
    path.write_text(
        "services:\n"
        f"  api:\n    may_send_c2: {str(c2_service == 'api').lower()}\n"
        "    nodes: [narrate, pseudo_brief, plain_c2]\n"
        "  worker:\n    may_send_c2: false\n    nodes: [rag_chunk_header, pseudo_brief]\n"
        "  cli:\n    may_send_c2: false\n    nodes: ['*']\n"
    )
    return path


@pytest.mark.parametrize(
    "headers",
    [
        NO_KEY,
        {**NO_KEY, "authorization": "Bearer not-a-known-token"},
        {**NO_KEY, "x-api-key": "unused-by-gateway"},
        {**NO_KEY, "authorization": "Basic Zm9vOmJhcg=="},
        {**NO_KEY, "authorization": f"Bearer {TEST_TOKENS['cli']}", "x-api-key": TEST_TOKENS["api"]},
    ],
    ids=["none", "unknown_bearer", "placeholder_key", "basic_auth", "bearer_and_key_disagree"],
)
async def test_unauthenticated_requests_get_401_before_anything_else(client_factory, headers):
    upstream, sink = FakeUpstream(), MemorySink()
    client, _ = client_factory(upstream=upstream, sink=sink, mode=Mode.LIVE)
    r = await client.post("/v1/messages", json=base_body(), headers=headers)
    assert r.status_code == 401 and r.json()["error"]["type"] == "sgw_unauthenticated"
    assert upstream.requests == [] and sink.records == []
    assert TEST_TOKENS["cli"] not in r.text


async def test_bearer_alone_and_sdk_key_alone_both_authenticate(client_factory):
    client, _ = client_factory(mode=Mode.LIVE)
    assert (await client.post("/v1/messages", json=base_body(), headers=_as("cli"))).status_code == 200
    key_only = {**NO_KEY, "x-api-key": TEST_TOKENS["cli"]}
    assert (await client.post("/v1/messages", json=base_body(), headers=key_only)).status_code == 200


@pytest.mark.parametrize(
    ("service", "node", "status"),
    [
        ("api", "narrate", 200),
        ("api", "rag_chunk_header", 403),
        ("worker", "narrate", 403),
        ("worker", "rag_chunk_header", 200),
        ("cli", "narrate", 200),
        ("cli", "rag_chunk_header", 200),
    ],
)
async def test_each_token_is_bound_to_its_nodes(client_factory, tmp_path, service, node, status):
    upstream, sink = FakeUpstream(), MemorySink()
    client, _ = client_factory(
        upstream=upstream,
        sink=sink,
        mode=Mode.LIVE,
        nodes_file=_nodes(tmp_path),
        callers_file=_callers(tmp_path),
    )
    r = await client.post("/v1/messages", json=base_body(), headers=_as(service, node))
    assert r.status_code == status, r.text
    if status == 403:
        assert r.json()["error"]["type"] == "sgw_node_not_allowed_for_caller"
        assert upstream.requests == []
        assert (sink.records[0].decision, sink.records[0].stop_reason) == (
            "deny",
            "sgw_node_not_allowed_for_caller",
        )


async def test_declared_classes_may_lower_but_never_raise_the_node_ceiling(client_factory, tmp_path):
    client, _ = client_factory(mode=Mode.LIVE, nodes_file=_nodes(tmp_path), callers_file=_callers(tmp_path))
    low = await client.post(
        "/v1/messages", json=base_body(), headers=_as("api", "narrate", **{"x-sgw-classes": "C0"})
    )
    assert low.status_code == 200
    high = await client.post(
        "/v1/messages", json=base_body(), headers=_as("cli", "narrate", **{"x-sgw-classes": "C2"})
    )
    assert high.status_code == 403 and "class_above_node_ceiling" in high.json()["error"]["message"]


@pytest.mark.parametrize(
    ("c2_service", "service", "node", "status"),
    [
        ("api", "api", "pseudo_brief", 200),
        ("api", "api", "plain_c2", 403),
        ("api", "worker", "pseudo_brief", 403),
        ("none", "api", "pseudo_brief", 403),
    ],
    ids=["c2_service_r2_node", "node_without_r2", "service_without_c2", "no_service_has_c2"],
)
async def test_pseudonymized_claim_counts_only_for_c2_services_on_r2_nodes(
    client_factory, tmp_path, c2_service, service, node, status
):
    upstream = FakeUpstream()
    client, _ = client_factory(
        upstream=upstream,
        mode=Mode.LIVE,
        egress_route="R2",
        nodes_file=_nodes(tmp_path),
        callers_file=_callers(tmp_path, c2_service),
    )
    headers = _as(service, node, **{"x-sgw-classes": "C2", "x-sgw-pseudonymized": "1"})
    r = await client.post("/v1/messages", json=base_body(), headers=headers)
    assert r.status_code == status, r.text
    if status == 403:
        assert r.json()["error"]["type"] == "sgw_class_denied" and upstream.requests == []


async def test_configured_digests_accept_the_real_token_and_never_the_test_one(client_factory):
    digests = (("cli", token_sha256(REAL)),)
    client, _ = client_factory(mode=Mode.LIVE, accept_test_tokens=False, caller_token_digests=digests)
    real = {**NO_KEY, "authorization": f"Bearer {REAL}"}
    assert (await client.post("/v1/messages", json=base_body(), headers=real)).status_code == 200
    assert (await client.post("/v1/messages", json=base_body(), headers=_as("cli"))).status_code == 401
    health = (await client.get("/healthz")).json()
    assert health["callers"] == {"services": ["cli"], "test_tokens": False}
    assert REAL not in str(health)


async def test_no_configured_tokens_means_every_call_is_refused(client_factory):
    client, _ = client_factory(mode=Mode.LIVE, accept_test_tokens=False)
    assert (await client.post("/v1/messages", json=base_body(), headers=_as("cli"))).status_code == 401


def test_test_tokens_are_refused_for_the_real_api(tmp_path):
    with pytest.raises(ValueError, match="test caller tokens"):
        Settings(
            mode=Mode.LIVE, accept_test_tokens=True, egress_pdp="reference", spend_csv=tmp_path / "s.csv"
        )
    Settings(mode=Mode.REPLAY, accept_test_tokens=True)


def test_digest_env_parsing_refuses_malformed_entries(monkeypatch):
    good = f"api:{token_sha256('a')},cli:{token_sha256('b')}"
    assert parse_token_digests(good) == (("api", token_sha256("a")), ("cli", token_sha256("b")))
    for bad in ("api", "api:abc", f":{token_sha256('a')}", f"api:{'z' * 64}"):
        with pytest.raises(ValueError):
            parse_token_digests(bad)
    monkeypatch.setenv("LLM_CALLER_TOKEN_SHA256", good)
    assert Settings.from_env().caller_token_digests[0][0] == "api"


def test_registry_unit_rules():
    callers = {"api": Caller("api", ("narrate", "report_*"))}
    reg = CallerRegistry((("api", token_sha256(REAL)), ("ghost", token_sha256("g"))), callers)
    assert reg.services == ["api"]
    caller = reg.authenticate({"authorization": f"bearer {REAL}"})
    reg.authorize(caller, "report_sitrep")
    with pytest.raises(PolicyViolation) as exc:
        reg.authorize(caller, "investigate")
    assert exc.value.status == 403
    with pytest.raises(PolicyViolation) as exc:
        reg.authenticate({"authorization": "Bearer g"})
    assert exc.value.status == 401


def test_shipped_binding_covers_every_k14_node_and_keeps_c2_off():
    import yaml

    from sgw.agent.nodes.llm import NODES_FILE

    callers = load_callers()
    assert set(callers) == {"api", "worker", "cli"}
    assert not any(c.may_send_c2 for c in callers.values())
    nodes = [n["node"] for n in yaml.safe_load(NODES_FILE.read_text())["nodes"]]
    for node in nodes:
        assert callers["cli"].may_call(node)
        assert callers["api"].may_call(node) or callers["worker"].may_call(node), node
    assert not callers["worker"].may_call("investigate") and not callers["api"].may_call("rag_chunk_header")
