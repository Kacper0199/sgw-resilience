from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from sgw.approval import testkit
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.contracts import golden

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
NO_OPA = "no OPA: set SGW_TEST_OPA_URL or start docker"
START = golden.ADVISORY_N.issued + timedelta(minutes=10)


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if testkit.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with testkit.seeded_database() as url:
        yield url


@pytest.fixture
def conn(db_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(db_url, autocommit=True) as c:
        yield c


@pytest.fixture
def clock() -> testkit.MutableClock:
    return testkit.MutableClock(START)


@pytest.fixture
def token_clock() -> testkit.MutableClock:
    return testkit.MutableClock(START)


@pytest.fixture
def svc(clock: testkit.MutableClock, token_clock: testkit.MutableClock) -> ApprovalService:
    return ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=token_clock)


@pytest.fixture(scope="module")
def opa_url() -> Iterator[str]:
    with testkit.opa_server() as url:
        if url is None:
            pytest.skip(NO_OPA)  # sgw-allow-skip: needs docker
        yield url
