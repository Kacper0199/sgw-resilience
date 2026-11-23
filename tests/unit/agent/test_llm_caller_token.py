from __future__ import annotations

from pathlib import Path

import pytest

from sgw.agent.nodes import llm


def test_service_token_wins_then_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SGW_SERVICE", "api")
    monkeypatch.setenv("SGW_GATEWAY_TOKEN_API", "api-token-value")
    monkeypatch.setenv("SGW_GATEWAY_TOKEN_WORKER", "worker-token-value")
    assert llm.caller_token() == "api-token-value"
    monkeypatch.setenv("SGW_SERVICE", "worker")
    assert llm.caller_token() == "worker-token-value"


def test_container_service_without_token_has_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SGW_SERVICE", "worker")
    monkeypatch.delenv("SGW_GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("SGW_GATEWAY_TOKEN_WORKER", raising=False)
    assert llm.caller_token() is None


def test_host_cli_reads_its_token_from_bootstrap_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SGW_GATEWAY_TOKEN", raising=False)
    monkeypatch.setenv("SGW_STATE_ROOT", str(tmp_path))
    secrets = tmp_path / "var" / "secrets"
    secrets.mkdir(parents=True)
    (secrets / "host.env").write_text("# generated\nSGW_GATEWAY_TOKEN_CLI=cli-token-value\n")
    assert llm.caller_token() == "cli-token-value"


async def test_client_presents_the_token_through_the_sdk_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx2 as httpx

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization") or request.headers.get("x-api-key", ""))
        return httpx.Response(
            401, json={"type": "error", "error": {"type": "sgw_unauthenticated", "message": ""}}
        )

    monkeypatch.setenv("SGW_GATEWAY_TOKEN", "process-token")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = llm.GatewayClient("http://gw.invalid", http_client=http)
    request = llm.LlmRequest(
        node="narrate",
        config=llm.node_config("narrate"),
        system=[{"type": "text", "text": "s"}],
        messages=[{"role": "user", "content": "m"}],
        classes=[llm.Classification.C1],
    )
    with pytest.raises(llm.LlmUnavailable) as exc:
        await client.create(request)
    assert seen[0] in {"Bearer process-token", "process-token"} and exc.value.reason == "gateway_401"
    assert exc.value.detail == "sgw_unauthenticated"
