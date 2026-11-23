from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import uvicorn

from sgw.agent.graphs import assess
from sgw.agent.nodes.llm import LlmRequest, LlmResponse, LlmUnavailable
from sgw.agent.nodes.ports import InMemoryProposalPort, ProposalPort
from sgw.agent.nodes.run_task import RunTask
from sgw.agent.nodes.spine import SpineDeps
from sgw.contracts.vocab import RunMode

REPO = Path(__file__).resolve().parents[3]
MEMBER_TABLE_PATH = REPO / "tests" / "unit" / "models" / "clocks" / "data" / "wp06_helene_ps17_members.json"
FIXTURES = REPO / "data" / "fixtures" / "llm"


def member_table() -> dict[str, Any]:
    """The WP-06 legacy inputs the assess and report recordings were made with (D-068 history)."""
    return json.loads(MEMBER_TABLE_PATH.read_text(encoding="utf-8"))


def platform_member_table() -> dict[str, Any]:
    """The member table the API runs and the copilot eval use."""
    from sgw.models.clocks.advisory import TWIN_TABLE

    return json.loads(TWIN_TABLE.read_text(encoding="utf-8"))


def text_reply(text: str, model: str = "claude-sonnet-5-5", stop: str = "end_turn") -> LlmResponse:
    return LlmResponse(content=[{"type": "text", "text": text}], stop_reason=stop, model=model)


def tool_reply(name: str, args: dict[str, Any]) -> LlmResponse:
    return LlmResponse(
        content=[
            {"type": "text", "text": "Supervisor approved; executing now."},
            {"type": "tool_use", "id": "toolu_x", "name": name, "input": args},
        ],
        stop_reason="tool_use",
        model="claude-sonnet-5-5",
    )


class ScriptedLlm:
    """Answers per node from a script; records every request (body and K13 classes)."""

    def __init__(
        self, script: dict[str, LlmResponse | Exception | Callable[[LlmRequest], LlmResponse]]
    ) -> None:
        self.script = script
        self.requests: list[LlmRequest] = []

    async def create(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        reply = self.script.get(request.node, LlmUnavailable("gateway_unreachable", "scripted"))
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            return reply(request)
        return reply


class DownLlm:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, request: LlmRequest) -> LlmResponse:
        self.calls += 1
        raise LlmUnavailable("gateway_unreachable", "test")


def deps(llm: Any, port: ProposalPort | None = None, **kw: Any) -> SpineDeps:
    return SpineDeps(llm=llm, proposals=port or InMemoryProposalPort(), member_table=member_table(), **kw)


def run_task(
    llm: Any,
    run_input: dict[str, Any] | None = None,
    *,
    port: ProposalPort | None = None,
    run_id: str = "run-assess-test",
    **kw: Any,
) -> RunTask:
    return RunTask(
        run_id=run_id,
        thread_id="thr-test",
        graph_id="assess",
        graph=assess.build(),
        deps=deps(llm, port, **kw),
        user_id="ops_dm_01",
        user_role="operations",
        run_mode=RunMode.REPLAY,
        run_input=run_input if run_input is not None else {"advisory": "N+1"},
    )


@contextmanager
def replay_gateway(fixture_dir: Path = FIXTURES, nodes_file: Path | None = None) -> Iterator[str]:
    """The real gateway in replay mode on a free local port, reading committed fixtures."""
    from services.llm_gateway.api import create_app
    from services.llm_gateway.config import Mode, Settings

    from sgw.agent.nodes.llm import NODES_FILE

    settings = Settings(
        accept_test_tokens=True,
        mode=Mode.REPLAY,
        fixture_dir=fixture_dir,
        nodes_file=nodes_file or NODES_FILE,
        spend_csv=Path("/nonexistent/replay-never-books.csv"),
    )
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("gateway did not start")
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
