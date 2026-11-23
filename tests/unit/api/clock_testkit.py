"""Pin the scenario clock of a TestClient app, in the control row and in-process, and keep it pinned.

The ledger broadcaster polls the control row and installs what it read; a poll that read the row before the
UPDATE can land after `set_view` and put the old time back. Waiting until two poll intervals pass with the
pinned time in place makes the next assertion independent of how busy the database is."""

import time
from dataclasses import replace
from datetime import datetime

import psycopg
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

SETTLE_TIMEOUT_S = 15.0


def pin_clock(client: TestClient, when: datetime) -> None:
    api = client.app.state.sgw  # type: ignore[attr-defined]
    moved = replace(api.clock.view, state=replace(api.clock.view.state, anchor_scenario=when, speed=0))
    with psycopg.connect(api.settings.database_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE control_state SET scenario_clock = %s WHERE id = 1", (Jsonb(moved.state.to_json()),)
        )
    poll = max(float(api.settings.ledger_poll_s), 0.05)
    deadline = time.monotonic() + SETTLE_TIMEOUT_S
    stable_since: float | None = None
    while time.monotonic() < deadline:
        if api.clock.view.state.anchor_scenario != when or api.clock.view.state.speed != 0:
            api.clock.set_view(moved)
            stable_since = None
        elif stable_since is None:
            stable_since = time.monotonic()
        elif time.monotonic() - stable_since >= 2 * poll:
            return
        time.sleep(poll / 2)
    raise AssertionError(f"scenario clock did not stay at {when.isoformat()}")
