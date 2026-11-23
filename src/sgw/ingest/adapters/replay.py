"""K6 replay adapter: one source's K9 events served page by page, optionally gated by the scenario clock.

Stream faults (gap, delay, schema drift) reshape the whole feed once; page faults (out-of-order, duplicate,
flood) act inside each page, so cursors stay stable under every fault.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sgw.contracts.adapter import AdapterHealth, Coverage, FaultKind, FetchResult, Record
from sgw.contracts.events import EnvelopeBase
from sgw.contracts.vocab import FeedMode
from sgw.ingest.faults import FaultOutcome, FaultSpec, GapWindow, Reject, apply_faults

CURSOR_PREFIX = "r1:"
STREAM_FAULTS = frozenset({FaultKind.GAP, FaultKind.DELAY, FaultKind.SCHEMA_DRIFT})


class CursorError(ValueError):
    pass


def encode_cursor(position: int) -> str:
    return f"{CURSOR_PREFIX}{position}"


def decode_cursor(cursor: str | None) -> int:
    if cursor is None or cursor == "":
        return 0
    if not cursor.startswith(CURSOR_PREFIX) or not cursor[len(CURSOR_PREFIX) :].isdigit():
        raise CursorError(f"not a replay cursor: {cursor!r}")
    return int(cursor[len(CURSOR_PREFIX) :])


class ReplayAdapter:
    def __init__(
        self,
        source_id: str,
        events: list[EnvelopeBase],
        *,
        feed_mode: FeedMode = FeedMode.REPLAY,
        page_size: int = 500,
        faults: list[FaultSpec] | None = None,
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        foreign = {e.source_id for e in events} - {source_id}
        if foreign:
            raise ValueError(f"events from other sources: {sorted(foreign)}")
        self.source_id = source_id
        self.feed_mode = feed_mode
        self.page_size = page_size
        self._base = sorted(events, key=lambda e: (e.event_time, e.dedup_key))
        self._faults: list[FaultSpec] = []
        self._stream: FaultOutcome = FaultOutcome(events=[])
        self._as_of: datetime | None = None
        self._last_event: EnvelopeBase | None = None
        self._last_fetch_at: datetime | None = None
        self._served = 0
        self._pending_rejects: list[Reject] = []
        self._restream()
        for spec in faults or []:
            self.inject_fault(spec.kind, **dict(spec.params))

    def _restream(self) -> None:
        stream_specs = [s for s in self._faults if s.kind in STREAM_FAULTS]
        outcome = apply_faults(self._base, stream_specs)
        outcome.events = [self._as_feed(e) for e in outcome.events]
        self._stream = outcome

    def _as_feed(self, event: EnvelopeBase) -> EnvelopeBase:
        if event.feed_mode is self.feed_mode:
            return event
        return event.model_copy(update={"feed_mode": self.feed_mode})

    def set_clock(self, as_of: datetime | None) -> None:
        """Deliver only events whose `scenario_known_at` is at or before `as_of` (None: everything)."""
        self._as_of = as_of

    @property
    def rejects(self) -> list[Reject]:
        return list(self._stream.rejects)

    def drain_rejects(self) -> list[Reject]:
        """Rejects that sit inside the pages served since the last drain; a resumed cursor never repeats
        records it already passed."""
        fresh, self._pending_rejects = self._pending_rejects, []
        return fresh

    @property
    def gaps(self) -> list[GapWindow]:
        return list(self._stream.gaps)

    def fetch_since(self, cursor: str | None) -> FetchResult:
        start = decode_cursor(cursor)
        stream = self._stream.events
        end = start
        limit = min(len(stream), start + self.page_size)
        while end < limit and (self._as_of is None or stream[end].scenario_known_at <= self._as_of):
            end += 1
        clean = stream[start:end]
        at_end = end >= len(stream)
        self._pending_rejects.extend(
            r
            for r in self._stream.rejects
            if start <= r.position < end or (at_end and r.position >= end and (start < end or start == 0))
        )
        page_specs = [s for s in self._faults if s.kind not in STREAM_FAULTS]
        page = apply_faults(clean, page_specs).events if page_specs else list(clean)
        if clean:
            self._last_event = clean[-1]
            self._served += len(clean)
        self._last_fetch_at = self._as_of or (clean[-1].received_at if clean else self._last_fetch_at)
        complete = not self._stream.gaps and not self._stream.rejects
        return FetchResult(
            events=page,
            next_cursor=encode_cursor(end),
            coverage=Coverage(
                from_utc=clean[0].event_time if clean else None,
                to_utc=clean[-1].event_time if clean else None,
                complete=complete,
            ),
        )

    def snapshot(self) -> list[Record]:
        regions = sorted({e.region_id for e in self._base if e.region_id})
        return [
            Record(
                record_id=self.source_id,
                kind="feed",
                attributes={"events": len(self._base), "regions": regions, "feed_mode": self.feed_mode.value},
            )
        ]

    def health(self) -> AdapterHealth:
        last = self._last_event
        lag = int((last.received_at - last.event_time).total_seconds()) if last else None
        age = None
        if last and self._last_fetch_at:
            age = max(0, int((self._last_fetch_at - last.event_time).total_seconds()))
        total = len(self._base) or 1
        return AdapterHealth(
            source_id=self.source_id,
            last_success_at=self._last_fetch_at if self._served else None,
            ingest_lag_s=max(0, lag) if lag is not None else None,
            product_age_s=age,
            error_rate_ppm=min(1_000_000, len(self._stream.rejects) * 1_000_000 // total),
            feed_mode=self.feed_mode,
        )

    def inject_fault(self, kind: FaultKind, **params: Any) -> None:
        self._faults.append(FaultSpec(kind, params))
        if kind in STREAM_FAULTS:
            self._restream()
