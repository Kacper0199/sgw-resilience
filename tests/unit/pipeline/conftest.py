from __future__ import annotations

from collections.abc import Iterator

import pytest

from sgw.ingest.testing import ScratchDb, scratch_database, server_available


@pytest.fixture(scope="session")
def db_server() -> None:
    reason = server_available()
    if reason:
        pytest.skip(reason)  # sgw-allow-skip: database tests need the local Postgres stack (port 5434)


@pytest.fixture
def scratch_db(db_server: None) -> Iterator[ScratchDb]:
    with scratch_database() as db:
        yield db
