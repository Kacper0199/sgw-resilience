"""Registered pipeline assets: feed ingest, ledger relay, ledger reconciliation and observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
import psycopg

from sgw.contracts.adapter import Adapter
from sgw.contracts.events import EnvelopeBase
from sgw.ingest import outbox, relay, store
from sgw.ingest.adapters.nws import AdapterFetchError
from sgw.ingest.faults import GapWindow, Reject
from sgw.pipeline import dq
from sgw.pipeline.context import RunContext
from sgw.pipeline.events import platform_event
from sgw.pipeline.registry import AssetResult, CheckResult, asset

MAX_PAGES = 100_000
INGEST = "ingest.feeds"


@dataclass
class FeedStats:
    source_id: str
    cursor: str | None
    fetched: int = 0
    enqueued: int = 0
    observations: int = 0
    rejects: list[Reject] = field(default_factory=list)
    gaps: list[GapWindow] = field(default_factory=list)
    events: list[EnvelopeBase] = field(default_factory=list)
    error: str | None = None


def _ingest_adapter(
    conn: psycopg.Connection, adapter: Adapter, cursor: str | None, ctx: RunContext
) -> FeedStats:
    stats = FeedStats(adapter.source_id, cursor)
    set_clock = getattr(adapter, "set_clock", None)
    if set_clock is not None:
        set_clock(ctx.as_of)
    for _ in range(MAX_PAGES):
        try:
            result = adapter.fetch_since(stats.cursor)
        except AdapterFetchError as error:
            stats.error = str(error)
            break
        except Exception as error:  # noqa: BLE001
            stats.error = f"adapter raised {type(error).__name__}: {str(error)[:200]}"
            break
        with conn.transaction():
            stats.enqueued += outbox.enqueue(conn, result.events, origin=f"ingest:{adapter.source_id}")
            stats.observations += store.upsert_observations(conn, result.events)
        stats.fetched += len(result.events)
        stats.events.extend(result.events)
        advanced = bool(result.next_cursor) and result.next_cursor != stats.cursor
        if advanced:
            stats.cursor = result.next_cursor
        if not result.events or not advanced:
            break
    drain = getattr(adapter, "drain_rejects", None)
    stats.rejects = list(drain()) if drain is not None else []
    stats.gaps = list(getattr(adapter, "gaps", []))
    return stats


@asset(INGEST, freshness_limit_s=900)
def ingest_feeds(ctx: RunContext, conn: psycopg.Connection) -> AssetResult:
    """Pull every adapter from its last cursor; outbox rows and observations commit together per page."""
    from sgw.pipeline.runner import last_watermarks

    previous = {} if ctx.from_start else last_watermarks(conn, ctx.namespace, INGEST)
    cursors: dict[str, str | None] = dict(previous.get("cursors", {}))  # type: ignore[call-overload]
    run_id = ctx.state.get("run_id")
    feeds: list[FeedStats] = []
    extra: list[EnvelopeBase] = []
    for adapter in ctx.adapters:
        stats = _ingest_adapter(conn, adapter, cursors.get(adapter.source_id), ctx)
        feeds.append(stats)
        cursors[adapter.source_id] = stats.cursor
        with conn.transaction():
            store.quarantine(conn, adapter.source_id, stats.rejects, run_id)
            store.record_gaps(conn, adapter.source_id, stats.gaps, "feed fault: gap")
            store.record_health(conn, adapter.health(), dq.freshness_limit(adapter.source_id))
        for gap in stats.gaps:
            extra.append(
                platform_event(
                    ctx,
                    "CoverageGap",
                    f"{adapter.source_id}:{gap.from_utc.isoformat()}:{gap.to_utc.isoformat()}",
                    {
                        "gap_source_id": adapter.source_id,
                        "from_utc": gap.from_utc,
                        "to_utc": gap.to_utc,
                        "reason": "feed fault: gap",
                    },
                )
            )
    events = [e for f in feeds for e in f.events]
    frame = dq.batch_frame(events)
    rejected = sum(len(f.rejects) for f in feeds)
    checks: list[CheckResult] = [
        dq.schema_check("ingest.envelope_schema", dq.ENVELOPE_SCHEMA, frame),
        dq.duplicate_check(frame),
        dq.out_of_order_check(frame),
        dq.late_check(frame),
        *dq.reject_checks(len(events), rejected),
        CheckResult(
            "ingest.feed_errors",
            "error",
            not any(f.error for f in feeds),
            "; ".join(f"{f.source_id}: {f.error}" for f in feeds if f.error) or "0 fetch errors",
        ),
    ]
    now = ctx.as_of or ctx.now
    for f in sorted(feeds, key=lambda s: s.source_id):
        measured, known = _last_event(conn, f)
        checks.append(dq.freshness_check(f.source_id, measured, now, last_known_at=known))
    ctx.state["ingested_keys"] = sorted({e.dedup_key for e in events})
    ctx.state["observation_keys"] = sorted({(r[0], r[1], r[5]) for r in store.observation_rows(events)})
    return AssetResult(
        rows_in=len(events) + rejected,
        rows_out=sum(f.enqueued for f in feeds),
        rows_quarantined=rejected,
        watermarks={"cursors": dict(sorted(cursors.items()))},
        checks=checks,
        extra_events=extra,
    )


def _last_event(conn: psycopg.Connection, stats: FeedStats) -> tuple[datetime | None, datetime | None]:
    """Measurement and known time of the feed's newest event, from the ledger and this run's fetch."""
    row = conn.execute(
        "SELECT event_time, known_at FROM event WHERE source_id = %s ORDER BY event_time DESC LIMIT 1",
        (stats.source_id,),
    ).fetchone()
    candidates = [(row[0], row[1])] if row else []
    candidates += [(e.event_time, e.known_at) for e in stats.events[-1:]]
    return max(candidates, key=lambda c: c[0]) if candidates else (None, None)


@asset("ledger.relay", deps=(INGEST,), runs_after_failure=True)
def ledger_relay(ctx: RunContext, conn: psycopg.Connection) -> AssetResult:
    """Drain the outbox into the ledger and prove the sequence is gapless; runs even when ingest raised,
    since committed outbox rows must never wait on a feed."""
    row = conn.execute("SELECT clock_timestamp()").fetchone()
    cutoff = row[0] if row else None
    result = relay.drain(conn)
    report = relay.verify_ledger(conn)
    left = outbox.pending_before(conn, cutoff)
    purged = outbox.purge_done(conn)
    return AssetResult(
        rows_in=result.claimed,
        rows_out=result.appended,
        rows_quarantined=result.rejected,
        watermarks={"head": report.max_seq or 0, "purged_done_rows": purged},
        checks=[
            CheckResult(
                "ledger.gapless",
                "error",
                report.gapless,
                f"count {report.count}, head {report.max_seq or 0}, first bad seq {report.first_bad_seq}",
            ),
            CheckResult(
                "ledger.outbox_drained",
                "error",
                left == 0,
                f"{left} row(s) queued before the drain still pending",
            ),
            CheckResult(
                "ledger.relay_rejects", "error", result.rejected == 0, f"{result.rejected} dead outbox row(s)"
            ),
            CheckResult(
                "ledger.dangling_supersedes",
                "warn",
                result.dangling_supersedes == 0,
                f"{result.dangling_supersedes} supersedes reference(s) not in the ledger",
            ),
        ],
    )


@asset("ledger.reconcile", deps=("ledger.relay", INGEST))
def ledger_reconcile(ctx: RunContext, conn: psycopg.Connection) -> AssetResult:
    """Every event fetched in this run is in the ledger exactly once."""
    keys: list[str] = list(ctx.state.get("ingested_keys", []))
    row = conn.execute("SELECT count(*) FROM event WHERE dedup_key = ANY(%s)", (keys,)).fetchone()
    present = int(row[0]) if row else 0
    return AssetResult(
        rows_in=len(keys),
        rows_out=present,
        checks=[
            CheckResult(
                "ledger.reconciled",
                "error",
                present == len(keys),
                f"{present} of {len(keys)} fetched keys in ledger",
            )
        ],
    )


@asset("observations", deps=(INGEST,), freshness_limit_s=900)
def observations(ctx: RunContext, conn: psycopg.Connection) -> AssetResult:
    """This run's numeric DeviceState readings: finite values, units, and no two different values for one
    reading known at the same instant (later revisions are allowed, K1)."""
    keys: list[tuple[str, str, object]] = list(ctx.state.get("observation_keys", []))
    if not keys:
        return AssetResult(checks=[CheckResult("observations.schema", "error", True, "0 rows this run")])
    sources, tags, times = (list(column) for column in zip(*keys, strict=True))
    rows = conn.execute(
        "SELECT o.source_id, o.tag, o.observed_at, o.known_at, o.value, o.unit, o.quality FROM observation o"
        " JOIN unnest(%s::text[], %s::text[], %s::timestamptz[]) AS k(source_id, tag, observed_at)"
        " USING (source_id, tag, observed_at) ORDER BY 1, 2, 3, 4",
        (sources, tags, times),
    ).fetchall()
    frame = pd.DataFrame(
        rows, columns=["source_id", "tag", "observed_at", "known_at", "value", "unit", "quality"]
    )
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    frame["known_at"] = pd.to_datetime(frame["known_at"], utc=True)
    frame["value"] = frame["value"].astype(float)
    return AssetResult(
        rows_in=len(keys),
        rows_out=len(frame),
        checks=[dq.schema_check("observations.schema", dq.OBSERVATION_SCHEMA, frame)],
    )
