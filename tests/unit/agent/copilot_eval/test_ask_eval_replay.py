"""The Ask AI eval v1 reruns keyless on both splits — replay gateway on its recordings and node rules,
recorded search and R27 tool results — with the grades of `data/artefacts/evals/ask_eval_v1.json` (dev) and
`ask_eval_v1_heldout.json` (held-out, scored once at the R29 freeze). Latency is the live run's and is not
compared."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sgw.agent.copilot.runner import RecordedToolRunner
from sgw.agent.copilot.search import RecordedSearch
from sgw.agent.copilot_eval import run as ask_eval
from sgw.agent.nodes.llm import GatewayClient, GatewayTags

from ..agent_testkit import replay_gateway

EVALS = Path(__file__).resolve().parents[4] / "data" / "artefacts" / "evals"
REPORTS = {"dev": EVALS / "ask_eval_v1.json", "heldout": EVALS / "ask_eval_v1_heldout.json"}
TIMING = ("seconds", "seconds_p50", "seconds_p95")


def _no_time(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in r.items() if k not in TIMING} for r in rows]


@pytest.mark.parametrize("split", sorted(REPORTS))
async def test_ask_eval_reruns_keyless_with_the_recorded_grades(
    split: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sgw.agent.tools.personas import EXTRA

    monkeypatch.setitem(EXTRA, "on", False)
    expected = json.loads(REPORTS[split].read_text(encoding="utf-8"))
    with replay_gateway(ask_eval.LLM_DIR, ask_eval.EVAL_NODES) as url:
        llm = GatewayClient(url, tags=GatewayTags(purpose="test", wave="R27"))
        got = await ask_eval.run_all(
            llm,
            search=RecordedSearch(ask_eval.SEARCH),
            runner=RecordedToolRunner(ask_eval.TOOLS_FILE),
            split=split,
            with_nodes=bool(expected["nodes"]),
        )
    assert _no_time(got["turns"]) == _no_time(expected["turns"])
    assert got["nodes"] == expected["nodes"]
    for engine, summary in got["summary"]["engines"].items():
        want = expected["summary"]["engines"][engine]
        assert {k: v for k, v in summary.items() if k not in TIMING} == {
            k: v for k, v in want.items() if k not in TIMING
        }
    assert got["summary"]["policy_analyst"] == expected["summary"]["policy_analyst"]
