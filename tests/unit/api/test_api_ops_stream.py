from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from sgw.api.ledger import LedgerRow
from sgw.api.stream import LedgerBroadcaster, OpsStream, resolve_last_event_id
from sgw.contracts.golden import build_micro_events
from sgw.contracts.wire import WireEvent, decode_stream

from .api_testkit import FakeMonotonic, FakeSource

GOLDEN = Path(__file__).resolve().parents[3] / "contracts" / "golden" / "streams" / "ops_ps17_hinge.sse"
SCENARIO_NOW = datetime(2024, 9, 26, 12, tzinfo=UTC)


def _stream(b: LedgerBroadcaster, heartbeat_s: float = 30.0) -> OpsStream:
    return OpsStream(broadcaster=b, scenario_now=lambda: SCENARIO_NOW, heartbeat_s=heartbeat_s)


async def _take(gen: AsyncIterator[str], n_frames: int, timeout: float = 2.0) -> str:
    out: list[str] = []
    frames = 0

    async def pull() -> None:
        nonlocal frames
        async for chunk in gen:
            out.append(chunk)
            if not chunk.startswith(":"):
                frames += 1
            if frames >= n_frames:
                return

    await asyncio.wait_for(pull(), timeout=timeout)
    return "".join(out)


def test_last_event_id_resolution() -> None:
    assert resolve_last_event_id(None, 7, 10).cursor is None
    assert resolve_last_event_id("ops.7.4", 7, 10).cursor == 4
    assert resolve_last_event_id("ops.6.4", 7, 10).resync
    assert resolve_last_event_id("ops.7.11", 7, 10).resync, "client ahead of the ledger: database was reset"
    assert resolve_last_event_id("garbage", 7, 10).resync, "an id we cannot honour asks for resync"
    foreign = resolve_last_event_id("run:abc.7.4", 7, 10)
    assert foreign.cursor is None and foreign.resync


async def test_fresh_client_gets_heartbeat_then_live_rows(source: FakeSource) -> None:
    for i in (1, 2):
        source.add(i)
    b = LedgerBroadcaster(source=source, epoch=7)
    await b.prime()
    gen = _stream(b).frames(None)
    first = await _take(gen, 1)
    ((sse_id, hb),) = decode_stream(first)
    assert hb.type is WireEvent.HEARTBEAT and sse_id.render() == "ops.7.2"
    assert hb.payload["head_ledger_seq"] == 2
    source.add(3)
    await b.tick()
    more = await _take(gen, 1)
    ((sse_id, frame),) = decode_stream(more)
    assert frame.type is WireEvent.LEDGER and frame.ledger_seq == 3 and sse_id.render() == "ops.7.3"
    await gen.aclose()
    assert b.subscriber_count == 0


async def test_reconnect_replays_exactly_the_missing_rows(source: FakeSource) -> None:
    for i in range(1, 11):
        source.add(i)
    b = LedgerBroadcaster(source=source, epoch=7)
    await b.prime()
    gen = _stream(b).frames("ops.7.4")
    text = await _take(gen, 1 + 6)
    seqs = [f.ledger_seq for _, f in decode_stream(text) if f.type is WireEvent.LEDGER]
    assert seqs == [5, 6, 7, 8, 9, 10]
    await gen.aclose()


async def test_epoch_mismatch_sends_resync_then_continues_from_head(source: FakeSource) -> None:
    source.add(1)
    b = LedgerBroadcaster(source=source, epoch=8)
    await b.prime()
    gen = _stream(b).frames("ops.7.1")
    text = await _take(gen, 2)
    frames = decode_stream(text)
    assert [f.type for _, f in frames] == [WireEvent.RESYNC, WireEvent.HEARTBEAT]
    assert frames[0][1].payload == {"reason": "epoch_mismatch", "epoch": 8, "snapshot_url": "/api/proposals"}
    await gen.aclose()


async def test_heartbeat_repeats_when_idle(source: FakeSource) -> None:
    b = LedgerBroadcaster(source=source, epoch=1)
    await b.prime()
    gen = _stream(b, heartbeat_s=0.05).frames(None)
    text = await _take(gen, 3)
    assert [f.type for _, f in decode_stream(text)] == [WireEvent.HEARTBEAT] * 3
    await gen.aclose()


async def test_slow_client_overflow_catches_up_from_database_without_loss(source: FakeSource) -> None:
    b = LedgerBroadcaster(source=source, epoch=1, queue_max=3)
    await b.prime()
    gen = _stream(b).frames(None)
    await _take(gen, 1)
    for i in range(1, 51):
        source.add(i)
    await b.tick()
    assert b.stats.overflows == 1
    text = await _take(gen, 50)
    seqs = [f.ledger_seq for _, f in decode_stream(text) if f.type is WireEvent.LEDGER]
    assert seqs == list(range(1, 51))
    await gen.aclose()


async def test_ops_frames_match_the_golden_stream(source: FakeSource) -> None:
    ledger = [e for e in build_micro_events() if e.source_id == "sgw-platform"]
    for i, e in enumerate(ledger, 1):
        dumped = e.model_dump(mode="json")
        source.rows[i] = LedgerRow(
            ledger_seq=i,
            event_id=str(e.event_id),
            event_type=e.type,
            event_time=e.event_time,
            run_mode=e.run_mode,
            classification=e.classification,
            payload=dumped["payload"],
        )
    b = LedgerBroadcaster(source=source, epoch=1)
    await b.prime()
    golden = [
        (i.render(), f.model_dump(mode="json", exclude={"ts"}))
        for i, f in decode_stream(GOLDEN.read_text(encoding="utf-8"))
        if f.type in (WireEvent.LEDGER, WireEvent.STATE)
    ]
    gen = _stream(b).frames("ops.1.0")
    text = await _take(gen, 1 + len(golden))
    ours = [
        (i.render(), f.model_dump(mode="json", exclude={"ts"}))
        for i, f in decode_stream(text)
        if f.type in (WireEvent.LEDGER, WireEvent.STATE)
    ]
    assert ours == golden
    await gen.aclose()


async def test_heartbeat_still_sent_under_continuous_flow(source: FakeSource) -> None:
    b = LedgerBroadcaster(source=source, epoch=1)
    await b.prime()
    gen = _stream(b, heartbeat_s=0.05).frames(None)
    await _take(gen, 1)
    beats = 0
    for i in range(1, 41):
        source.add(i)
        await b.tick()
        await asyncio.sleep(0.005)
        text = await _take(gen, 1)
        beats += sum(1 for _, f in decode_stream(text) if f.type is WireEvent.HEARTBEAT)
    assert beats >= 1, "a flow faster than the heartbeat interval must not starve heartbeats"
    await gen.aclose()


async def test_stream_ends_when_the_session_is_gone(source: FakeSource) -> None:
    b = LedgerBroadcaster(source=source, epoch=1)
    await b.prime()
    valid = {"ok": True}

    async def still_valid() -> bool:
        return valid["ok"]

    stream = OpsStream(
        broadcaster=b, scenario_now=lambda: SCENARIO_NOW, heartbeat_s=0.05, still_valid=still_valid
    )
    gen = stream.frames(None)
    await _take(gen, 2)
    valid["ok"] = False
    rest = [chunk async for chunk in gen]
    assert all(WireEvent.HEARTBEAT.value not in c for c in rest[1:])
    assert b.subscriber_count == 0


async def test_late_commit_in_a_skipped_gap_triggers_resync(source: FakeSource) -> None:
    mono = FakeMonotonic()
    b = LedgerBroadcaster(source=source, epoch=1, gap_hold_s=1.0, monotonic=mono)
    await b.prime()
    gen = _stream(b).frames(None)
    await _take(gen, 1)
    source.add(2)
    await b.tick()
    mono.t += 1.5
    await b.tick()
    text = await _take(gen, 1)
    assert [f.ledger_seq for _, f in decode_stream(text)] == [2]
    source.add(1)
    await b.tick()
    assert b.stats.late_rows == 1
    text = await _take(gen, 1)
    ((_, frame),) = decode_stream(text)
    assert frame.type is WireEvent.RESYNC and frame.payload["reason"] == "ring_overflow"
    mono.t += 31
    source.add(3)
    await b.tick()
    assert b._skipped == {}
    await gen.aclose()


def test_stream_slots_are_counted_without_overshoot(source: FakeSource) -> None:
    b = LedgerBroadcaster(source=source)
    assert b.try_open_stream(2) and b.try_open_stream(2)
    assert not b.try_open_stream(2)
    b.close_stream()
    assert b.try_open_stream(2)
    assert b.stats.streams_refused == 1
