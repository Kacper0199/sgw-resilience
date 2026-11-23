"""K4 `stream/ops`: ledger replay by `Last-Event-ID`, live fan-out, heartbeats, bounded per-client queues.

One `LedgerBroadcaster` per process tails the ledger (poll on the head, woken early by `NOTIFY sgw_ledger`
if a writer sends it) and fans rows out to subscribers. Each subscriber has a bounded queue; when it
overflows the subscriber is dropped from fan-out and its stream catches up from Postgres instead, so a
slow client costs memory O(queue) and never loses an event. Gaps in `ledger_seq` (rolled-back or
not-yet-committed inserts) are held for `gap_hold_s` before they are skipped, so a late commit is not
overtaken.

Order inside a connection: subscribe, then replay from the database up to the broadcaster's head, then drain
the live queue skipping anything already sent (subscribe before snapshot, DC-18).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

from sgw.api.ledger import ControlSnapshot, LedgerRow
from sgw.contracts.vocab import Classification, DegradedMode, KillLevel, RunMode
from sgw.contracts.wire import (
    HeartbeatPayload,
    ResyncPayload,
    SseId,
    StatePayload,
    WireEvent,
    WireFrame,
    encode_frame,
)

log = logging.getLogger("sgw.api.stream")

OPS_STREAM = "ops"
PAGE = 500
SNAPSHOT_URL = "/api/proposals"
STATE_TILE_EVENTS = {"DecisionClockUpdated": ("decision_clock", "decision_case_id")}


class LedgerSource(Protocol):
    async def head(self) -> int: ...

    async def fetch_after(self, after: int, upto: int, limit: int) -> list[LedgerRow]: ...

    async def control(self) -> ControlSnapshot | None: ...

    async def existing(self, seqs: list[int]) -> list[int]: ...


@dataclass(eq=False)
class Subscription:
    """`None` in the queue is a wake-up only (e.g. a late row made a resync necessary)."""

    queue: asyncio.Queue[LedgerRow | None]
    generation: int
    overflowed: bool = False


@dataclass
class _Gap:
    expected: int
    first_seen: float


@dataclass
class BroadcasterStats:
    delivered: int = 0
    overflows: int = 0
    gaps_skipped: int = 0
    polls: int = 0
    errors: int = 0
    subscribers_peak: int = 0
    late_rows: int = 0
    streams_refused: int = 0


@dataclass
class LedgerBroadcaster:
    source: LedgerSource
    poll_s: float = 0.25
    gap_hold_s: float = 1.0
    queue_max: int = 1000
    epoch: int = 1
    monotonic: Callable[[], float] = time.monotonic
    head_seq: int = 0
    control: ControlSnapshot | None = None
    stats: BroadcasterStats = field(default_factory=BroadcasterStats)
    on_control: Callable[[ControlSnapshot], None] | None = None
    on_reset: Callable[[], Awaitable[None]] | None = None
    late_window_s: float = 30.0
    replay_slots: int = 4
    resync_generation: int = 0
    _subs: set[Subscription] = field(default_factory=set)
    _skipped: dict[int, float] = field(default_factory=dict)
    _streams: int = 0
    _replay_sem: asyncio.Semaphore | None = None
    _wake: asyncio.Event = field(default_factory=asyncio.Event)
    _gap: _Gap | None = None
    _task: asyncio.Task[None] | None = None

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    @property
    def stream_count(self) -> int:
        return self._streams

    def try_open_stream(self, limit: int) -> bool:
        """Check and count in one step (no await in between), so concurrent connects cannot overshoot."""
        if self._streams >= limit:
            self.stats.streams_refused += 1
            return False
        self._streams += 1
        return True

    def close_stream(self) -> None:
        self._streams = max(0, self._streams - 1)

    @property
    def replay_semaphore(self) -> asyncio.Semaphore:
        if self._replay_sem is None:
            self._replay_sem = asyncio.Semaphore(self.replay_slots)
        return self._replay_sem

    def subscribe(self) -> Subscription:
        sub = Subscription(asyncio.Queue(maxsize=self.queue_max), self.resync_generation)
        self._subs.add(sub)
        self.stats.subscribers_peak = max(self.stats.subscribers_peak, len(self._subs))
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.discard(sub)

    def wake(self) -> None:
        self._wake.set()

    async def prime(self) -> None:
        """Start at the current head: subscribers replay anything older from the database themselves."""
        self.head_seq = await self.source.head()
        read = getattr(self.source, "epoch", None)
        if read is not None:
            self.epoch = await read()
        await self._refresh_control()

    async def start(self) -> None:
        await self.prime()
        self._task = asyncio.create_task(self._run(), name="sgw-ledger-broadcaster")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        last_control = 0.0
        while True:
            try:
                await self.tick()
                now = self.monotonic()
                if now - last_control >= 1.0:
                    await self._refresh_control()
                    last_control = now
            except asyncio.CancelledError:
                raise
            except Exception:
                self.stats.errors += 1
                log.exception("ledger broadcaster tick failed")
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_s)

    async def check_epoch(self) -> bool:
        """The database was dropped and recreated under a running API (`sgw reset-db`): its ledger starts
        again below the head this broadcaster delivered to, so no new row would ever pass `tick`. Restart at
        the new head with the new epoch and make every client resync. A source without `epoch()` never
        resets."""
        read = getattr(self.source, "epoch", None)
        if read is None:
            return False
        epoch = await read()
        if epoch == self.epoch:
            return False
        head = await self.source.head()
        if self.on_reset is not None:
            await self.on_reset()
        log.warning("ledger database recreated (epoch %s -> %s); clients resync", self.epoch, epoch)
        self.epoch, self.head_seq = epoch, head
        self._gap = None
        self._skipped.clear()
        self.resync_generation += 1
        for sub in list(self._subs):
            with contextlib.suppress(asyncio.QueueFull):
                sub.queue.put_nowait(None)
        return True

    async def _refresh_control(self) -> None:
        await self.check_epoch()
        snap = await self.source.control()
        if snap is not None:
            self.control = snap
            if self.on_control:
                self.on_control(snap)

    async def tick(self) -> int:
        """Deliver every row the gap rule allows; returns how many were delivered."""
        self.stats.polls += 1
        db_head = await self.source.head()
        delivered = 0
        while db_head > self.head_seq:
            rows = await self.source.fetch_after(self.head_seq, db_head, PAGE)
            if not rows:
                if not self._gap_expired(self.head_seq + 1):
                    break
                self._skip(range(self.head_seq + 1, db_head + 1))
                self.head_seq = db_head
                break
            stalled = False
            for row in rows:
                if row.ledger_seq != self.head_seq + 1 and not self._gap_expired(self.head_seq + 1):
                    stalled = True
                    break
                if row.ledger_seq != self.head_seq + 1:
                    self._skip(range(self.head_seq + 1, row.ledger_seq))
                self._gap = None
                self.head_seq = row.ledger_seq
                self._publish(row)
                delivered += 1
            if stalled:
                break
        self.stats.delivered += delivered
        await self._recheck_skipped()
        return delivered

    def _skip(self, seqs: range) -> None:
        now = self.monotonic()
        self.stats.gaps_skipped += len(seqs)
        for seq in seqs[-10_000:]:
            self._skipped[seq] = now

    async def _recheck_skipped(self) -> None:
        """A skipped seq that commits within `late_window_s` was never sent live: every client resyncs."""
        if not self._skipped:
            return
        cutoff = self.monotonic() - self.late_window_s
        self._skipped = {s: t for s, t in self._skipped.items() if t >= cutoff}
        if not self._skipped:
            return
        late = await self.source.existing(sorted(self._skipped))
        if not late:
            return
        for seq in late:
            self._skipped.pop(seq, None)
        self.stats.late_rows += len(late)
        self.resync_generation += 1
        log.warning("ledger rows %s committed after the gap hold; clients resync", late[:10])
        for sub in list(self._subs):
            with contextlib.suppress(asyncio.QueueFull):
                sub.queue.put_nowait(None)

    def _gap_expired(self, expected: int) -> bool:
        now = self.monotonic()
        if self._gap is None or self._gap.expected != expected:
            self._gap = _Gap(expected, now)
        return now - self._gap.first_seen >= self.gap_hold_s

    def _publish(self, row: LedgerRow) -> None:
        for sub in list(self._subs):
            try:
                sub.queue.put_nowait(row)
            except asyncio.QueueFull:
                sub.overflowed = True
                self._subs.discard(sub)
                self.stats.overflows += 1


def ledger_frames(row: LedgerRow, epoch: int, now: datetime) -> list[str]:
    sse_id = SseId(stream=OPS_STREAM, epoch=epoch, seq=row.ledger_seq)
    frame = WireFrame(
        type=WireEvent.LEDGER,
        seq=row.ledger_seq,
        ledger_seq=row.ledger_seq,
        ts=now,
        scenario_time=row.event_time,
        run_mode=row.run_mode,
        classification=row.classification,
        payload={"event_type": row.event_type, "event_id": row.event_id, "payload": row.payload},
    )
    out = [encode_frame(frame, sse_id)]
    tile = STATE_TILE_EVENTS.get(row.event_type)
    if tile and isinstance(row.payload.get(tile[1]), str):
        state = StatePayload(
            tile=tile[0],  # type: ignore[arg-type]
            entity_id=row.payload[tile[1]],
            version=row.ledger_seq,
            value=row.payload,
        )
        out.append(
            encode_frame(
                WireFrame(
                    type=WireEvent.STATE,
                    seq=row.ledger_seq,
                    ts=now,
                    scenario_time=row.event_time,
                    run_mode=row.run_mode,
                    classification=row.classification,
                    payload=state.model_dump(mode="json"),
                ),
                sse_id,
            )
        )
    return out


@dataclass(frozen=True)
class StreamStart:
    cursor: int | None
    resync: bool


def resolve_last_event_id(raw: str | None, epoch: int, head: int) -> StreamStart:
    """Where a connection starts: after the client's last seq, or at the head (fresh or resync).

    An id the server cannot honour (unparseable, another stream, another epoch, ahead of the ledger) means
    the client holds state this stream cannot continue, so it gets `resync` rather than a silent restart.
    """
    if not raw:
        return StreamStart(None, False)
    try:
        sse_id = SseId.parse(raw.strip())
    except ValueError:
        return StreamStart(None, True)
    if sse_id.stream != OPS_STREAM:
        return StreamStart(None, True)
    if sse_id.epoch != epoch or sse_id.seq > head:
        return StreamStart(None, True)
    return StreamStart(sse_id.seq, False)


@dataclass
class OpsStream:
    broadcaster: LedgerBroadcaster
    scenario_now: Callable[[], datetime]
    heartbeat_s: float = 10.0
    wall_now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    still_valid: Callable[[], Awaitable[bool]] | None = None

    def _heartbeat(self, cursor: int) -> str:
        b = self.broadcaster
        ctl = b.control
        now = self.wall_now()
        payload = HeartbeatPayload(
            head_ledger_seq=b.head_seq,
            server_time=now,
            kill_level=ctl.kill_level if ctl else KillLevel.K0,
            degraded_mode=ctl.degraded_mode if ctl else DegradedMode.M0,
        )
        frame = WireFrame(
            type=WireEvent.HEARTBEAT,
            seq=cursor,
            ts=now,
            scenario_time=self.scenario_now(),
            run_mode=ctl.run_mode if ctl else RunMode.REPLAY,
            classification=Classification.C1,
            payload=payload.model_dump(mode="json"),
        )
        return encode_frame(frame, SseId(stream=OPS_STREAM, epoch=b.epoch, seq=cursor))

    def _resync(self, reason: Literal["epoch_mismatch", "ring_overflow"] = "epoch_mismatch") -> str:
        b = self.broadcaster
        ctl = b.control
        now = self.wall_now()
        frame = WireFrame(
            type=WireEvent.RESYNC,
            seq=b.head_seq,
            ts=now,
            scenario_time=self.scenario_now(),
            run_mode=ctl.run_mode if ctl else RunMode.REPLAY,
            classification=Classification.C1,
            payload=ResyncPayload(reason=reason, epoch=b.epoch, snapshot_url=SNAPSHOT_URL).model_dump(
                mode="json"
            ),
        )
        return encode_frame(frame, SseId(stream=OPS_STREAM, epoch=b.epoch, seq=b.head_seq))

    async def _page(self, cursor: int, target: int) -> tuple[int, list[str]]:
        """One database page in (cursor, target]; returns the new cursor and frames. `target` is the head at
        the time the subscription existed, so everything after it is already queued and catch-up ends."""
        b = self.broadcaster
        async with b.replay_semaphore:
            rows = await b.source.fetch_after(cursor, target, PAGE)
        if not rows:
            return target, []
        out: list[str] = []
        for row in rows:
            out.extend(ledger_frames(row, b.epoch, self.wall_now()))
        return rows[-1].ledger_seq, out

    async def _beat(self, cursor: int) -> str | None:
        """A heartbeat, or `None` when the session behind this stream has ended (logout, expiry, switch)."""
        if self.still_valid is not None and not await self.still_valid():
            return None
        return self._heartbeat(cursor)

    async def frames(self, last_event_id: str | None) -> AsyncIterator[str]:
        b = self.broadcaster
        start = resolve_last_event_id(last_event_id, b.epoch, b.head_seq)
        sub = b.subscribe()
        try:
            yield ": sgw ops stream\n\n"
            if start.resync:
                yield self._resync()
            cursor = b.head_seq if start.cursor is None else start.cursor
            yield self._heartbeat(cursor)
            target = b.head_seq
            while cursor < target:
                cursor, chunk = await self._page(cursor, target)
                for text in chunk:
                    yield text
            next_beat = time.monotonic() + self.heartbeat_s
            epoch = b.epoch
            while True:
                if epoch != b.epoch:
                    epoch, cursor = b.epoch, b.head_seq
                    sub.generation = b.resync_generation
                    yield self._resync("epoch_mismatch")
                if sub.generation != b.resync_generation:
                    sub.generation = b.resync_generation
                    yield self._resync("ring_overflow")
                if sub.overflowed:
                    sub = b.subscribe()
                    target = b.head_seq
                    while cursor < target:
                        cursor, chunk = await self._page(cursor, target)
                        for text in chunk:
                            yield text
                if time.monotonic() >= next_beat:
                    beat = await self._beat(cursor)
                    if beat is None:
                        return
                    yield beat
                    next_beat = time.monotonic() + self.heartbeat_s
                timeout = max(0.0, next_beat - time.monotonic())
                try:
                    row = await asyncio.wait_for(sub.queue.get(), timeout=timeout)
                except TimeoutError:
                    continue
                if row is None or row.ledger_seq <= cursor:
                    continue
                cursor = row.ledger_seq
                for text in ledger_frames(row, b.epoch, self.wall_now()):
                    yield text
        finally:
            b.unsubscribe(sub)
