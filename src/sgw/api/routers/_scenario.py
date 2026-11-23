"""Scenario time and name for read routes, and the one `as_of` rule: a caller may look back, never ahead of
the scenario clock. Not a router module (leading underscore)."""

from __future__ import annotations

from datetime import datetime

from fastapi import Request

from sgw.api.deps import ApiState
from sgw.api.errors import Unprocessable


def scenario_name(state: ApiState) -> str:
    return state.clock.view.state.scenario


def active_scenario(request: Request) -> str:
    """The active scenario for routes that may also run without the API state (approval routers mounted alone
    in tests): Helene when there is no scenario clock."""
    state = getattr(request.app.state, "sgw", None)
    return state.clock.view.state.scenario if state is not None else "helene"


def read_time(state: ApiState, as_of: datetime | None = None) -> datetime:
    now = state.clock.now()
    if as_of is None:
        return now
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise Unprocessable("as_of needs a UTC offset, e.g. 2024-09-26T15:00:00Z", code="INVALID_AS_OF")
    return min(as_of, now)
