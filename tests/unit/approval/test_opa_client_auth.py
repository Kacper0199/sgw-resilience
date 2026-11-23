from __future__ import annotations

import httpx
import pytest

from sgw.approval.breakglass_policy import OpaGovernance
from sgw.approval.errors import PolicyUnavailableError
from sgw.approval.policy import OpaPolicy


@pytest.mark.parametrize("factory", [OpaPolicy, OpaGovernance])
def test_clients_send_the_bearer_token(monkeypatch: pytest.MonkeyPatch, factory) -> None:
    monkeypatch.setenv("SGW_OPA_TOKEN", "token-for-test-0123456789abcdefghijkl")
    client = factory("http://opa.invalid")
    assert client._client.headers["Authorization"] == "Bearer token-for-test-0123456789abcdefghijkl"


@pytest.mark.parametrize("factory", [OpaPolicy, OpaGovernance])
def test_runtime_load_refused_without_explicit_permission(monkeypatch: pytest.MonkeyPatch, factory) -> None:
    monkeypatch.delenv("SGW_OPA_DEV_LOAD", raising=False)
    calls: list[str] = []
    transport = httpx.MockTransport(lambda request: calls.append(request.method) or httpx.Response(200))
    client = factory(
        "http://opa.invalid", client=httpx.Client(base_url="http://opa.invalid", transport=transport)
    )
    with pytest.raises(PolicyUnavailableError, match="runtime policy load is disabled"):
        client.load()
    assert calls == []
    monkeypatch.setenv("SGW_OPA_DEV_LOAD", "1")
    client.load()
    assert calls and set(calls) == {"PUT"}


def test_missing_decision_does_not_trigger_a_push(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SGW_OPA_DEV_LOAD", raising=False)
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json={})

    client = OpaPolicy(
        "http://opa.invalid",
        reload_on_missing=True,
        client=httpx.Client(base_url="http://opa.invalid", transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(PolicyUnavailableError):
        client._query("approve", {})
    assert "PUT" not in methods
