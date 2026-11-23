"""`/v1/events` stream logic: scope filter, resume by Last-Event-ID, resync, live fan-out, token re-check."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sgw.api.ledger import ControlSnapshot, LedgerRow
from sgw.api.stream import LedgerBroadcaster
from sgw.contracts.vocab import Classification, RunMode
from sgw.integrations.stream import IntegrationStream, start_cursor


def row(seq: int, event_type: str) -> LedgerRow:
    return LedgerRow(
        ledger_seq=seq,
        event_id=f"00000000-0000-4000-8000-{seq:012d}",
        event_type=event_type,
        event_time=datetime(2024, 9, 26, tzinfo=UTC) + timedelta(minutes=seq),
        run_mode=RunMode.REPLAY,
        classification=Classification.C1,
        payload={"n": seq},
    )


@dataclass
class Source:
    rows: dict[int, LedgerRow] = field(default_factory=dict)

    async def head(self) -> int:
        return max(self.rows, default=0)

    async def fetch_after(self, after: int, upto: int, limit: int) -> list[LedgerRow]:
        return [self.rows[k] for k in sorted(self.rows) if after < k <= upto][:limit]

    async def control(self) -> ControlSnapshot | None:
        return None

    async def existing(self, seqs: list[int]) -> list[int]:
        return [s for s in seqs if s in self.rows]


TYPES = ["OutageEvent", "DecisionApproved", "ClockBreached", "DecisionApproved", "CommitmentDrifted"]


async def collect(stream: IntegrationStream, last: str | None, n: int) -> list[str]:
    out: list[str] = []
    gen = stream.frames(last)
    try:
        async with asyncio.timeout(3):
            async for frame in gen:
                if not frame.startswith(":"):
                    out.append(frame)
                if len(out) >= n:
                    break
    finally:
        await gen.aclose()
    return out


def parse(frame: str) -> tuple[str, str, dict[str, object]]:
    lines = dict(line.split(": ", 1) for line in frame.strip().splitlines())
    return lines["id"], lines["event"], json.loads(lines["data"])


async def broadcaster(source: Source) -> LedgerBroadcaster:
    b = LedgerBroadcaster(source=source, poll_s=0.01, gap_hold_s=0.0, epoch=7)
    await b.prime()
    return b


async def alive() -> bool:
    return True


async def test_replay_filters_to_scoped_types_and_resumes() -> None:
    source = Source({i + 1: row(i + 1, t) for i, t in enumerate(TYPES)})
    b = await broadcaster(source)
    stream = IntegrationStream(b, frozenset({"DecisionApproved"}), alive, heartbeat_s=0.05)
    frames = await collect(stream, "v1.7.0", 2)
    parsed = [parse(f) for f in frames]
    assert [(i, e) for i, e, _ in parsed] == [("v1.7.2", "DecisionApproved"), ("v1.7.4", "DecisionApproved")]
    assert parsed[0][2]["ledger_seq"] == 2 and parsed[0][2]["data"] == {"n": 2}
    resumed = await collect(stream, "v1.7.2", 1)
    assert parse(resumed[0])[0] == "v1.7.4"


async def test_foreign_or_stale_ids_get_resync() -> None:
    assert start_cursor("ops.7.3", 7, 5) == (5, "bad_last_event_id")
    assert start_cursor("v1.6.3", 7, 5) == (5, "epoch_mismatch")
    assert start_cursor("v1.7.9", 7, 5) == (5, "epoch_mismatch")
    assert start_cursor("junk", 7, 5) == (5, "bad_last_event_id")
    assert start_cursor(None, 7, 5) == (5, None)
    b = await broadcaster(Source({1: row(1, "DecisionApproved")}))
    frames = await collect(IntegrationStream(b, frozenset({"DecisionApproved"}), alive), "v1.1.1", 1)
    assert parse(frames[0])[1] == "resync"


async def test_live_rows_are_filtered_and_revocation_ends_the_stream() -> None:
    source = Source()
    b = await broadcaster(source)
    await b.start()
    valid = {"ok": True}

    async def check() -> bool:
        return valid["ok"]

    try:
        stream = IntegrationStream(b, frozenset({"ClockBreached"}), check, heartbeat_s=0.05)
        task = asyncio.create_task(collect(stream, None, 1))
        await asyncio.sleep(0.1)
        source.rows[1] = row(1, "DecisionApproved")
        source.rows[2] = row(2, "ClockBreached")
        b.wake()
        frames = await task
        assert parse(frames[0])[:2] == ("v1.7.2", "ClockBreached")
        valid["ok"] = False
        gen = stream.frames(None)
        seen = [f async for f in gen]
        assert all(f.startswith(":") for f in seen)
    finally:
        await b.stop()
