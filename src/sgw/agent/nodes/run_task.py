"""RunTask: drives one graph run and turns it into K4 run frames (`run_start` .. `run_paused` / `run_end` /
`run_error`). LangGraph types never leave this module: nodes emit plain dicts through the stream writer and
the interrupt becomes `run_paused`. Frames are kept in order for SSE replay after `Last-Event-ID`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command

from sgw.agent.nodes.spine import SpineDeps
from sgw.contracts.vocab import Classification, RunMode
from sgw.contracts.wire import WireEvent, WireFrame

log = logging.getLogger("sgw.agent.run")
TERMINAL = frozenset({WireEvent.RUN_PAUSED, WireEvent.RUN_END, WireEvent.RUN_ERROR})


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RunTask:
    def __init__(
        self,
        *,
        run_id: str,
        thread_id: str,
        graph_id: str,
        graph: Any,
        deps: SpineDeps,
        user_id: str,
        user_role: str,
        run_mode: RunMode,
        run_input: dict[str, Any],
        wall_now: Callable[[], datetime] = _utc_now,
        scenario_now: Callable[[], datetime] | None = None,
        on_status: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self.run_id = run_id
        self.thread_id = thread_id
        self.graph_id = graph_id
        self.graph = graph
        self.deps = deps
        self.user_id = user_id
        self.user_role = user_role
        self.run_mode = run_mode
        self.run_input = run_input
        self.wall_now = wall_now
        self.scenario_now = scenario_now
        self.on_status = on_status
        self.frames: list[WireFrame] = []
        self.status = "created"
        self._changed = asyncio.Condition()
        self._task: asyncio.Task[None] | None = None

    @property
    def config(self) -> dict[str, Any]:
        return {"configurable": {"thread_id": f"{self.thread_id}:{self.run_id}"}}

    @property
    def finished(self) -> bool:
        return bool(self.frames) and self.frames[-1].type in TERMINAL

    async def _add(
        self, event: WireEvent, payload: dict[str, Any], classification: Classification, ns: list[str]
    ) -> None:
        frame = WireFrame(
            type=event,
            seq=len(self.frames),
            run_id=self.run_id,
            ns=ns,
            ts=self.wall_now(),
            scenario_time=self.scenario_now() if self.scenario_now else None,
            run_mode=self.run_mode,
            classification=classification,
            payload=payload,
        )
        async with self._changed:
            self.frames.append(frame)
            self._changed.notify_all()

    def start(self) -> asyncio.Task[None]:
        self._task = asyncio.create_task(self.run())
        return self._task

    def start_resume(self, wake: Any = "wake") -> asyncio.Task[None]:
        self.status = "running"
        self._task = asyncio.create_task(self.resume(wake))
        return self._task

    async def run(self) -> None:
        state = {
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "user_role": self.user_role,
            "run_mode": self.run_mode.value,
            "graph": self.graph_id,
            "input": self.run_input,
        }
        await self._add(
            WireEvent.RUN_START,
            {"graph": self.graph_id, "thread_id": self.thread_id, "input_keys": sorted(self.run_input)},
            Classification.C1,
            [],
        )
        await self._drive(state)

    async def resume(self, wake: Any = "wake") -> None:
        await self._add(WireEvent.STEP, {"node": "approval", "status": "resumed"}, Classification.C1, [])
        await self._drive(Command(resume=wake))

    async def _drive(self, graph_input: Any) -> None:
        self.status = "running"
        paused: tuple[Any, list[str]] | None = None
        try:
            async for part in self.graph.astream(
                graph_input,
                self.config,
                context=self.deps,
                stream_mode=["updates", "custom"],
                subgraphs=True,
                version="v2",
            ):
                ns = [str(x) for x in part["ns"]]
                if part["type"] == "custom":
                    data = part["data"]
                    await self._add(
                        WireEvent(data["event"]),
                        dict(data["payload"]),
                        Classification(data["classification"]),
                        ns,
                    )
                elif part["type"] == "updates" and "__interrupt__" in (part["data"] or {}):
                    paused = (part["data"]["__interrupt__"][0].value, ns)
        except asyncio.CancelledError:
            await self._set_status("cancelled")
            await self._add(WireEvent.RUN_END, {"status": "cancelled"}, Classification.C0, [])
            raise
        except Exception as exc:
            log.exception("run %s failed", self.run_id)
            await self._set_status("error")
            await self._add(
                WireEvent.RUN_ERROR,
                {"error": type(exc).__name__, "message": str(exc)[:300]},
                Classification.C1,
                [],
            )
            return
        if paused:
            await self._set_status("paused")
            await self._add(WireEvent.RUN_PAUSED, {"interrupt": paused[0]}, Classification.C1, paused[1])
            return
        values = (await self.graph.aget_state(self.config)).values
        await self._set_status(str(values.get("status", "ended")))
        await self._add(WireEvent.RUN_END, {"status": self.status}, Classification.C1, [])

    async def _set_status(self, status: str) -> None:
        self.status = status
        if self.on_status is not None:
            try:
                await self.on_status(status)
            except Exception:
                log.exception("run %s: status %s not persisted", self.run_id, status)

    async def state(self) -> dict[str, Any]:
        snap = await self.graph.aget_state(self.config)
        return dict(snap.values)

    async def cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def follow(
        self, after_seq: int = -1, heartbeat_s: float | None = None
    ) -> AsyncIterator[WireFrame | None]:
        """Frames after `after_seq`, then live ones until a terminal frame; `None` marks a heartbeat tick."""
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
