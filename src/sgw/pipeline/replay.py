"""Scenario replay: fixtures -> replay adapters -> outbox -> ledger relay -> DQ, as one pipeline run.

The run clock is `--as-of` or, for a full replay, the data horizon (the latest `scenario_known_at`), so
freshness rules measure how far each feed lags the newest knowledge in the scenario.
Replaying the same scenario into a fresh database gives a byte-identical ledger export (`ledger_sha256`);
replaying again into the same database resumes from the stored cursors and appends no source event.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg

from sgw.contracts.vocab import FeedMode, RunMode
from sgw.ingest import ledger, outbox
from sgw.ingest.adapters.registry import DEFAULT_PAGE, scenario_adapters
from sgw.ingest.relay import LedgerReport, verify_ledger
from sgw.ingest.scenario import load_scenario
from sgw.pipeline.context import RunContext
from sgw.pipeline.runner import RunOutcome, run_pipeline

RESET_TABLES = ("dq_check", "pipeline_run", "quarantine", "coverage_gap", "adapter_health", "observation")


@dataclass(frozen=True)
class ReplayReport:
    scenario: str
    outcomes: list[RunOutcome]
    ledger: LedgerReport
    ledger_sha256: str
    ledger_events: int

    @property
    def error_failures(self) -> int:
        return sum(1 for o in self.outcomes for c in o.failed_checks if c.severity == "error")

    @property
    def warn_failures(self) -> int:
        return sum(1 for o in self.outcomes for c in o.failed_checks if c.severity == "warn")

    @property
    def ok(self) -> bool:
        return (
            self.ledger.gapless
            and self.error_failures == 0
            and all(o.status in ("success", "partial") for o in self.outcomes)
        )


def replay_scenario(
    conn: psycopg.Connection,
    name: str,
    *,
    env: Mapping[str, str],
    page_size: int = DEFAULT_PAGE,
    as_of: datetime | None = None,
    from_start: bool = False,
    include_platform: bool = False,
    fixtures_root: Path | None = None,
) -> ReplayReport:
    scenario = load_scenario(name, fixtures_root)
    modes = {h.feed_mode for h in scenario.headers}
    horizon = max((e.scenario_known_at for e in scenario.events), default=scenario.window_end)
    ctx = RunContext(
        namespace=f"replay.{name}",
        run_mode=RunMode.REPLAY,
        feed_mode=modes.pop() if len(modes) == 1 else FeedMode.SYNTHETIC,
        now=as_of or min(horizon, scenario.window_end),
        adapters=list(
            scenario_adapters(scenario, env=env, page_size=page_size, include_platform=include_platform)
        ),
        as_of=as_of,
        from_start=from_start,
        env=env,
    )
    outcomes = run_pipeline(conn, ctx)
    report = verify_ledger(conn)
    sha, count = ledger.ledger_sha256(conn)
    return ReplayReport(name, outcomes, report, sha, count)


def reset_replay_state(conn: psycopg.Connection) -> dict[str, int]:
    """Delete the ledger and the ingest/pipeline tables (not reference data) and restart run ids. Needs the
    owner connection: the runtime role cannot delete ledger rows (migration 0011). Fails if other tables
    still reference ledger events, which protects a database that already holds decisions."""
    removed: dict[str, int] = {}
    with conn.transaction():
        for table in RESET_TABLES:
            removed[table] = conn.execute(f"DELETE FROM {table}").rowcount  # noqa: S608
        removed["job"] = conn.execute("DELETE FROM job WHERE kind = %s", (outbox.OUTBOX_KIND,)).rowcount
        removed["event"] = conn.execute("DELETE FROM event").rowcount
        conn.execute("ALTER SEQUENCE pipeline_run_seq RESTART")
    return removed
