"""`GET /v1/events`: the webhook event types as server-sent events, filtered by the token's read scopes.

Frames: `id: v1.<epoch>.<ledger_seq>` (K4 ids name `ops` or `run:` streams only, so `/v1` has its own),
`event: <type>`, `data: <WebhookEventV1, canonical JSON>` (the same bytes a webhook carries, without the
signature, since the TLS channel and the bearer token authenticate it).
`Last-Event-ID` resumes from the ledger; an id from another epoch or stream gets one `event: resync` frame and
the stream continues from the head. Comment heartbeats (`: hb <seq>`) keep proxies from closing the
connection; at each heartbeat the token is re-checked, so a revoked or expired token ends the stream.
Built on WP-08's `LedgerBroadcaster` (subscribe before replay, bounded queue, overflow -> catch up from the
database), so a slow integration client costs bounded memory and loses nothing.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from sgw.api.ledger import LedgerRow
from sgw.api.stream import PAGE, LedgerBroadcaster
from sgw.integrations.payload import body_bytes, event_v1

V1_STREAM = "v1"
_ID_RE = re.compile(r"^v1\.(?P<epoch>\d{1,12})\.(?P<seq>\d{1,18})$")


def render_id(epoch: int, seq: int) -> str:
    return f"{V1_STREAM}.{epoch}.{seq}"


def event_frame(row: LedgerRow, epoch: int) -> str:
    event = event_v1(
        event_id=row.event_id,
        event_type=row.event_type,
        ledger_seq=row.ledger_seq,
        event_time=row.event_time,
        payload=row.payload,
    )
    sse_id = render_id(epoch, row.ledger_seq)
    return f"id: {sse_id}\nevent: {row.event_type}\ndata: {body_bytes(event).decode()}\n\n"


def resync_frame(reason: str, epoch: int, head: int) -> str:
    sse_id = render_id(epoch, head)
    data = json.dumps({"reason": reason, "epoch": epoch, "head_ledger_seq": head}, sort_keys=True)
    return f"id: {sse_id}\nevent: resync\ndata: {data}\n\n"


def start_cursor(raw: str | None, epoch: int, head: int) -> tuple[int, str | None]:
    """(cursor, resync reason or None)."""
    if not raw:
        return head, None
    match = _ID_RE.match(raw.strip())
    if match is None:
        return head, "bad_last_event_id"
    seq = int(match["seq"])
    if int(match["epoch"]) != epoch or seq > head:
        return head, "epoch_mismatch"
    return seq, None


@dataclass
class IntegrationStream:
    broadcaster: LedgerBroadcaster
    event_types: frozenset[str]
    still_valid: Callable[[], Awaitable[bool]]
    heartbeat_s: float = 10.0

    async def _page(self, cursor: int, target: int) -> tuple[int, list[str]]:
        b = self.broadcaster
        async with b.replay_semaphore:
            rows = await b.source.fetch_after(cursor, target, PAGE)
        if not rows:
            return target, []
        frames = [event_frame(r, b.epoch) for r in rows if r.event_type in self.event_types]
        return rows[-1].ledger_seq, frames

    async def frames(self, last_event_id: str | None) -> AsyncIterator[str]:
        b = self.broadcaster
        cursor, reason = start_cursor(last_event_id, b.epoch, b.head_seq)
        sub = b.subscribe()
        try:
            yield f": sgw v1 events ({','.join(sorted(self.event_types))})\n\n"
            if reason:
                yield resync_frame(reason, b.epoch, b.head_seq)
            target = b.head_seq
            while cursor < target:
                cursor, chunk = await self._page(cursor, target)
                for frame in chunk:
                    yield frame
            next_beat = time.monotonic()
            epoch = b.epoch
            while True:
                if epoch != b.epoch:
                    epoch, cursor = b.epoch, b.head_seq
                    yield resync_frame("epoch_mismatch", b.epoch, b.head_seq)
                if sub.overflowed:
                    sub = b.subscribe()
                    target = b.head_seq
                    while cursor < target:
                        cursor, chunk = await self._page(cursor, target)
                        for frame in chunk:
                            yield frame
                if time.monotonic() >= next_beat:
                    if not await self.still_valid():
                        return
                    yield f": hb {cursor}\n\n"
                    next_beat = time.monotonic() + self.heartbeat_s
                try:
                    row = await asyncio.wait_for(
                        sub.queue.get(), timeout=max(0.0, next_beat - time.monotonic())
                    )
                except TimeoutError:
                    continue
                if row is None or row.ledger_seq <= cursor:
                    continue
                cursor = row.ledger_seq
                if row.event_type in self.event_types:
                    yield event_frame(row, b.epoch)
        finally:
            b.unsubscribe(sub)
