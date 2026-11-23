"""Connections that wait for a free slot: the shared Postgres caps each role (`sgw_runtime`: 30 for every
stack on the machine) and the server (60), so under load a new connection is refused with "too many
connections" for a moment. `connect` tries again until a slot frees up or `wait_s` passed; any other error
is raised at once (R35 defect 5: a refused connection failed a scenario-job run or a graph step outright)."""

from __future__ import annotations

import time
from typing import Any

import psycopg

WAIT_S = 15.0
FIRST_PAUSE_S = 0.2
MAX_PAUSE_S = 2.0
FULL = ("too many connections", "remaining connection slots are reserved")


def slots_full(error: psycopg.OperationalError) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in FULL)


def connect(conninfo: str, *, wait_s: float = WAIT_S, **kwargs: Any) -> psycopg.Connection[Any]:
    deadline = time.monotonic() + wait_s
    pause = FIRST_PAUSE_S
    while True:
        try:
            return psycopg.connect(conninfo, **kwargs)
        except psycopg.OperationalError as error:
            if not slots_full(error) or time.monotonic() + pause > deadline:
                raise
        time.sleep(pause)
        pause = min(pause * 2, MAX_PAUSE_S)
