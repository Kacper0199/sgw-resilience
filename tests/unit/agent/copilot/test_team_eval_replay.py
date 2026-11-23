"""The R27 team-node model choice reruns keyless (replay gateway on its own recordings and node rules,
recorded search) with the grades of `data/artefacts/evals/ask_team_nodes_dev_v1.json`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sgw.agent.copilot import team_eval
from sgw.agent.copilot.search import RecordedSearch
from sgw.agent.nodes.llm import GatewayClient, GatewayTags

from ..agent_testkit import replay_gateway

REPORT = Path(__file__).resolve().parents[4] / "data" / "artefacts" / "evals" / "ask_team_nodes_dev_v1.json"


async def test_team_node_eval_reruns_keyless_with_the_recorded_grades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sgw.agent.tools.personas import EXTRA

    monkeypatch.setitem(EXTRA, "on", False)
    expected = json.loads(REPORT.read_text(encoding="utf-8"))
    with replay_gateway(team_eval.DATA / "llm_eval", team_eval.EVAL_NODES) as url:
        llm = GatewayClient(url, tags=GatewayTags(purpose="test", wave="R27"))
        got = await team_eval.run_all(llm, RecordedSearch(team_eval.RECORDED_SEARCH))
    assert got["summary"] == expected["summary"]
    assert got["rows"] == expected["rows"]
    s = got["summary"]
    assert s["ask_plan:haiku"]["passed"] >= 11 and s["ask_worker_water:sonnet"]["passed"] == 3
