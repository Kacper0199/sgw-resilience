from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from sgw.agent.nodes import evidence_source as es
from sgw.agent.nodes.llm import GatewayClient, GatewayTags, k13_headers
from sgw.agent.nodes.ports import InMemoryProposalPort
from sgw.agent.render.evidence import EvidenceBundle
from sgw.agent.render.slots import slot_values
from sgw.contracts.vocab import Classification
from sgw.contracts.wire import SseId, WireEvent, decode_stream, encode_frame

from . import node_eval
from .agent_testkit import DownLlm, ScriptedLlm, replay_gateway, run_task


@pytest.fixture(scope="module")
def gateway() -> Iterator[str]:
    with replay_gateway() as url:
        yield url


def _client(url: str) -> GatewayClient:
    return GatewayClient(url, tags=GatewayTags(purpose="test", wave="W3"))


def _closed_port_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}"


async def _replay_run(url: str, port: InMemoryProposalPort | None = None) -> Any:
    task = run_task(_client(url), {"advisory": "N+1"}, port=port, run_id="run-replay-golden")
    await task.run()
    return task


async def test_replay_run_emits_run_start_to_run_paused(gateway: str) -> None:
    task = await _replay_run(gateway)
    types = [f.type for f in task.frames]
    assert types[0] is WireEvent.RUN_START
    assert types[-1] is WireEvent.RUN_PAUSED
    assert [f.seq for f in task.frames] == list(range(len(task.frames)))
    for needed in (
        WireEvent.TOOL_START,
        WireEvent.TOOL_END,
        WireEvent.AGENT_START,
        WireEvent.AGENT_END,
        WireEvent.TEXT_DELTA,
        WireEvent.ARTIFACT,
        WireEvent.APPROVAL_REQUIRED,
    ):
        assert needed in types, needed
    assert types.index(WireEvent.APPROVAL_REQUIRED) < types.index(WireEvent.RUN_PAUSED)
    state = await task.state()
    assert state["narrative"]["path"] == "llm", state["narrative"]["reason"]
    assert state["rationale"]["path"] == "llm", state["rationale"]["reason"]
    assert state["status"] == "awaiting_approval"
    text = "".join(f.payload["text"] for f in task.frames if f.type is WireEvent.TEXT_DELTA)
    assert text.strip() == state["narrative"]["rendered"].strip()
    assert "{E" not in text
    wire = "".join(
        encode_frame(f, SseId(stream=f"run:{task.run_id}", epoch=1, seq=f.seq)) for f in task.frames
    )
    assert [f for _, f in decode_stream(wire)] == task.frames


async def test_m2_path_gives_the_same_slot_values_with_the_gateway_stopped(gateway: str) -> None:
    live = await _replay_run(gateway)
    down = run_task(_client(_closed_port_url()), {"advisory": "N+1"}, run_id="run-gateway-down")
    await down.run()
    a, b = await live.state(), await down.state()
    assert b["narrative"]["path"] == "m2" and b["narrative"]["reason"] == "gateway_unreachable"
    assert b["rationale"]["path"] == "m2"
    assert down.frames[-1].type is WireEvent.RUN_PAUSED
    values_a = slot_values(EvidenceBundle.model_validate(a["bundle"]))
    values_b = slot_values(EvidenceBundle.model_validate(b["bundle"]))
    assert values_a == values_b
    for key, shown in a["narrative"]["slots_shown"].items():
        ref, field = key.split(".")
        assert values_b[ref][field] == shown
    for key, shown in b["narrative"]["slots_shown"].items():
        assert a["narrative"]["slots_shown"].get(key, shown) == shown
    assert a["approval"]["action_hash"] == b["approval"]["action_hash"]


async def test_prompt_declares_content_classes_and_binds_no_tools() -> None:
    llm = ScriptedLlm({})
    task = run_task(llm)
    await task.run()
    assert {r.node for r in llm.requests} == {"narrate", "draft_rationale"}
    for r in llm.requests:
        assert list(r.classes) == [Classification.C0, Classification.C1]
        assert k13_headers(r, GatewayTags())["x-sgw-classes"] == "C0,C1"
        body = r.body()
        assert "tools" not in body
        assert body["output_config"]["effort"] == "medium"
        assert "temperature" not in body and body["thinking"] == {"type": "adaptive"}
        dumped = json.dumps(body)
        for value in slot_values(EvidenceBundle.model_validate((await task.state())["bundle"]))[
            "E1"
        ].values():
            assert value not in dumped


async def test_resume_value_never_approves_and_store_state_does() -> None:
    port = InMemoryProposalPort()
    task = run_task(DownLlm(), port=port)
    await task.run()
    pid = (await task.state())["approval"]["proposal_id"]
    await task.resume({"approved": True, "approver": "ops_ic_01"})
    assert task.frames[-1].type is WireEvent.RUN_PAUSED
    assert port.effects == []
    assert (await task.state())["status"] == "awaiting_approval"
    port.proposals[pid]["state"] = "approved"
    await task.resume("wake")
    assert task.frames[-1].type is WireEvent.RUN_END
    assert (await task.state())["status"] == "executed"
    assert [e["proposal_id"] for e in port.effects] == [pid]


async def test_changed_action_hash_blocks_execution() -> None:
    port = InMemoryProposalPort()
    task = run_task(DownLlm(), port=port)
    await task.run()
    pid = (await task.state())["approval"]["proposal_id"]
    port.proposals[pid].update(state="approved", action_hash="0" * 64)
    await task.resume("wake")
    assert (await task.state())["status"] == "blocked"
    assert port.effects == []


def test_spine_tools_are_k5_tools_and_unknown_names_are_refused() -> None:
    with pytest.raises(es.UnknownTool):
        es.call_tool("shell", {"cmd": "id"}, {})
    with pytest.raises(es.UnknownTool):
        es.call_tool("draft_proposal", {}, {})


EVALS = Path(__file__).resolve().parents[3] / "data" / "artefacts" / "evals"


@pytest.mark.parametrize(
    ("results", "models", "nodes_file", "legacy"),
    [
        ("node_eval_v3.json", ("sonnet",), None, False),
        ("node_eval_v2.json", ("sonnet",), "nodes_v2.yaml", True),
        ("node_eval_v1.json", ("sonnet", "haiku"), "nodes_v1.yaml", True),
    ],
)
async def test_node_eval_reruns_keyless_with_the_recorded_grades(
    results: str, models: tuple[str, ...], nodes_file: str | None, legacy: bool, tmp_path: Path
) -> None:
    gw_nodes = tmp_path / "eval_nodes.yaml"
    gw_nodes.write_text(
        "version: 1\nnodes:\n"
        "  - {node: narrate, models: [sonnet, haiku], class_ceiling: C1}\n"
        "  - {node: draft_rationale, models: [sonnet, haiku], class_ceiling: C1}\n",
        encoding="utf-8",
    )
    expected = json.loads((EVALS / results).read_text(encoding="utf-8"))
    kwargs: dict[str, Any] = {"legacy": legacy, "cases": tuple(expected["cases"])}
    if nodes_file:
        kwargs["nodes_file"] = EVALS / nodes_file
    fixtures = EVALS / "llm_fixtures" if legacy else None
    with replay_gateway(nodes_file=gw_nodes, **({"fixture_dir": fixtures} if fixtures else {})) as url:
        got = await node_eval.run_all(url, "test", models, **kwargs)
    assert got["summary"] == expected["summary"]
    for case, per_model in expected["cases"].items():
        for model, row in per_model.items():
            for node, r in row.items():
                assert got["cases"][case][model][node]["grades"] == r["grades"]
                assert got["cases"][case][model][node]["text"] == r["text"]


async def test_text_is_emitted_only_after_verify_and_tier_comes_from_a_slot(gateway: str) -> None:
    task = await _replay_run(gateway)
    frames = task.frames
    verify_start = next(
        i
        for i, f in enumerate(frames)
        if f.type is WireEvent.STEP and f.payload == {"node": "verify", "status": "start"}
    )
    first_text = next(i for i, f in enumerate(frames) if f.type is WireEvent.TEXT_DELTA)
    assert first_text > verify_start
    state = await task.state()
    bundle = EvidenceBundle.model_validate(state["bundle"])
    policy = next(i for i in bundle.items if i.kind == "approval_policy")
    assert policy.values["tier"].value == state["approval"]["tier"] == "T3"
    assert "T3" not in state["narrative"]["text"]
    assert f"{{{policy.id}.tier}}" in state["narrative"]["text"]


async def test_failed_final_verify_shows_no_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from sgw.agent.nodes import spine
    from sgw.agent.render.verify import Violation

    def refuse(text: str, fields: Any, ids: Any) -> list[Violation]:
        return [Violation("test", "forced in the final verify node")]

    monkeypatch.setattr(spine, "verify", refuse)
    task = run_task(DownLlm())
    await task.run()
    state = await task.state()
    assert state["status"] == "blocked" and state.get("approval") is None
    assert not any(f.type in (WireEvent.TEXT_DELTA, WireEvent.APPROVAL_REQUIRED) for f in task.frames)
