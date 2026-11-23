"""Thread rows (migration 3500) and K1 `agent_run` rows. The graph state lives in the LangGraph Postgres
checkpointer (schema `lg`); these rows say who owns a run, which graph and mode it used, its K1 status and
whether it was tainted, so a run can be found and resumed after the API restarts."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from psycopg.rows import tuple_row
from psycopg_pool import AsyncConnectionPool

K1_STATUS = {"created": "running", "running": "running", "paused": "paused", "error": "error"}
K1_STATUS |= {"cancelled": "cancelled"}
TERMINAL = frozenset({"done", "error", "cancelled"})
GRAPH_VERSIONS = {"assess": "assess@1", "copilot": "copilot@1"}


def k1_status(run_status: str) -> str:
    """Graph outcomes (executed, blocked, no_action, awaiting_approval at the end) are `done` in K1."""
    return K1_STATUS.get(run_status, "done")


@dataclass(frozen=True)
class ThreadRow:
    thread_id: str
    user_id: str
    module: str
    created_at: datetime


@dataclass(frozen=True)
class RunRow:
    run_id: str
    thread_id: str
    user_id: str
    graph: str
    run_mode: str
    status: str
    tainted: bool = False


class RunStore(Protocol):
    async def add_thread(self, row: ThreadRow) -> None: ...

    async def thread(self, thread_id: str) -> ThreadRow | None: ...

    async def add_run(self, row: RunRow) -> None: ...

    async def set_status(self, run_id: str, run_status: str, tainted: bool) -> None: ...

    async def run(self, run_id: str) -> RunRow | None: ...

    async def latest_run(self, thread_id: str) -> RunRow | None: ...

    async def thread_runs(self, thread_id: str, user_id: str, graph: str, limit: int) -> list[TimedRun]: ...


@dataclass(frozen=True)
class TimedRun:
    row: RunRow
    started_at: datetime
    ended_at: datetime | None


@dataclass
class MemoryRunStore:
    threads: dict[str, ThreadRow] = field(default_factory=dict)
    runs: dict[str, RunRow] = field(default_factory=dict)
    times: dict[str, tuple[datetime, datetime | None]] = field(default_factory=dict)

    async def add_thread(self, row: ThreadRow) -> None:
        self.threads[row.thread_id] = row

    async def thread(self, thread_id: str) -> ThreadRow | None:
        return self.threads.get(thread_id)

    async def add_run(self, row: RunRow) -> None:
        self.runs[row.run_id] = replace(row, status=k1_status(row.status))
        self.times[row.run_id] = (datetime.now(UTC), None)

    async def set_status(self, run_id: str, run_status: str, tainted: bool) -> None:
        self.runs[run_id] = replace(self.runs[run_id], status=k1_status(run_status), tainted=tainted)
        started = self.times.get(run_id, (datetime.now(UTC), None))[0]
        self.times[run_id] = (started, datetime.now(UTC) if k1_status(run_status) in TERMINAL else None)

    async def run(self, run_id: str) -> RunRow | None:
        return self.runs.get(run_id)

    async def latest_run(self, thread_id: str) -> RunRow | None:
        rows = [r for r in self.runs.values() if r.thread_id == thread_id]
        return rows[-1] if rows else None

    async def thread_runs(self, thread_id: str, user_id: str, graph: str, limit: int) -> list[TimedRun]:
        rows = [
            r
            for r in self.runs.values()
            if r.thread_id == thread_id and r.user_id == user_id and r.graph == graph
        ]
        return [TimedRun(r, *self.times[r.run_id]) for r in rows[-limit:]]


INSERT_RUN = (
    "INSERT INTO agent_run (run_id, thread_id, user_id, graph, graph_version, run_mode, status, tainted)"
    " VALUES (%s, %s, %s, %s, %s, %s::sgw_run_mode, %s, %s)"
)
LATEST = " WHERE thread_id = %s ORDER BY started_at DESC LIMIT 1"
SELECT_RUN = "SELECT run_id, thread_id, user_id, graph, run_mode::text, status, tainted FROM agent_run"


@dataclass
class PostgresRunStore:
    pool: AsyncConnectionPool[Any]

    async def _one(self, query: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        async with self.pool.connection() as conn, conn.cursor(row_factory=tuple_row) as cur:
            await cur.execute(query, params)
            row: tuple[Any, ...] | None = await cur.fetchone()
            return row

    async def add_thread(self, row: ThreadRow) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO agent_thread (thread_id, user_id, module, created_at) VALUES (%s, %s, %s, %s)",
                (row.thread_id, row.user_id, row.module, row.created_at),
            )

    async def thread(self, thread_id: str) -> ThreadRow | None:
        r = await self._one(
            "SELECT thread_id, user_id, module, created_at FROM agent_thread WHERE thread_id = %s",
            (thread_id,),
        )
        return ThreadRow(*r) if r else None

    async def add_run(self, row: RunRow) -> None:
        version = GRAPH_VERSIONS.get(row.graph, f"{row.graph}@1")
        params = (row.run_id, row.thread_id, row.user_id, row.graph, version, row.run_mode)
        async with self.pool.connection() as conn:
            await conn.execute(INSERT_RUN, (*params, k1_status(row.status), row.tainted))

    async def set_status(self, run_id: str, run_status: str, tainted: bool) -> None:
        status = k1_status(run_status)
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE agent_run SET status = %s, tainted = %s,"
                " ended_at = CASE WHEN %s THEN now() ELSE NULL END WHERE run_id = %s",
                (status, tainted, status in TERMINAL, run_id),
            )

    async def run(self, run_id: str) -> RunRow | None:
        r = await self._one(SELECT_RUN + " WHERE run_id = %s", (run_id,))
        return RunRow(*r) if r else None

    async def latest_run(self, thread_id: str) -> RunRow | None:
        r = await self._one(
            SELECT_RUN + " WHERE thread_id = %s ORDER BY started_at DESC LIMIT 1", (thread_id,)
        )
        return RunRow(*r) if r else None

    async def thread_runs(self, thread_id: str, user_id: str, graph: str, limit: int) -> list[TimedRun]:
        """The user's most recent `limit` runs of one graph in a thread, oldest first, with their times."""
        async with self.pool.connection() as conn, conn.cursor(row_factory=tuple_row) as cur:
            await cur.execute(
                SELECT_RUN.replace(" FROM", ", started_at, ended_at FROM")
                + " WHERE thread_id = %s AND user_id = %s AND graph = %s ORDER BY started_at DESC LIMIT %s",
                (thread_id, user_id, graph, limit),
            )
            rows = await cur.fetchall()
        return [TimedRun(RunRow(*r[:7]), r[7], r[8]) for r in reversed(rows)]
