"""Pipeline runner: executes registered assets in dependency order. Each asset gets a `pipeline_run` row; its
checks become `dq_check` rows; `PipelineRunFinished` and one `DQCheckFailed` per failed check go to the
outbox in the same transaction as the run record, and a final relay drain publishes them. An asset that
raises blocks its dependants (except assets marked `runs_after_failure`, such as the relay); failed checks
fail the run but do not block, since its outbox rows are committed. A failed run keeps its cursors, so the
next run does not fetch and quarantine the same records again."""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from datetime import timedelta

import psycopg
from psycopg.types.json import Jsonb

from sgw.common.telemetry import sgw_span
from sgw.contracts.vocab import Classification
from sgw.ingest import outbox, relay
from sgw.pipeline.context import RunContext
from sgw.pipeline.events import platform_event
from sgw.pipeline.registry import AssetResult, CheckResult, topo_order

log = logging.getLogger(__name__)
ASSET_MODULES = (
    "sgw.pipeline.assets",
    "sgw.models.outage.asset",
    "sgw.opendata.asset",
    "sgw.models.surge.asset",
)


@dataclass
class RunOutcome:
    asset: str
    run_id: str
    status: str
    rows_in: int = 0
    rows_out: int = 0
    rows_quarantined: int = 0
    checks: list[CheckResult] = field(default_factory=list)
    error: str | None = None

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]


def load_assets() -> None:
    for module in ASSET_MODULES:
        importlib.import_module(module)


STALE_RUNNING = timedelta(minutes=30)


def next_run_id(conn: psycopg.Connection, namespace: str, asset: str) -> str:
    row = conn.execute("SELECT nextval('pipeline_run_seq')").fetchone()
    assert row is not None
    return f"{namespace}.{asset}.{int(row[0]):06d}"


def abandon_stale_runs(
    conn: psycopg.Connection, namespace: str, older_than: timedelta = STALE_RUNNING
) -> int:
    """Close `running` rows left by a runner that died; they would otherwise look live forever."""
    return conn.execute(
        "UPDATE pipeline_run SET status = 'failed', finished_at = clock_timestamp(),"
        " error = 'abandoned: runner stopped before finishing'"
        " WHERE status = 'running' AND starts_with(run_id, %s) AND started_at < clock_timestamp() - %s",
        (f"{namespace}.", older_than),
    ).rowcount


def last_watermarks(conn: psycopg.Connection, namespace: str, asset: str) -> dict[str, object]:
    row = conn.execute(
        "SELECT watermarks FROM pipeline_run WHERE asset = %s AND starts_with(run_id, %s)"
        " AND status <> 'running' AND watermarks <> '{}'::jsonb"
        " ORDER BY started_at DESC, run_id DESC LIMIT 1",
        (asset, f"{namespace}.{asset}."),
    ).fetchone()
    return dict(row[0]) if row and row[0] else {}


def _status(result: AssetResult, error: str | None) -> str:
    if error or any(not c.passed and c.severity == "error" for c in result.checks):
        return "failed"
    return "partial" if result.rows_quarantined else "success"


def run_pipeline(
    conn: psycopg.Connection, ctx: RunContext, names: list[str] | None = None
) -> list[RunOutcome]:
    load_assets()
    abandon_stale_runs(conn, ctx.namespace)
    outcomes: dict[str, RunOutcome] = {}
    for spec in topo_order(names):
        run_id = next_run_id(conn, ctx.namespace, spec.name)
        conn.execute(
            "INSERT INTO pipeline_run (run_id, asset, status, started_at, code_version)"
            " VALUES (%s, %s, 'running', now(), %s)",
            (run_id, spec.name, ctx.code_version),
        )
        ctx.state["run_id"] = run_id
        error: str | None = None
        result = AssetResult()
        with sgw_span(
            f"pipeline.{spec.name}",
            run_id=run_id,
            classification=Classification.C1,
            user_role="system",
            run_mode=ctx.run_mode,
        ) as span:
            blocked = (
                []
                if spec.runs_after_failure
                else [d for d in spec.deps if d in outcomes and outcomes[d].error is not None]
            )
            if blocked:
                error = f"upstream failed: {', '.join(blocked)}"
            else:
                try:
                    result = spec.fn(ctx, conn)
                except Exception as exc:  # noqa: BLE001
                    log.exception("asset %s failed", spec.name)
                    error = f"{type(exc).__name__}: {exc}"
            trace = span.get_span_context().trace_id
        status = _status(result, error)
        outcome = RunOutcome(
            spec.name,
            run_id,
            status,
            result.rows_in,
            result.rows_out,
            result.rows_quarantined,
            list(result.checks),
            error,
        )
        _record(conn, ctx, outcome, result, format(trace, "032x") if trace else None)
        outcomes[spec.name] = outcome
    relay.drain(conn)
    return list(outcomes.values())


def _record(
    conn: psycopg.Connection, ctx: RunContext, outcome: RunOutcome, result: AssetResult, trace_id: str | None
) -> None:
    events = [
        *result.extra_events,
        platform_event(
            ctx,
            "PipelineRunFinished",
            outcome.run_id,
            {
                "run_id": outcome.run_id,
                "asset": outcome.asset,
                "status": outcome.status,
                "rows_in": outcome.rows_in,
                "rows_out": outcome.rows_out,
                "rows_quarantined": outcome.rows_quarantined,
            },
        ),
    ]
    for check in outcome.failed_checks:
        events.append(
            platform_event(
                ctx,
                "DQCheckFailed",
                f"{outcome.run_id}:{check.name}",
                {
                    "check_id": f"{outcome.run_id}:{check.name}"[:128],
                    "asset": outcome.asset,
                    "severity": check.severity,
                    "detail": check.observed,
                },
            )
        )
    with conn.transaction():
        conn.execute(
            "UPDATE pipeline_run SET status = %s, finished_at = clock_timestamp(), rows_in = %s,"
            " rows_out = %s, rows_quarantined = %s, watermarks = %s, error = %s, trace_id = %s"
            " WHERE run_id = %s",
            (
                outcome.status,
                outcome.rows_in,
                outcome.rows_out,
                outcome.rows_quarantined,
                Jsonb(result.watermarks),
                outcome.error,
                trace_id,
                outcome.run_id,
            ),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO dq_check (check_id, run_id, asset, name, severity, passed, observed,"
                " freshness_limit_s, checked_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp())",
                [
                    (
                        f"{outcome.run_id}:{c.name}",
                        outcome.run_id,
                        outcome.asset,
                        c.name,
                        c.severity,
                        c.passed,
                        c.observed,
                        c.freshness_limit_s,
                    )
                    for c in outcome.checks
                ],
            )
        outbox.enqueue(conn, events, origin=f"pipeline:{outcome.asset}")
