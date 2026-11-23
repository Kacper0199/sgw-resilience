"""K6 conformance suite. Adapter packages call `check_adapter(factory)` from their own parametrised test;
`tests/contracts/test_adapter_conformance.py` runs it over every adapter in `ADAPTER_FACTORIES`
(W1 adds theirs)."""

from __future__ import annotations

from collections.abc import Callable

from sgw.contracts.adapter import Adapter, AdapterHealth, FaultKind, FetchResult
from sgw.contracts.events import EnvelopeBase
from sgw.contracts.vocab import FeedMode

AdapterFactory = Callable[[], Adapter]


def check_adapter(factory: AdapterFactory) -> None:
    adapter = factory()
    assert isinstance(adapter, Adapter), "adapter must implement the K6 port"
    assert isinstance(adapter.feed_mode, FeedMode)

    first = adapter.fetch_since(None)
    assert isinstance(first, FetchResult)
    assert all(isinstance(e, EnvelopeBase) for e in first.events)
    assert all(e.feed_mode is adapter.feed_mode for e in first.events), "events carry the adapter's feed_mode"
    times = [e.event_time for e in first.events]
    assert times == sorted(times), "fetch_since returns events in event_time order"

    again = factory().fetch_since(None)
    assert [e.dedup_key for e in again.events] == [e.dedup_key for e in first.events], (
        "cursor None is idempotent"
    )
    tail = adapter.fetch_since(first.next_cursor)
    assert not {e.dedup_key for e in tail.events} & {e.dedup_key for e in first.events}, "cursor advances"

    dup = factory()
    dup.inject_fault(FaultKind.DUPLICATE)
    keys = [e.dedup_key for e in dup.fetch_since(None).events]
    assert set(keys) == {e.dedup_key for e in first.events}, "duplicates keep the same dedup_key"

    health = adapter.health()
    assert isinstance(health, AdapterHealth)
    assert health.feed_mode is adapter.feed_mode and health.source_id == adapter.source_id
    assert isinstance(adapter.snapshot(), list)
