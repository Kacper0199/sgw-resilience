"""`sgw demo goto` (and `sgw reset-db`) replace the database under a running API. Every pooled
connection then belongs to a terminated backend; the pools check a connection before lending it, so the
first request after the switch succeeds instead of failing with AdminShutdown."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from sgw.api.app import create_app
from sgw.api.settings import ApiSettings
from sgw.approval import testkit as tk

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"


def _terminate(admin: str, name: str) -> int:
    with psycopg.connect(admin, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
            " WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        ).fetchall()
    return len(rows)


def test_the_api_pool_lends_a_live_connection_after_its_backends_were_terminated() -> None:
    admin = tk.admin_dsn()
    if admin is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with tk.scratch_database("sgw_wp33pool_t") as url:
        name = str(psycopg.conninfo.conninfo_to_dict(url)["dbname"])
        app = create_app(ApiSettings(database_url=url, demo_mode=True, cookie_secure=False))
        with TestClient(app) as client:
            pool: Any = app.state.sgw.pool

            async def one() -> int:
                async with pool.connection() as conn:
                    row = await (await conn.execute("SELECT 1")).fetchone()
                    return int(row[0])

            assert client.portal.call(one) == 1
            assert _terminate(admin, name) >= 1
            assert client.portal.call(one) == 1
