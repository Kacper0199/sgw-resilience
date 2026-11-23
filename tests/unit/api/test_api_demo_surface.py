from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sgw.api.app import create_app
from sgw.api.settings import ApiSettings

DSN = "postgresql://nobody@127.0.0.1:1/none"


@pytest.mark.parametrize(
    ("settings", "docs", "banner"),
    [
        (ApiSettings(database_url=DSN, demo_mode=False, cookie_secure=True), 404, None),
        (ApiSettings(database_url=DSN, demo_mode=False, cookie_secure=True, api_docs=True), 200, None),
        (ApiSettings(database_url=DSN, demo_mode=True), 200, "synthetic data; demo identities"),
    ],
)
def test_docs_and_demo_banner_follow_the_mode(settings: ApiSettings, docs: int, banner: str | None) -> None:
    client = TestClient(create_app(settings))
    response = client.get("/api/docs")
    assert response.status_code == docs
    assert response.headers.get("x-sgw-demo-mode") == banner
    other = client.get("/api/does-not-exist")
    assert other.headers.get("x-sgw-demo-mode") == banner


def test_settings_read_the_docs_flag() -> None:
    env = {"SGW_DATABASE_URL": DSN, "SGW_COOKIE_SECURE": "1"}
    assert ApiSettings.from_env(env).api_docs is False
    assert ApiSettings.from_env({**env, "SGW_API_DOCS": "1"}).api_docs is True
