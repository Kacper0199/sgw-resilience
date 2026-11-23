"""SEC-39 (STM 10.2, L7): invented asset ids and numbers in model text are blocked by the K15 verifier with
the D-073 id rule (exact match against the run's evidence bundle and the asset/document registry; no id-
shaped pattern passes). Blocked text is never shown: the node falls back to the M2 template with the same
slots."""

from __future__ import annotations

import json

import pytest
from tests.unit.agent.agent_testkit import ScriptedLlm, run_task, text_reply

from sgw.agent.render.verify import verify
from sgw.contracts.wire import WireEvent

GOOD = "Crew pre-positioning (DC-D2-CREWS-AIK) binds first, due by {E1.effective_decide_by}."
BAD_NARRATIVES = {
    "invented_asset": "Crews must stage at PS-91 before {E1.decide_by}.",
    "invented_feeder": "Patrol FDR-AIK-9999 first; due by {E1.decide_by}.",
    "invented_case": "Case DC-D3-PS99-POWER binds first, due {E1.decide_by}.",
    "bare_number": "About 48,000 customers lose power before {E1.decide_by}.",
    "bare_time": "Decide by 04:28Z, that is {E1.decide_by}.",
    "spelled_number": "Roughly twelve thousand customers depend on it; due {E1.decide_by}.",
    "unknown_slot": "Due by {E9.decide_by}.",
    "unknown_field": "Expected peak {E1.p50}.",
}


@pytest.mark.parametrize("case", sorted(BAD_NARRATIVES))
async def test_sec_39_invented_ids_and_numbers_never_reach_the_reader(case: str) -> None:
    bad = BAD_NARRATIVES[case]
    task = run_task(ScriptedLlm({"narrate": text_reply(bad)}))
    await task.run()
    state = await task.state()
    n = state["narrative"]
    assert n["path"] == "m2" and n["reason"] == "verifier_rejected"
    assert n["violations"]
    shown = "".join(f.payload.get("text", "") for f in task.frames if f.type is WireEvent.TEXT_DELTA)
    stream = json.dumps([f.model_dump(mode="json") for f in task.frames])
    for token in ("PS-91", "FDR-AIK-9999", "PS99", "48,000", "twelve thousand"):
        assert token not in shown and token not in stream


async def test_sec_39_valid_text_with_registry_ids_is_shown() -> None:
    task = run_task(ScriptedLlm({"narrate": text_reply(GOOD)}))
    await task.run()
    state = await task.state()
    assert state["narrative"]["path"] == "llm"
    assert "DC-D2-CREWS-AIK" in state["narrative"]["rendered"]


async def test_sec_39_rationale_with_invented_number_is_blocked() -> None:
    bad = json.dumps(
        {
            "rationale": "Stage 6 crews by {E1.decide_by}.",
            "preconditions": ["crews_available"],
            "evidence_ids": ["E1"],
        }
    )
    task = run_task(ScriptedLlm({"draft_rationale": text_reply(bad)}))
    await task.run()
    r = (await task.state())["rationale"]
    assert r["path"] == "m2" and any(v.startswith("stray_digit") for v in r["violations"])


def test_sec_39_shape_alone_never_passes() -> None:
    fields = {"E1": {"decide_by"}}
    for token in ("PS-17", "PS-18", "FDR-AIK-2207", "CRW-OSPREY-04"):
        assert verify(f"{token} first.", fields, frozenset()) != []
    assert verify("PS-17 first.", fields, frozenset({"PS-17"})) == []
