from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from sgw.ops import testkit as tk

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with tk.ops_database() as url:
        yield url


@pytest.fixture
def conn(db_url: str) -> Iterator[psycopg.Connection[Any]]:
    tk.reset_control(db_url)
    with psycopg.connect(db_url, autocommit=True) as c:
        yield c
