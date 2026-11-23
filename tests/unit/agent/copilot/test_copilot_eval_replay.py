"""The copilot dev eval reruns keyless (replay gateway, production fixtures, recorded search) with the
recorded grades: 0 write attempts, verifier-clean text, citations resolve,
unanswerable -> not in the documents."""

from __future__ import annotations

import json
from pathlib import Path

from sgw.agent.copilot import evaluate
from sgw.agent.copilot.search import DEMO_SEARCH, RecordedSearch

from ..agent_testkit import replay_gateway

REPORTS = Path(__file__).resolve().parents[4] / "data" / "artefacts" / "evals"


async def test_copilot_eval_reruns_keyless_with_the_recorded_grades() -> None:
    expected = json.loads((REPORTS / "copilot_eval_v4.json").read_text(encoding="utf-8"))
    with replay_gateway() as url:
        got = await evaluate.run_all(url, "test", search=RecordedSearch(DEMO_SEARCH))
    assert got["summary"] == expected["summary"]
    assert got["rows"] == expected["rows"]
    s = got["summary"]
    assert s["write_attempts"] == 0 and s["passed"] == s["items"] and s["unanswerable_correct"] == "1/1"
