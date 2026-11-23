from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from sgw.contracts.adapter import Adapter, AdapterHealth, Coverage, FaultKind, FetchResult, Record
from sgw.contracts.conformance import check_adapter
from sgw.contracts.events import EnvelopeBase
from sgw.contracts.golden import build_micro_events
from sgw.contracts.vocab import FeedMode


class FixtureReplayAdapter:
    """Reference adapter over the helene_micro fixture; the shape every W1 adapter follows."""

    source_id = "helene-micro-oms"
    feed_mode = FeedMode.SYNTHETIC
    page = 7

    def __init__(self) -> None:
        self._events = [
            e for e in build_micro_events() if e.source_id == "oms" or e.source_id == "ami-headend"
        ]
        self._faults: set[FaultKind] = set()

    def fetch_since(self, cursor: str | None) -> FetchResult:
        start = int(cursor or 0)
        chunk: list[EnvelopeBase] = self._events[start : start + self.page]
        if FaultKind.DUPLICATE in self._faults:
            chunk = chunk + chunk[:2]
            chunk.sort(key=lambda e: e.event_time)
        covered = (chunk[0].event_time, chunk[-1].event_time) if chunk else (None, None)
        return FetchResult(
            events=chunk,
            next_cursor=str(start + self.page),
            coverage=Coverage(from_utc=covered[0], to_utc=covered[1], complete=True),
        )

    def snapshot(self) -> list[Record]:
        return [Record(record_id="FDR-AIK-2207", kind="feeder", attributes={"region_id": "SC-45003"})]

    def health(self) -> AdapterHealth:
        return AdapterHealth(
            source_id=self.source_id,
            last_success_at=None,
            ingest_lag_s=0,
            product_age_s=0,
            error_rate_ppm=0,
            feed_mode=self.feed_mode,
        )

    def inject_fault(self, kind: FaultKind, **params: Any) -> None:
        self._faults.add(kind)


ADAPTER_FACTORIES: dict[str, Callable[[], Adapter]] = {"fixture_replay": FixtureReplayAdapter}


@pytest.mark.parametrize("name", sorted(ADAPTER_FACTORIES))
def test_adapter_conformance(name: str) -> None:
    check_adapter(ADAPTER_FACTORIES[name])


def test_broken_adapter_fails_conformance() -> None:
    class WrongMode(FixtureReplayAdapter):
        feed_mode = FeedMode.LIVE

    with pytest.raises(AssertionError, match="feed_mode"):
        check_adapter(WrongMode)
