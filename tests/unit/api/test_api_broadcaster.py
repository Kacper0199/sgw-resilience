from __future__ import annotations

import asyncio

import pytest

from sgw.api.stream import LedgerBroadcaster

from .api_testkit import FakeMonotonic, FakeSource


async def test_prime_starts_at_head_and_delivers_new_rows_in_order(source: FakeSource) -> None:
    for i in (1, 2, 3):
        source.add(i)
    b = LedgerBroadcaster(source=source)
    await b.prime()
    assert b.head_seq == 3
    sub = b.subscribe()
    source.add(4)
    source.add(5)
    assert await b.tick() == 2
    got = [sub.queue.get_nowait().ledger_seq for _ in range(2)]
    assert got == [4, 5]


async def test_gap_is_held_then_skipped_after_hold(source: FakeSource) -> None:
    mono = FakeMonotonic()
    b = LedgerBroadcaster(source=source, gap_hold_s=1.0, monotonic=mono)
    await b.prime()
    sub = b.subscribe()
    source.add(2)
    assert await b.tick() == 0, "seq 1 missing: hold"
    mono.t += 0.5
    source.add(1)
    assert await b.tick() == 2, "late commit filled the gap: both delivered in order"
    assert [sub.queue.get_nowait().ledger_seq for _ in range(2)] == [1, 2]
    source.add(4)
    assert await b.tick() == 0
    mono.t += 1.01
    assert await b.tick() == 1
    assert sub.queue.get_nowait().ledger_seq == 4
    assert b.stats.gaps_skipped == 1


async def test_overflowing_subscriber_is_dropped_not_blocking_others(source: FakeSource) -> None:
    b = LedgerBroadcaster(source=source, queue_max=2)
    await b.prime()
    slow, fast = b.subscribe(), b.subscribe()
    for i in range(1, 4):
        source.add(i)
    await b.tick()
    assert slow.overflowed and fast.overflowed
    assert b.subscriber_count == 0
    assert b.stats.overflows == 2
    healthy = b.subscribe()
    source.add(4)
    await b.tick()
    assert healthy.queue.get_nowait().ledger_seq == 4


async def test_run_loop_wakes_on_notify_before_poll_interval(source: FakeSource) -> None:
    b = LedgerBroadcaster(source=source, poll_s=30.0)
    await b.start()
    try:
        sub = b.subscribe()
        source.add(1)
        b.wake()
        row = await asyncio.wait_for(sub.queue.get(), timeout=2)
        assert row.ledger_seq == 1
    finally:
        await b.stop()


async def test_tick_errors_do_not_kill_the_loop(source: FakeSource) -> None:
    calls = {"n": 0}
    real_head = source.head

    async def flaky_head() -> int:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("db blip")
        return await real_head()

    source.head = flaky_head  # type: ignore[method-assign]
    b = LedgerBroadcaster(source=source, poll_s=0.01)
    await b.start()
    try:
        sub = b.subscribe()
        source.add(1)
        row = await asyncio.wait_for(sub.queue.get(), timeout=2)
        assert row.ledger_seq == 1
        assert b.stats.errors >= 1
    finally:
        await b.stop()


async def test_a_recreated_database_restarts_the_broadcaster_at_the_new_head(source: FakeSource) -> None:
    """G1: after `sgw reset-db` under a running API the new ledger restarts below the delivered head, so
    `tick` delivered nothing and the browser never saw N+1 proposals. The epoch check resets the head and
    makes every client resync."""
    state = {"epoch": 7}

    async def epoch() -> int:
        return state["epoch"]

    source.epoch = epoch  # type: ignore[attr-defined]
    for i in range(1, 51):
        source.add(i)
    resets: list[int] = []

    async def on_reset() -> None:
        if state["epoch"] == 9:
            raise RuntimeError("control_state not migrated yet")
        resets.append(state["epoch"])

    b = LedgerBroadcaster(source=source, on_reset=on_reset)
    await b.prime()
    assert (b.epoch, b.head_seq) == (7, 50)
    sub = b.subscribe()
    source.rows.clear()
    for i in range(1, 31):
        source.add(i)
    state["epoch"] = 8
    assert await b.tick() == 0, "below the old head: nothing passes without the epoch check"
    assert await b.check_epoch() is True
    assert (b.epoch, b.head_seq) == (8, 30) and b.resync_generation == 1 and resets == [8]
    assert sub.queue.get_nowait() is None
    source.add(31)
    assert await b.tick() == 1 and sub.queue.get_nowait().ledger_seq == 31
    assert await b.check_epoch() is False
    state["epoch"] = 9
    with pytest.raises(RuntimeError):
        await b.check_epoch()
    assert b.epoch == 8, "a failed reload leaves the old epoch, so the next check retries"
