"""Proposals: rule-made decision cases reach the copilot with their state (P-K3-01), a bare word of a
decision id is sent back for repair (P-K3-02), and the decision board says how soon each decision is due so
"what do I need to decide in the next three hours" is answerable (P-K3-03)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sgw.agent.copilot.runner import PlatformToolRunner, RecordedToolRunner, RecordingToolRunner
from sgw.agent.copilot.synthesis import id_fragments
from sgw.agent.copilot.tools import CopilotTools, clock_context
from sgw.agent.copilot.workers import BY_NAME, WorkerTask, prefetch
from sgw.agent.tools.executors import due_window
from sgw.contracts.vocab import ApprovalFunction, ProposalState, UiSeverity

from ..agent_testkit import platform_member_table as member_table
from .copilot_testkit import ctx

NOW = datetime(2024, 9, 27, 12, 0, tzinfo=UTC)
TANKER = "DC-D3-HSP-TALLOWBRANCH-TANKER"


@pytest.mark.parametrize(
    ("left", "word"),
    [
        (timedelta(minutes=-5), "passed"),
        (timedelta(minutes=40), "next_hour"),
        (timedelta(hours=2, minutes=5), "next_three_hours"),
        (timedelta(hours=5), "next_six_hours"),
        (timedelta(hours=20), "next_day"),
        (timedelta(days=3), "later"),
    ],
)
def test_the_board_says_how_soon_a_decision_is_due(left: timedelta, word: str) -> None:
    assert due_window(NOW + left, NOW) == word


def tanker() -> Any:
    due = datetime(2024, 9, 27, 14, 5, tzinfo=UTC)
    return SimpleNamespace(
        proposal_id="PRP-TANKER",
        decision_case_id=TANKER,
        title="Send a potable water tanker to Tallowbranch hospital",
        state=ProposalState.PROPOSED,
        severity=UiSeverity.SEVERE,
        on_critical_path=False,
        owner_function=ApprovalFunction.LOGISTICS,
        decide_by_utc=due,
        effective_decide_by_utc=due,
        expires_at=None,
        proposal_version=1,
        functions_required=[ApprovalFunction.LOGISTICS],
        approvals=[],
    )


class Board:
    scenario = "helene"

    async def decisions(self, at: datetime, states: Any) -> list[Any]:
        return [tanker()]


def tools_at(at: datetime) -> CopilotTools:
    table = member_table()
    return CopilotTools(
        ctx=clock_context(ctx(at), table), member_table=table, search=None, search_ctx=ctx(at)
    )


async def test_a_rule_made_case_answers_from_the_board_with_its_state_and_replays(tmp_path: Path) -> None:
    recorder = RecordingToolRunner(PlatformToolRunner(Board()))
    live = tools_at(NOW)
    out = await recorder.run("get_decision_case", {"decision_case_id": TANKER}, live)
    assert not out.is_error and live.calls[-1]["status"] == "ok"
    assert TANKER in str(out.content) and "state=proposed" in str(out.content)
    assert "due=next_three_hours" in str(out.content)
    recorder.save(tmp_path / "tools.json")
    again = await RecordedToolRunner(tmp_path / "tools.json").run(
        "get_decision_case", {"decision_case_id": TANKER}, tools_at(NOW)
    )
    assert again.content == out.content


def test_a_bare_word_of_a_decision_id_is_a_violation_and_the_whole_id_is_not() -> None:
    tools = tools_at(NOW)
    tools.items.append(
        SimpleNamespace(entity_ids=["DC-D3-PS17-POWER"], label="Hook up (DC-D3-PS17-POWER, D3)")  # type: ignore[arg-type]
    )
    assert id_fragments("PS-17 has POWER needed first.", tools) == ["id_fragment: POWER"]
    assert id_fragments("DC-D3-PS17-POWER is due; the ETR stands.", tools) == []


@pytest.mark.parametrize(("over", "board"), [(False, False), (True, True)])
def test_after_the_final_advisory_the_water_analyst_reads_the_board(over: bool, board: bool) -> None:
    calls = prefetch(
        BY_NAME["water"],
        WorkerTask("water", "Which decisions keep Tallowbranch hospital supplied?", ()),
        member_table(),
        NOW,
        False,
        over,
    )
    assert (("list_decisions", {}) in calls) is board


def test_after_the_final_advisory_the_water_analyst_reads_every_boil_water_notice_and_lift() -> None:
    """AB-OVR-014/023: the board lists its oldest twenty decisions, so the notices and lifts raised last are
    read by case; Helene only."""
    from sgw.agent.copilot.workers import notice_cases

    at = datetime(2024, 9, 30, 12, tzinfo=UTC)
    notices = notice_cases("helene", at)
    assert "DC-D3-PS17-CEDARFALL-BWA-LIFT" in notices and "DC-D3-PS52-DEERWATER-BWA" in notices
    assert notice_cases("ian", at) == ()
    task = WorkerTask("water", "What happened overnight?", ())
    calls = prefetch(BY_NAME["water"], task, member_table(), at, False, True, notices)
    read = [a["decision_case_id"] for n, a in calls if n == "get_decision_case"]
    assert set(notices) <= set(read) and len(read) == len(set(read))


def test_a_number_word_repair_names_counts_and_numbers_from_the_question() -> None:
    from sgw.agent.copilot.synthesis import synth_repair

    hinted = str(synth_repair(["number_word: Four"])["content"])
    plain = str(synth_repair(["stray_digit: 3"])["content"])
    assert "These decisions" in hinted and "window you asked about" in hinted
    assert "These decisions" not in plain
