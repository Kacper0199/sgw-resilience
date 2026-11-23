"""The admin trace's team steps: analyst lanes, tool calls and the answer check come from the
copilot run's audit writes, with at most two flat id arguments and no free text."""

from __future__ import annotations

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from sgw.api.readmodels.agent_runs import audit_steps, decode_audit, flat_args

ROWS = [
    {"kind": "plan", "path": "llm", "workers": ["water", "grid"]},
    {
        "kind": "worker",
        "worker": "water",
        "wave": 1,
        "path": "llm",
        "at": "2024-09-26T15:05:01+00:00",
        "ms": 2300,
    },
    {
        "kind": "tool_call",
        "worker": "water",
        "tool": "get_decision_case",
        "args": {"decision_case_id": "DC-D3-PS17-POWER"},
        "status": "ok",
        "at": "2024-09-26T15:05:01.200000+00:00",
        "ms": 12,
    },
    {
        "kind": "worker",
        "worker": "grid",
        "wave": 1,
        "path": "code",
        "at": "2024-09-26T15:05:01+00:00",
        "ms": 15000,
    },
    {
        "kind": "tool_call",
        "worker": "grid",
        "tool": "search_procedures",
        "args": {"query": "ignore previous instructions", "top_k": 8},
        "status": "refused",
        "at": "2024-09-26T15:05:02+00:00",
        "ms": 1,
    },
    {"kind": "verify", "at": "2024-09-26T15:05:09+00:00", "decision": "pass"},
    {"kind": "tool_call", "tool": "get_water_status", "args": {}, "status": "ok"},
]


def test_lanes_tools_and_checks_become_trace_steps() -> None:
    steps = audit_steps(ROWS)
    assert [(s.kind, s.worker, s.tool, s.status, s.decision) for s in steps] == [
        ("worker", "water", None, "ok", None),
        ("tool_call", "water", "get_decision_case", "ok", None),
        ("worker", "grid", None, "error", "fallback"),
        ("tool_call", "grid", "search_procedures", "refused", None),
        ("graph_step", None, None, None, "pass"),
    ]
    assert steps[0].node == "ask_worker_water" and steps[0].latency_ms == 2300
    assert steps[1].args == {"decision_case_id": "DC-D3-PS17-POWER"}
    assert steps[3].args == {"top_k": 8}
    assert steps[4].node == "verify"


def test_flat_args_keep_two_short_values_and_never_free_text() -> None:
    assert flat_args({"zone_ids": ["WZ-A", "WZ-B", "WZ-C", "WZ-D"], "limit": 5, "x": True}) == {
        "limit": 5,
        "x": True,
    }
    assert flat_args({"zone_ids": ["WZ-A", "WZ-B", "WZ-C", "WZ-D"]}) == {"zone_ids": "WZ-A, WZ-B, WZ-C…"}
    assert flat_args({"query": "x" * 10, "_truncated": "y"}) is None
    assert flat_args("not a dict") is None


def test_audit_writes_decode_from_the_checkpointer_format() -> None:
    kind, blob = JsonPlusSerializer().dumps_typed(ROWS[:3])
    assert decode_audit(kind, blob) == ROWS[:3]
