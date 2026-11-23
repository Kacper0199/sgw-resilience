from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from sgw.ingest.testing import server_available
from sgw.integrations.testkit import Db, build_app, seeded_db


@pytest.fixture(scope="module")
def db() -> Iterator[Db]:
    reason = server_available()
    if reason:
        pytest.skip(reason)  # sgw-allow-skip: database tests need Postgres (SGW_TEST_DATABASE_URL)
    with seeded_db("wp37") as found:
        yield found


@pytest.fixture(scope="module")
def client(db: Db) -> Iterator[TestClient]:
    with TestClient(build_app(db.runtime_url)) as c:
        yield c
