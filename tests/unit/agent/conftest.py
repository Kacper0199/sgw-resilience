"""Agent tests run their LLM clients against replay gateways that accept the public test tokens (security
audit M4); every client here presents the CLI test token."""

from __future__ import annotations

import pytest
from services.llm_gateway.callers import TEST_TOKENS


@pytest.fixture(autouse=True)
def _gateway_test_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SGW_GATEWAY_TOKEN", TEST_TOKENS["cli"])
    monkeypatch.delenv("SGW_SERVICE", raising=False)
