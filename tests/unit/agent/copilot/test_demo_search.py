"""Root fix: on the shared stack the API container computed a query embedding slightly differently from
the host that recorded, so close-ranked passages swapped and the ETR revision answer missed its recording. In
DEMO_MODE the copilot replays the recorded demo searches and searches live only for other queries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from sgw.agent.copilot import search as search_mod
from sgw.agent.copilot.search import DEMO_SEARCH, RecordedSearch, ReplayFirstSearch, key
from sgw.contracts.tools import TOOLS

from .copilot_testkit import ctx

ETR = "When do I have to revise a global ETR that is already out?"
MORNING_AFTER = datetime(2024, 9, 27, 12, 0, tzinfo=UTC)


def args(query: str) -> Any:
    return TOOLS["search_procedures"][1].model_validate({"query": query})


def test_a_recorded_demo_search_replays_and_another_query_searches_live() -> None:
    recorded = RecordedSearch(DEMO_SEARCH)
    asked: list[str] = []

    def live(a: Any, c: Any) -> list[Any]:
        asked.append(a.query)
        return []

    search = ReplayFirstSearch(recorded, live)
    assert key(args(ETR), ctx(MORNING_AFTER)) in recorded.data
    hits = search(args(ETR), ctx(MORNING_AFTER))
    assert hits and asked == []
    assert search(args("an unrecorded question about stray cats"), ctx(MORNING_AFTER)) == []
    assert asked == ["an unrecorded question about stray cats"]


@pytest.mark.parametrize(("demo", "replays"), [("1", True), ("", False)])
def test_only_demo_mode_replays_recorded_searches(
    monkeypatch: pytest.MonkeyPatch, demo: str, replays: bool
) -> None:
    monkeypatch.setenv("SGW_DATABASE_URL", "postgresql://unused@127.0.0.1:1/none")
    monkeypatch.setenv("DEMO_MODE", demo)
    assert isinstance(search_mod.env_search(), ReplayFirstSearch) is replays
