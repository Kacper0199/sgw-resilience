from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from services.llm_gateway.api import create_app
from services.llm_gateway.config import Mode, Settings

from .gateway_testkit import FAKE_KEY, FakeUpstream


@pytest.fixture
def settings_factory(tmp_path: Path) -> Callable[..., Settings]:
    def make(**kw: Any) -> Settings:
        defaults: dict[str, Any] = {
            "mode": Mode.RECORD,
            "fixture_dir": tmp_path / "fixtures",
            "spend_csv": tmp_path / "var" / "llm_spend.csv",
            "api_key": FAKE_KEY,
            "upstream_base_url": "https://upstream.invalid",
            "record_overwrite": True,
            "allow_test_upstream": True,
            "accept_test_tokens": True,
        }
        defaults.update(kw)
        return Settings(**defaults)

    return make


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
def client_factory(settings_factory: Callable[..., Settings]):
    clients: list[httpx.AsyncClient] = []

    def make(
        upstream: FakeUpstream | None = None, *, sink: Any = None, **kw: Any
    ) -> tuple[httpx.AsyncClient, Any]:
        upstream = upstream or FakeUpstream()
        settings = settings_factory(**kw)
        app = create_app(settings, transport=httpx.MockTransport(upstream), sleep=_no_sleep, sink=sink)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")
        clients.append(client)
        return client, app

    yield make
