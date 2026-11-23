"""The three report graphs on the real WP-14a gateway in replay mode with the committed recordings: LLM
path green, M2 path with identical slot values when the gateway is stopped, and the per-node eval
regraded keyless."""

from __future__ import annotations

import json
import shutil
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from sgw.agent.render.evidence import EvidenceBundle
from sgw.agent.render.slots import slot_values
from sgw.contracts.wire import SseId, WireEvent, decode_stream, encode_frame

from ..agent_testkit import FIXTURES, replay_gateway
from . import report_eval
from . import reports_testkit as rk

GRAPHS = ["etr", "sitrep", "after_action"]
EVAL_FIXTURES = rk.DATA / "llm_eval_fixtures"


@pytest.fixture(scope="module")
def gateway() -> Iterator[str]:
    with replay_gateway() as url:
        yield url


@pytest.fixture(scope="module")
def eval_gateway(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Replay gateway whose egress rules allow both measured models on the report nodes, serving the runtime
    recordings plus the eval-only ones (other model or older prompt) kept out of `data/fixtures/llm`."""
    root = tmp_path_factory.mktemp("eval")
    fixtures = root / "llm"
    for node in report_eval.NODE_OF.values():
        for src in (FIXTURES / node, EVAL_FIXTURES / node):
            shutil.copytree(src, fixtures / node, dirs_exist_ok=True)
    nodes = root / "eval_nodes.yaml"
    nodes.write_text(
        "nodes:\n"
        + "".join(
            f"  {n}: {{models: [sonnet, haiku], class_ceiling: C1}}\n" for n in report_eval.NODE_OF.values()
        ),
        encoding="utf-8",
    )
    with replay_gateway(fixture_dir=fixtures, nodes_file=nodes) as url:
        yield url


def _closed_port_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}"


@pytest.mark.parametrize("graph", GRAPHS)
async def test_replay_run_is_green_on_the_llm_path(gateway: str, graph: str) -> None:
    task = rk.run_task(graph, rk.gateway_client(gateway), run_id=f"run-{graph}-replay")
    await task.run()
    state = await task.state()
    n = state["narrative"]
    assert n["path"] == "llm", (n["reason"], n["violations"])
    types = [f.type for f in task.frames]
    assert types[0] is WireEvent.RUN_START
    assert types[-1] is (WireEvent.RUN_PAUSED if graph == "etr" else WireEvent.RUN_END)
    assert WireEvent.AGENT_START in types and WireEvent.TEXT_DELTA in types
    assert [f.seq for f in task.frames] == list(range(len(task.frames)))
    assert "{E" not in n["rendered"] and not report_eval.REPEATED.search(n["rendered"])
    wire = "".join(
        encode_frame(f, SseId(stream=f"run:{task.run_id}", epoch=1, seq=f.seq)) for f in task.frames
    )
    assert [f for _, f in decode_stream(wire)] == task.frames
    if graph == "etr":
        assert state["approval"]["tier"] == "T3"
        assert "has not been checked against a real storm" in n["rendered"]


@pytest.mark.parametrize("graph", GRAPHS)
async def test_m2_with_the_gateway_stopped_shows_the_same_slot_values(gateway: str, graph: str) -> None:
    live = rk.run_task(graph, rk.gateway_client(gateway), run_id=f"run-{graph}-live")
    down = rk.run_task(graph, rk.gateway_client(_closed_port_url()), run_id=f"run-{graph}-down")
    await live.run()
    await down.run()
    a, b = await live.state(), await down.state()
    assert a["narrative"]["path"] == "llm"
    assert b["narrative"]["path"] == "m2" and b["narrative"]["reason"] == "gateway_unreachable"
    assert slot_values(EvidenceBundle.model_validate(a["bundle"])) == slot_values(
        EvidenceBundle.model_validate(b["bundle"])
    )
    values = slot_values(EvidenceBundle.model_validate(b["bundle"]))
    for key, shown in a["narrative"]["slots_shown"].items():
        ref, field = key.split(".")
        assert values[ref][field] == shown, key
        assert b["narrative"]["slots_shown"].get(key, shown) == shown, key
    if graph == "etr":
        assert a["approval"]["action_hash"] == b["approval"]["action_hash"]
        assert down.frames[-1].type is WireEvent.RUN_PAUSED


async def test_node_eval_regrades_keyless_with_the_recorded_grades(eval_gateway: str, tmp_path: Path) -> None:
    out = tmp_path / "eval.json"
    await report_eval.main(eval_gateway, ["sonnet", "haiku"], "test", out, None)
    fresh = json.loads(out.read_text(encoding="utf-8"))
    committed = json.loads(report_eval.OUT.read_text(encoding="utf-8"))
    assert fresh["summary"] == committed["summary"]
    assert [(r["case"], r["model"], r["passed"]) for r in fresh["rows"]] == [
        (r["case"], r["model"], r["passed"]) for r in committed["rows"]
    ]
