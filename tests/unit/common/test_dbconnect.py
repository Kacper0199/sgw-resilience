"""Defect 5: a connection refused because the role or server is full is tried again until a slot frees
up; any other connection error is raised at once."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from sgw.common import dbconnect

FULL = psycopg.OperationalError('FATAL:  too many connections for role "sgw_runtime"')


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dbconnect, "FIRST_PAUSE_S", 0.001)
    monkeypatch.setattr(dbconnect, "MAX_PAUSE_S", 0.002)


def test_a_full_role_is_waited_for(monkeypatch: pytest.MonkeyPatch) -> None:
    tries: list[str] = []

    def connect(conninfo: str, **kwargs: Any) -> str:
        tries.append(conninfo)
        if len(tries) < 3:
            raise FULL
        return "conn"

    monkeypatch.setattr(dbconnect.psycopg, "connect", connect)
    assert dbconnect.connect("dsn", autocommit=True) == "conn"  # type: ignore[comparison-overlap]
    assert len(tries) == 3


def test_other_errors_and_a_full_server_past_the_wait_are_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(conninfo: str, **kwargs: Any) -> None:
        raise psycopg.OperationalError("password authentication failed")

    monkeypatch.setattr(dbconnect.psycopg, "connect", refused)
    with pytest.raises(psycopg.OperationalError, match="password"):
        dbconnect.connect("dsn")

    def full(conninfo: str, **kwargs: Any) -> None:
        raise FULL

    monkeypatch.setattr(dbconnect.psycopg, "connect", full)
    with pytest.raises(psycopg.OperationalError, match="too many"):
        dbconnect.connect("dsn", wait_s=0.01)
