"""Feed freshness at the replay clock: what each registered feed had delivered by the scenario time,
read from the ledger with known-at discipline and judged by the one rule of `sgw.pipeline.dq.freshness_check`.

A replay loads the whole scenario window at once, so the pipeline's stored freshness checks and adapter
health describe the end of the window. System health in a replay shows these values instead: the feed table
and the freshness checks then agree, and neither looks at data the scenario has not reached.

Outage reports (`oms`) also count the replayed outage curve the Briefing reads (`county_hourly.csv`): its
last whole hour with customers out is a report known at that hour, so the feed is never "no data" while the
Briefing shows customers out."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from sgw.contracts.api_models import DqCheckOut, FeedHealthItem
from sgw.contracts.vocab import FeedMode
from sgw.pipeline.dq import LATE_FACTOR, REPORTS_ON_SCHEDULE, freshness_check, freshness_limit
from sgw.pipeline.registry import CheckResult

INGEST_ASSET = "ingest.feeds"
OUTAGE_SOURCE = "oms"
CHECK_PREFIX = "replay-clock"
LATE_ARRIVALS = "ingest.late_arrivals"


@dataclass(frozen=True)
class FeedAtClock:
    source_id: str
    feed_mode: FeedMode
    last_event_time: datetime | None
    last_known_at: datetime | None
    check: CheckResult


def feeds_at(conn: psycopg.Connection[Any], at: datetime) -> list[FeedAtClock]:
    """Every feed with an adapter health row, with its newest event known at or before `at`."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT h.source_id, h.feed_mode, e.event_time, e.known_at FROM adapter_health h"
            " LEFT JOIN LATERAL (SELECT event_time, known_at FROM event"
            "  WHERE source_id = h.source_id AND scenario_known_at <= %s"
            "  ORDER BY event_time DESC LIMIT 1) e ON true ORDER BY h.source_id",
            (at,),
        ).fetchall()
    return [
        with_outage_curve(r["source_id"], FeedMode(r["feed_mode"]), r["event_time"], r["known_at"], at)
        for r in rows
    ]


def outage_curve_hour(at: datetime) -> datetime | None:
    """The last whole hour at or before `at` at which the replayed outage curve has customers out."""
    from sgw.reports.sources import county_series

    hours = [t for t, counties in county_series().items() if t <= at and sum(counties.values()) > 0]
    return max(hours, default=None)


def with_outage_curve(
    source_id: str, mode: FeedMode, event_time: datetime | None, known_at: datetime | None, at: datetime
) -> FeedAtClock:
    if source_id == OUTAGE_SOURCE:
        hour = outage_curve_hour(at)
        if hour is not None and (event_time is None or hour > event_time):
            event_time, known_at = hour, hour
    return FeedAtClock(
        source_id,
        mode,
        event_time,
        known_at,
        freshness_check(source_id, event_time, at, last_known_at=known_at),
    )


def feed_health(feed: FeedAtClock, at: datetime, display_name: str) -> FeedHealthItem:
    measured, known = feed.last_event_time, feed.last_known_at
    return FeedHealthItem(
        source_id=feed.source_id,
        feed_mode=feed.feed_mode,
        ingest_lag_s=None if measured is None or known is None else int((known - measured).total_seconds()),
        product_age_s=None if measured is None else int((at - measured).total_seconds()),
        freshness_limit_s=freshness_limit(feed.source_id),
        stale=not feed.check.passed,
        display_name=display_name,
        measured_by="age" if feed.source_id in REPORTS_ON_SCHEDULE else "delay",
        status=feed_status(
            measured is not None, not feed.check.passed, on_change=feed.source_id not in REPORTS_ON_SCHEDULE
        ),
    )


FeedStatus = Literal["on_time", "late", "no_data", "quiet"]


def feed_status(delivered: bool, stale: bool, *, on_change: bool = False) -> FeedStatus:
    """Nothing delivered is `quiet` for a feed that reports only when something changes (not late, not
    missing), else `no_data`."""
    if not delivered:
        return "quiet" if on_change else "no_data"
    return "late" if stale else "on_time"


def late_arrivals(conn: psycopg.Connection[Any], at: datetime, source_ids: list[str]) -> CheckResult:
    """`ingest.late_arrivals` over the events known by `at`: known later than `LATE_FACTOR` limits."""
    limits = [LATE_FACTOR * freshness_limit(s) for s in source_ids]
    row = conn.execute(
        "SELECT count(*) FROM event e JOIN unnest(%s::text[], %s::int[]) AS l(source_id, limit_s)"
        " USING (source_id) WHERE e.scenario_known_at <= %s"
        " AND extract(epoch FROM e.known_at - e.event_time) > l.limit_s",
        (source_ids, limits, at),
    ).fetchone()
    late = int(row[0]) if row else 0
    return CheckResult(
        LATE_ARRIVALS, "warn", late == 0, f"{late} event(s) known later than {LATE_FACTOR}x freshness"
    )


def replaced_check_names(source_ids: list[str]) -> set[str]:
    return {LATE_ARRIVALS, *(f"freshness.{s}" for s in source_ids)}


def checks_at(conn: psycopg.Connection[Any], at: datetime) -> list[DqCheckOut]:
    """The freshness and late-arrival checks of the ingest asset, evaluated at `at`."""
    feeds = feeds_at(conn, at)
    results = [late_arrivals(conn, at, [f.source_id for f in feeds]), *(f.check for f in feeds)]
    return [
        DqCheckOut(
            check_id=f"{CHECK_PREFIX}:{c.name}",
            asset=INGEST_ASSET,
            name=c.name,
            severity=c.severity,
            passed=c.passed,
            observed=c.observed,
            checked_at=at,
        )
        for c in results
    ]
