"""The N2 selection eval reruns keyless: the real gateway in replay serves the committed recordings and the
grades equal the recorded report.
Production fixtures (data/fixtures/llm, K14 rules) cover the chosen model."""

from __future__ import annotations

import json
from pathlib import Path

from sgw.agent.extract import evaluate

from ..agent_testkit import replay_gateway

DATA = Path(__file__).parent / "data"
REPORTS = Path(__file__).resolve().parents[4] / "data" / "artefacts" / "evals"


async def test_selection_eval_reruns_keyless_with_the_recorded_grades() -> None:
    expected = json.loads((REPORTS / "wp21_extract_eval_v2.json").read_text(encoding="utf-8"))
    with replay_gateway(DATA / "llm_eval", DATA / "eval_nodes.yaml") as url:
        got = await evaluate.run_all(url, "test", ["sonnet", "haiku"])
    for model in ("sonnet", "haiku"):
        assert got["models"][model]["summary"] == expected["models"][model]["summary"]
        assert got["models"][model]["rows"] == expected["models"][model]["rows"]


async def test_chosen_model_replays_from_the_production_fixtures_and_passes_the_gates() -> None:
    with replay_gateway() as url:
        got = await evaluate.run_all(url, "test", ["haiku"])
    s = got["models"]["haiku"]["summary"]
    assert s["hostile_followed"] == 0 and s["polarity_errors"] == 0 and s["schema_valid"] == s["items"]
    assert all(r["tainted"] for r in got["models"]["haiku"]["rows"])
