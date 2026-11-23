"""Copilot search against Postgres built from the committed corpus: the recorded search results that the
replay tests use still equal a live search, and the copilot dev eval run on live search (replay gateway)
gives the recorded grades. Any corpus, index or ranking drift fails here."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest

from sgw.agent.copilot import evaluate
from sgw.agent.copilot.search import DEMO_SEARCH, DbSearch, hit_to_json
from sgw.agent.rag.corpus import load_corpus
from sgw.agent.rag.embed import CachedPassages, default_embedder
from sgw.agent.rag.headers import load_headers
from sgw.agent.rag.index import build_index
from sgw.approval import testkit as tk
from sgw.contracts.tools import SearchProceduresArgs

from ..agent_testkit import replay_gateway
from .copilot_testkit import ctx

DATA = Path(__file__).parent / "data"
REPORTS = Path(__file__).resolve().parents[4] / "data" / "artefacts" / "evals"
NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with tk.scratch_database(prefix="sgw_wp21_t") as url:
        with psycopg.connect(url) as c:
            build_index(c, load_corpus(), load_headers(), embedder=default_embedder(), cache=CachedPassages())
            c.commit()
        yield url


def live(url: str) -> DbSearch:
    return DbSearch(lambda: psycopg.connect(url, autocommit=True), embedder=default_embedder())


def test_recorded_searches_equal_live_searches(db_url: str) -> None:
    recorded: dict[str, list[dict[str, Any]]] = json.loads(DEMO_SEARCH.read_text("utf-8"))
    search = live(db_url)
    for key, rows in recorded.items():
        as_of, top_k, query = key.split("|", 2)
        hits = search(SearchProceduresArgs(query=query, top_k=int(top_k)), ctx(datetime.fromisoformat(as_of)))
        got = [hit_to_json(g.hit) for g in hits]
        assert [h["chunk_id"] for h in got] == [h["chunk_id"] for h in rows], key
        assert [h["blocks"] for h in got] == [h["blocks"] for h in rows], key


async def test_copilot_eval_on_live_search_gives_the_recorded_grades(db_url: str) -> None:
    expected = json.loads((REPORTS / "copilot_eval_v4.json").read_text(encoding="utf-8"))
    with replay_gateway() as url:
        got = await evaluate.run_all(url, "test", search=live(db_url))
    assert got["rows"] == expected["rows"]


async def test_postgres_store_lists_a_users_copilot_runs_with_times_and_a_cap(db_url: str) -> None:
    from datetime import UTC, datetime

    from psycopg_pool import AsyncConnectionPool

    from sgw.agent.nodes.run_store import PostgresRunStore, RunRow, ThreadRow

    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(db_url, min_size=1, max_size=2, open=False)
    await pool.open()
    try:
        store = PostgresRunStore(pool)
        await store.add_thread(ThreadRow("thr-db", "ops_dm_01", "ask", datetime.now(UTC)))
        for n, (user, graph) in enumerate(
            [
                ("ops_dm_01", "copilot"),
                ("ops_dm_01", "assess"),
                ("ops_dm_01", "copilot"),
                ("ops_dm_02", "copilot"),
            ]
        ):
            await store.add_run(RunRow(f"run-{n}", "thr-db", user, graph, "replay", "created"))
            await store.set_status(f"run-{n}", "ended", False)
        got = await store.thread_runs("thr-db", "ops_dm_01", "copilot", 50)
        assert [t.row.run_id for t in got] == ["run-0", "run-2"]
        assert all(t.ended_at is not None and t.ended_at >= t.started_at for t in got)
        assert [t.row.run_id for t in await store.thread_runs("thr-db", "ops_dm_01", "copilot", 1)] == [
            "run-2"
        ]
    finally:
        await pool.close()
