"""K19 run-level event logs: capture the K4 frames of a green replay run per demo bookmark, and play them
back as a run of the API in DEMO_MODE.

A log plays back only on a database that `sgw demo goto` put at that bookmark (database comment), for the
same graph and graph version at the bookmark's run time, and only when the gateway cannot serve the run:
it refused the connection, or an earlier live run of that graph at that time hit a replay miss (request
hash not recorded), or the presenter set `SGW_DEMO_PLAYBACK=always`. A slow gateway is not a reason. A
FAULT_LLM_DOWN drill never plays back: it is there to show the M2 template path.

Playback is a stand-in for the screen only: it writes no proposal, approval or ledger row. Its `run_start`
frame carries `playback` (the replay banner and the source run); its terminal frame carries
`playback: true` and `resumable: false` (the run store says `done`, so a resume answers 409). The next
bookmark holds the proposals with the same ids, because logs and bookmarks come from one story run."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from sgw.contracts.eventlog import EventLogHeader, EventLogLine, read_eventlog, write_eventlog
from sgw.contracts.wire import SseId, WireEvent, WireFrame
from sgw.demo.bookmarks import BY_ID, Bookmark
from sgw.demo.snapshots import marked_bookmark

log = logging.getLogger("sgw.demo.eventlog")

REPO = Path(__file__).resolve().parents[3]
EVENTLOG_DIR = REPO / "data" / "fixtures" / "eventlog"
DIR_ENV = "SGW_EVENTLOG_DIR"
MODE_ENV = "SGW_DEMO_PLAYBACK"
SPEED_ENV = "SGW_DEMO_PLAYBACK_SPEED"
SCHEMA_VERSION = 1
LICENCE = "Apache-2.0 (synthetic data)"
MAX_GAP_MS = 1500
BANNER = (
    "Replay of a recorded run: the LLM gateway is not answering, so this run plays back the recorded one."
)
PROBE_TIMEOUT_S = 0.5
MISS_REASON = "gateway_424"
TERMINAL = frozenset({WireEvent.RUN_PAUSED, WireEvent.RUN_END, WireEvent.RUN_ERROR})


def eventlog_dir() -> Path:
    return Path(os.environ.get(DIR_ENV) or EVENTLOG_DIR)


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def capture(
    bm: Bookmark,
    run_id: str,
    graph_version: str,
    frames: Iterable[dict[str, Any]],
    ids: Iterable[str],
    gaps_ms: Iterable[int],
    directory: Path | None = None,
    captured_at: datetime | None = None,
) -> tuple[Path, EventLogHeader]:
    """Write `<dir>/<bookmark>.jsonl`: the run's frames from `run_start` up to its first terminal frame."""
    lines: list[EventLogLine] = []
    for raw, sse_id, gap in zip(frames, ids, gaps_ms, strict=True):
        frame = WireFrame.model_validate(raw)
        lines.append(EventLogLine(id=sse_id, delay_ms=max(0, int(gap)) if lines else 0, frame=frame))
        if frame.type in TERMINAL:
            break
    if not lines or lines[0].frame.type is not WireEvent.RUN_START:
        raise ValueError(f"{bm.id}: the captured run does not start with run_start")
    if lines[-1].frame.type not in TERMINAL:
        raise ValueError(f"{bm.id}: the captured run has no terminal frame")
    folder = directory or eventlog_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{bm.id}.jsonl"
    handle, tmp_name = tempfile.mkstemp(prefix=f".{bm.id}.", suffix=".tmp", dir=folder)
    os.close(handle)
    tmp = Path(tmp_name)
    try:
        header = write_eventlog(
            tmp,
            {
                "eventlog": "ps17-story",
                "schema_version": SCHEMA_VERSION,
                "bookmark": bm.id,
                "graph": bm.run_graph,
                "graph_version": graph_version,
                "captured_at": (captured_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
                "source_run_id": run_id,
                "licence": LICENCE,
            },
            lines,
        )
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path, header


@dataclass(frozen=True)
class EventLog:
    path: Path
    header: EventLogHeader
    lines: list[EventLogLine]

    @property
    def bookmark(self) -> Bookmark | None:
        return BY_ID.get(self.header.bookmark)


_CACHE: dict[Path, tuple[float, EventLog]] = {}


def load(path: Path) -> EventLog:
    mtime = path.stat().st_mtime
    cached = _CACHE.get(path)
    if cached is None or cached[0] != mtime:
        header, lines = read_eventlog(path)
        cached = (mtime, EventLog(path, header, lines))
        _CACHE[path] = cached
    return cached[1]


def load_all(directory: Path | None = None) -> list[EventLog]:
    """Every readable log; a stray, corrupt or half-written file is logged and skipped, never raised."""
    folder = directory or eventlog_dir()
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.jsonl")):
        try:
            out.append(load(path))
        except (OSError, ValueError) as exc:
            log.warning("event log %s skipped: %s", path.name, type(exc).__name__)
    return out


def _minute(at: datetime) -> datetime:
    return at.astimezone(UTC).replace(second=0, microsecond=0)


def match(
    graph: str,
    scenario_time: datetime,
    bookmark_id: str | None,
    graph_version: str,
    directory: Path | None = None,
    run_input: dict[str, Any] | None = None,
) -> EventLog | None:
    """The log of the bookmark the database is at, for this graph, graph version and input at its run time
    (`run_input` None skips the input check)."""
    if bookmark_id is None:
        return None
    at = _minute(scenario_time)
    for item in load_all(directory):
        h = item.header
        bm = item.bookmark
        if (
            bm is not None
            and h.bookmark == bookmark_id
            and h.graph == graph
            and h.graph_version == graph_version
            and _utc(bm.run_at) == at
            and (run_input is None or run_input == bm.run_input)
        ):
            return item
    return None


async def database_bookmark(pool: Any) -> str | None:
    """The bookmark `sgw demo goto` marked on the API's database (None after a seed or reset-db)."""
    if pool is None:
        return None
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT shobj_description(oid, 'pg_database') FROM pg_database"
                " WHERE datname = current_database()"
            )
            row = await cur.fetchone()
    except Exception:  # noqa: BLE001 - playback is best effort; the live run goes on
        log.warning("demo bookmark mark not readable", exc_info=True)
        return None
    if row is None:
        return None
    value = row[0] if not isinstance(row, dict) else next(iter(row.values()))
    return marked_bookmark(value)


async def gateway_unreachable(base_url: str, timeout_s: float = PROBE_TIMEOUT_S) -> bool:
    """True only when the gateway refuses or cannot take the connection; a slow or degraded answer is not."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=timeout_s)) as client:
            await client.get(f"{base_url.rstrip('/')}/healthz")
    except httpx.ConnectError:
        return True
    except httpx.HTTPError:
        return False
    return False


_MISSES: set[tuple[str, datetime]] = set()


def note_miss(graph: str, scenario_time: datetime) -> None:
    _MISSES.add((graph, _minute(scenario_time)))


def missed(graph: str, scenario_time: datetime) -> bool:
    return (graph, _minute(scenario_time)) in _MISSES


class MissRecorder:
    """Wraps a node's LLM client in DEMO_MODE: a replay miss (gateway 424) marks this graph at this scenario
    time, so the next run there plays the recorded one. The miss itself still raises (M2 template)."""

    def __init__(self, inner: Any, graph: str, scenario_time: Callable[[], datetime]) -> None:
        self.inner = inner
        self.graph = graph
        self.scenario_time = scenario_time

    async def create(self, request: Any) -> Any:
        from sgw.agent.nodes.llm import LlmUnavailable

        try:
            return await self.inner.create(request)
        except LlmUnavailable as exc:
            if exc.reason == MISS_REASON:
                note_miss(self.graph, self.scenario_time())
            raise


def playback_mode() -> str:
    mode = os.environ.get(MODE_ENV, "auto").strip().lower()
    return mode if mode in {"auto", "always", "off"} else "auto"


def playback_allowed(demo_mode: bool) -> bool:
    return demo_mode and playback_mode() != "off" and os.environ.get("FAULT_LLM_DOWN", "0") != "1"


async def gateway_cannot_answer(
    gateway_url: str,
    graph: str,
    scenario_time: datetime,
    probe: Callable[[str], Awaitable[bool]] = gateway_unreachable,
) -> bool:
    if playback_mode() == "always" or missed(graph, scenario_time):
        return True
    return await probe(gateway_url)


def _speed() -> float:
    try:
        return max(0.0, float(os.environ.get(SPEED_ENV, "1")))
    except ValueError:
        return 1.0


class PlaybackTask:
    """Duck-types `RunTask` for the run routes: frames of a recorded run, re-stamped to this run's id and the
    wall clock, released with the recorded gaps (capped at 1.5 s, scaled by `SGW_DEMO_PLAYBACK_SPEED`)."""

    def __init__(
        self,
        *,
        log: EventLog,
        run_id: str,
        thread_id: str,
        on_status: Callable[[str], Awaitable[None]] | None = None,
        speed: float | None = None,
        wall_now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.log = log
        self.run_id = run_id
        self.thread_id = thread_id
        self.graph_id = log.header.graph
        self.on_status = on_status
        self.speed = _speed() if speed is None else speed
        self.wall_now = wall_now
        self.frames: list[WireFrame] = []
        self.status = "created"
        self._changed = asyncio.Condition()
        self._task: asyncio.Task[None] | None = None

    @property
    def playback(self) -> dict[str, Any]:
        h = self.log.header
        return {
            "banner": BANNER,
            "eventlog": h.eventlog,
            "bookmark": h.bookmark,
            "source_run_id": h.source_run_id,
            "captured_at": h.captured_at.isoformat().replace("+00:00", "Z"),
        }

    @property
    def finished(self) -> bool:
        return bool(self.frames) and self.frames[-1].type in TERMINAL

    def _restamp(self, frame: WireFrame) -> WireFrame:
        payload = dict(frame.payload)
        if frame.type is WireEvent.RUN_START:
            payload["thread_id"] = self.thread_id
            payload["playback"] = self.playback
        if frame.type in TERMINAL:
            payload["playback"] = True
            payload["resumable"] = False
        return frame.model_copy(
            update={"seq": len(self.frames), "run_id": self.run_id, "ts": self.wall_now(), "payload": payload}
        )

    async def _emit(self, frame: WireFrame) -> None:
        async with self._changed:
            self.frames.append(frame)
            self._changed.notify_all()

    async def run(self) -> None:
        self.status = "running"
        await self._set_status("running")
        for line in self.log.lines:
            gap = min(line.delay_ms, MAX_GAP_MS) * self.speed / 1000
            if gap > 0 and self.frames:
                await asyncio.sleep(gap)
            await self._emit(self._restamp(line.frame))
        await self._set_status("done")

    def start(self) -> asyncio.Task[None]:
        self._task = asyncio.create_task(self.run())
        return self._task

    def start_resume(self, wake: Any = "wake") -> asyncio.Task[None]:
        async def ended() -> None:
            await self._emit(
                self._restamp(
                    WireFrame(
                        type=WireEvent.RUN_END,
                        seq=0,
                        run_id=self.run_id,
                        ts=self.wall_now(),
                        run_mode=self.log.lines[-1].frame.run_mode,
                        classification=self.log.lines[-1].frame.classification,
                        payload={"status": "playback_only"},
                    )
                )
            )

        self._task = asyncio.create_task(ended())
        return self._task

    async def _set_status(self, status: str) -> None:
        self.status = status
        if self.on_status is not None:
            with contextlib.suppress(Exception):
                await self.on_status(status)

    async def state(self) -> dict[str, Any]:
        return {"playback": self.playback, "status": self.status}

    async def cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def follow(
        self, after_seq: int = -1, heartbeat_s: float | None = None
    ) -> AsyncIterator[WireFrame | None]:
        next_seq = after_seq + 1
        while True:
            async with self._changed:
                if next_seq >= len(self.frames) and not self.finished:
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._changed.wait(), timeout=heartbeat_s)
                pending = self.frames[next_seq:]
            if not pending:
                if self.finished:
                    return
                yield None
                continue
            for frame in pending:
                yield frame
                next_seq = frame.seq + 1
            if self.finished and next_seq >= len(self.frames):
                return


def sse_ids(run_id: str, epoch: int, count: int) -> list[str]:
    return [SseId(stream=f"run:{run_id}", epoch=epoch, seq=i).render() for i in range(count)]
