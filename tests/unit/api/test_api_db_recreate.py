"""G1: `sgw reset-db` under a running API. The API must follow the recreated database: its scenario clock
reloads from the fresh control row (else the scenario jobs expire the new seed on the old scenario time) and
its broadcaster restarts at the new ledger head (else the browser never hears of new proposals)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from sgw.api.app import create_app
from sgw.api.settings import ApiSettings
from sgw.approval import testkit as tk
from sgw.common.migrate import apply

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
LATE = datetime(2024, 9, 28, 18, 0, tzinfo=UTC)


def _recreate(admin: str, name: str) -> None:
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{name}"')
    url = tk._with_db(admin, name)
    with psycopg.connect(url, autocommit=True) as conn:
        for ext in tk.EXTENSIONS:
            conn.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
    apply(url)


def test_the_api_follows_a_database_recreated_under_it() -> None:
    admin = tk.admin_dsn()
    if admin is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with tk.scratch_database("sgw_g1recreate_t") as url:
        name = str(psycopg.conninfo.conninfo_to_dict(url)["dbname"])
        app = create_app(ApiSettings(database_url=url, demo_mode=True, cookie_secure=False))
        with TestClient(app) as client:
            api: Any = app.state.sgw
            initial = api.clock.now()
            moved = api.clock.view
            from dataclasses import replace

            api.clock.set_view(replace(moved, state=replace(moved.state, anchor_scenario=LATE, speed=0)))
            assert api.clock.now() == LATE
            old_epoch = api.broadcaster.epoch
            _recreate(admin, name)
            for _ in range(3):
                try:
                    if client.portal.call(api.broadcaster.check_epoch):
                        break
                except psycopg.Error:
                    continue
            assert api.broadcaster.epoch != old_epoch
            assert api.clock.now() != LATE and abs((api.clock.now() - initial).total_seconds()) < 3600
            with psycopg.connect(url, autocommit=True) as conn:
                stored = conn.execute("SELECT scenario_clock FROM control_state WHERE id = 1").fetchone()
            assert stored is not None and stored[0] != {}
