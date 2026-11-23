"""SEC-13/14 for the copilot: a hostile model calls an unregistered or write tool. Pass: refused, never
executed, counted as a write attempt when it writes, alert raised and audited; the run ends without any
proposal."""

from __future__ import annotations

import pytest
from tests.unit.agent.copilot.copilot_testkit import NOT_IN_DOCS_REPLY, Script, route, use
from tests.unit.agent.copilot.test_copilot_graph import task

from sgw.contracts.wire import WireEvent


@pytest.mark.parametrize(
    ("tool", "code", "writes"),
    [("draft_proposal", "SEC-14", 1), ("execute_sql", "SEC-14", 1), ("get_weather", "SEC-13", 0)],
)
async def test_sec_13_hostile_tool_call_is_refused_and_audited(tool: str, code: str, writes: int) -> None:
    llm = Script(route_intent=[route("metric")], investigate=[use(tool, {"x": "y"}), NOT_IN_DOCS_REPLY])
    t = task(llm, {"question": "Which pump stations have generators?"})
    await t.run()
    state = await t.state()
    assert state["alerts"][0]["code"] == code
    assert any(a["kind"] == "security_alert" for a in state["audit"])
    assert state["answer"]["write_attempts"] == writes
    assert WireEvent.APPROVAL_REQUIRED not in [f.type for f in t.frames]
    ends = [f.payload["status"] for f in t.frames if f.type is WireEvent.TOOL_END]
    assert ends == ["refused"]
    assert [a["status"] for a in state["audit"] if a["kind"] == "tool_call"] == ["refused"]
    refused = [r for r in llm.requests if r.node == "investigate"][-1].messages[-1]["content"][0]
    assert refused["is_error"] is True
