from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from sgw.agent.nodes.llm import LlmUnavailable
from sgw.api import deps as api_deps
from sgw.api.errors import install_error_handlers
from sgw.api.routers import runs
from sgw.contracts.eventlog import read_eventlog
from sgw.contracts.wire import WireEvent, decode_stream
from sgw.demo import eventlog
from sgw.demo.bookmarks import ADVISORY_N, BOOKMARKS, bookmark
from sgw.demo.snapshots import MARK_PREFIX

from .agent_testkit import DownLlm, deps
from .test_runs_router import _user

AT_N = datetime.fromisoformat(ADVISORY_N.replace("Z", "+00:00"))
AT_N1 = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)
DEAD_GATEWAY = "http://127.0.0.1:9"


class _Cursor:
    def __init__(self, value: str | None) -> None:
        self.value = value

    async def fetchone(self) -> tuple[str | None]:
        return (self.value,)


class _Conn:
    def __init__(self, value: str | None) -> None:
        self.value = value

    async def execute(self, _sql: str) -> _Cursor:
        return _Cursor(self.value)


class MarkedPool:
    """Stands in for the API pool: the database comment `sgw demo goto` writes."""

    def __init__(self, bookmark_id: str | None) -> None:
        self.comment = MARK_PREFIX + bookmark_id if bookmark_id else None

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_Conn]:
        yield _Conn(self.comment)


def _app(demo_mode: bool, now: datetime = AT_N, marked: str | None = "at-n") -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(runs.router)
    app.dependency_overrides[api_deps.current_user] = lambda: _user("ops_dm_01")
    app.dependency_overrides[api_deps.writer] = lambda: _user("ops_dm_01")
    app.dependency_overrides[api_deps.csrf_protect] = lambda: _user("ops_dm_01")

    def factory(_: Request) -> Any:
        return deps(DownLlm())

    app.state.agent_runtime = runs.AgentRuntime(deps_factory=factory, epoch=7)
    app.state.sgw = SimpleNamespace(
        settings=SimpleNamespace(demo_mode=demo_mode),
        clock=SimpleNamespace(now=lambda: now),
        pool=MarkedPool(marked),
    )
    app.router.add_api_route(
        runs.RESUME_ROUTE[1], runs.resume_run, methods=[runs.RESUME_ROUTE[0]], status_code=202
    )
    return app


async def _run(
    app: FastAPI, graph: str = "assess", run_input: dict[str, Any] | None = None
) -> tuple[str, list[Any]]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client:
        thread_id = (await client.post("/api/threads", json={"module": "decisions"})).json()["thread_id"]
        r = await client.post(
            f"/api/threads/{thread_id}/runs", json={"graph": graph, "input": run_input or {"advisory": "N"}}
        )
        assert r.status_code == 202, r.text
        stream = await client.get(f"/api/threads/{thread_id}/events")
    return r.json()["run_id"], decode_stream(stream.text)


def _played(frames: list[Any]) -> bool:
    return "playback" in frames[0][1].payload


@pytest.fixture
async def recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Path]:
    """A K19 log of a real assess run, captured as bookmark at-n (assess at advisory N)."""
    monkeypatch.setenv(eventlog.DIR_ENV, str(tmp_path))
    monkeypatch.setenv(eventlog.SPEED_ENV, "0")
    monkeypatch.setenv("SGW_GATEWAY_URL", DEAD_GATEWAY)
    monkeypatch.delenv(eventlog.MODE_ENV, raising=False)
    monkeypatch.delenv("FAULT_LLM_DOWN", raising=False)
    monkeypatch.setattr(eventlog, "_MISSES", set())
    run_id, frames = await _run(_app(demo_mode=False))
    raw = [f.model_dump(mode="json") for _, f in frames]
    ids = [i.render() for i, _ in frames]
    path, header = eventlog.capture(bookmark("at-n"), run_id, "assess@1", raw, ids, [5] * len(raw), tmp_path)
    assert header.source_run_id == run_id and path.name == "at-n.jsonl"
    yield path


def test_capture_writes_a_k19_log_from_run_start_to_the_first_terminal_frame(recorded: Path) -> None:
    header, lines = read_eventlog(recorded)
    assert header.graph == "assess" and header.bookmark == "at-n" and header.eventlog == "ps17-story"
    assert lines[0].frame.type is WireEvent.RUN_START and lines[0].delay_ms == 0
    assert lines[-1].frame.type is WireEvent.RUN_PAUSED
    assert all(line.delay_ms == 5 for line in lines[1:])
    assert not list(recorded.parent.glob("*.tmp"))


def test_capture_refuses_a_run_without_a_terminal_frame(tmp_path: Path, recorded: Path) -> None:
    _, lines = read_eventlog(recorded)
    raw = [line.frame.model_dump(mode="json") for line in lines[:-1]]
    before = recorded.read_bytes()
    with pytest.raises(ValueError, match="terminal"):
        eventlog.capture(
            bookmark("at-n"), "run-x", "assess@1", raw, [ln.id for ln in lines[:-1]], [0] * len(raw), tmp_path
        )
    assert recorded.read_bytes() == before


def test_capture_replaces_a_log_atomically(recorded: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    header, lines = read_eventlog(recorded)
    raw = [ln.frame.model_dump(mode="json") for ln in lines]
    before = recorded.read_bytes()

    def broken(path: Path, *_a: Any, **_k: Any) -> None:
        path.write_text('{"half": ', encoding="utf-8")
        raise OSError("disk full")

    monkeypatch.setattr(eventlog, "write_eventlog", broken)
    with pytest.raises(OSError, match="disk full"):
        eventlog.capture(bookmark("at-n"), "run-y", "assess@1", raw, [ln.id for ln in lines], [0] * len(raw))
    assert recorded.read_bytes() == before and not list(recorded.parent.glob("*.tmp"))


def test_match_needs_the_marked_bookmark_graph_version_input_and_run_time(recorded: Path) -> None:
    assert eventlog.match("assess", AT_N, "at-n", "assess@1", run_input={"advisory": "N"}) is not None
    assert eventlog.match("assess", AT_N.replace(second=40), "at-n", "assess@1") is not None
    assert eventlog.match("assess", AT_N, None, "assess@1") is None
    assert eventlog.match("assess", AT_N, "at-n1", "assess@1") is None
    assert eventlog.match("assess", AT_N, "at-n", "assess@2") is None
    assert eventlog.match("assess", AT_N, "at-n", "assess@1", run_input={"advisory": "N+1"}) is None
    assert eventlog.match("assess", AT_N1, "at-n", "assess@1") is None
    assert eventlog.match("water_continuity", AT_N, "at-n", "assess@1") is None


async def test_stray_corrupt_and_truncated_logs_are_skipped(
    recorded: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (recorded.parent / "notes.jsonl").write_text("presenter notes, not a log\n", encoding="utf-8")
    text = recorded.read_text(encoding="utf-8")
    (recorded.parent / "at-n1.jsonl").write_text(text[: len(text) // 2], encoding="utf-8")
    logs = eventlog.load_all()
    assert [log.path.name for log in logs] == ["at-n.jsonl"]
    assert "notes.jsonl" in caplog.text and "at-n1.jsonl" in caplog.text
    _, frames = await _run(_app(demo_mode=True))
    assert _played(frames)


async def test_demo_run_plays_back_with_the_banner_when_the_gateway_refuses(recorded: Path) -> None:
    _, recorded_lines = read_eventlog(recorded)
    app = _app(demo_mode=True)
    run_id, frames = await _run(app)
    assert [f.type for _, f in frames] == [ln.frame.type for ln in recorded_lines]
    assert all(f.run_id == run_id for _, f in frames)
    assert [i.seq for i, _ in frames] == list(range(len(frames)))
    banner = frames[0][1].payload["playback"]
    assert banner["bookmark"] == "at-n" and "Replay of a recorded run" in banner["banner"]
    assert frames[-1][1].payload["playback"] is True and frames[-1][1].payload["resumable"] is False
    assert [f.payload for _, f in frames[1:-1]] == [ln.frame.payload for ln in recorded_lines[1:-1]]
    row = await app.state.agent_runtime.store.run(run_id)
    assert row.status == "done"


async def test_no_playback_outside_demo_mode_unmarked_or_with_another_input(recorded: Path) -> None:
    assert not _played((await _run(_app(demo_mode=False)))[1])
    assert not _played((await _run(_app(demo_mode=True, marked=None)))[1])
    assert not _played((await _run(_app(demo_mode=True, marked="at-n1")))[1])
    assert not _played((await _run(_app(demo_mode=True), run_input={"advisory": "N+1"}))[1])


async def test_a_slow_or_answering_gateway_does_not_trigger_playback(
    recorded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def slow(_url: str) -> bool:
        return False

    monkeypatch.setattr(eventlog.gateway_cannot_answer, "__defaults__", (slow,))
    assert not _played((await _run(_app(demo_mode=True)))[1])


async def test_probe_counts_only_a_refused_connection_as_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await eventlog.gateway_unreachable(DEAD_GATEWAY) is True

    def raising(exc: Exception) -> Any:
        class Client:
            def __init__(self, **_k: Any) -> None:
                pass

            async def __aenter__(self) -> Client:
                return self

            async def __aexit__(self, *_a: Any) -> None:
                return None

            async def get(self, _url: str) -> Any:
                raise exc

        return Client

    monkeypatch.setattr(eventlog.httpx, "AsyncClient", raising(httpx.ReadTimeout("slow")))
    assert await eventlog.gateway_unreachable("http://gw") is False
    monkeypatch.setattr(eventlog.httpx, "AsyncClient", raising(httpx.ConnectError("refused")))
    assert await eventlog.gateway_unreachable("http://gw") is True


async def test_a_replay_miss_makes_the_next_run_there_play_back(
    recorded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def answering(_url: str) -> bool:
        return False

    monkeypatch.setattr(eventlog.gateway_cannot_answer, "__defaults__", (answering,))

    class MissingRecording:
        async def create(self, _request: Any) -> Any:
            raise LlmUnavailable("gateway_424", "sgw_replay_miss")

    recorder = eventlog.MissRecorder(MissingRecording(), "assess", lambda: AT_N)
    with pytest.raises(LlmUnavailable):
        await recorder.create(object())
    assert eventlog.missed("assess", AT_N) and not eventlog.missed("assess", AT_N1)
    assert _played((await _run(_app(demo_mode=True)))[1])


async def test_live_demo_runs_record_replay_misses(recorded: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def answering(_url: str) -> bool:
        return False

    monkeypatch.setattr(eventlog.gateway_cannot_answer, "__defaults__", (answering,))

    class Miss(DownLlm):
        async def create(self, request: Any) -> Any:
            raise LlmUnavailable("gateway_424", "sgw_replay_miss")

    app = _app(demo_mode=True)
    app.state.agent_runtime.deps_factory = lambda _r: deps(Miss())
    _, frames = await _run(app)
    assert not _played(frames) and eventlog.missed("assess", AT_N)


async def test_no_playback_at_another_time_in_a_fault_drill_or_when_off(
    recorded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not _played((await _run(_app(demo_mode=True, now=AT_N1)))[1])
    monkeypatch.setenv("FAULT_LLM_DOWN", "1")
    assert not _played((await _run(_app(demo_mode=True)))[1])
    monkeypatch.setenv("FAULT_LLM_DOWN", "0")
    monkeypatch.setenv(eventlog.MODE_ENV, "off")
    assert not _played((await _run(_app(demo_mode=True)))[1])


async def test_always_mode_plays_back_without_probing(
    recorded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(eventlog.MODE_ENV, "always")
    assert await eventlog.gateway_cannot_answer("http://unused", "assess", AT_N, probe=_never_called)
    _, frames = await _run(_app(demo_mode=True))
    assert frames[0][1].payload["playback"]["bookmark"] == "at-n"


async def _never_called(_url: str) -> bool:
    raise AssertionError("always mode must not probe")


async def test_resuming_a_played_back_run_ends_it_without_touching_the_store(recorded: Path) -> None:
    log = eventlog.load(recorded)
    statuses: list[str] = []

    async def on_status(status: str) -> None:
        statuses.append(status)

    task = eventlog.PlaybackTask(log=log, run_id="run-new", thread_id="thr-new", on_status=on_status, speed=0)
    await task.start()
    assert statuses == ["running", "done"] and task.finished
    await task.start_resume()
    assert task.frames[-1].type is WireEvent.RUN_END and task.frames[-1].payload["status"] == "playback_only"
    seen = [f async for f in task.follow(-1) if f is not None]
    assert [f.seq for f in seen] == list(range(len(log.lines) + 1))


async def test_database_bookmark_reads_the_goto_mark() -> None:
    assert await eventlog.database_bookmark(MarkedPool("signed")) == "signed"
    assert await eventlog.database_bookmark(MarkedPool(None)) is None
    assert await eventlog.database_bookmark(None) is None


def test_committed_event_logs_cover_every_bookmark_and_verify() -> None:
    from sgw.agent.nodes.run_store import GRAPH_VERSIONS

    logs = {log.header.bookmark: log for log in eventlog.load_all(eventlog.EVENTLOG_DIR)}
    keyed = [b for b in BOOKMARKS if b.run_graph is not None]
    assert set(logs) == {b.id for b in keyed}
    for bm in keyed:
        log = logs[bm.id]
        assert log.header.graph == bm.run_graph
        assert log.header.graph_version == GRAPH_VERSIONS.get(bm.run_graph, f"{bm.run_graph}@1")
        assert log.lines[0].frame.type is WireEvent.RUN_START
        assert log.lines[-1].frame.type in eventlog.TERMINAL
        assert "sk-ant-" not in log.path.read_text(encoding="utf-8")
