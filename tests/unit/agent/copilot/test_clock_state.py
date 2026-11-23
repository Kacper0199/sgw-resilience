"""Clock state: after the final advisory a decision clock says whether its deadline passed and what became
of the decision (timed by its authority record on the scenario clock); local decision reads never hit the
analyst's platform-call limit."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sgw.agent.copilot.clock_state import clock_state
from sgw.agent.copilot.runner import LocalToolRunner, RecordedToolRunner, RecordingToolRunner
from sgw.agent.copilot.tools import CopilotTools, clock_context
from sgw.agent.copilot.workers import BY_NAME, WorkerTask, run_worker
from sgw.agent.nodes.llm import LlmResponse, node_config
from sgw.contracts.vocab import ProposalState

from ..agent_testkit import platform_member_table as member_table
from .copilot_testkit import ctx, final, text

DUE = datetime(2024, 9, 26, 23, 29, tzinfo=UTC)
LATER = datetime(2024, 9, 30, 12, 0, tzinfo=UTC)
ON_TIME = DUE - timedelta(hours=2)
CASE = "DC-D3-PS17-POWER"


def proposal(state: ProposalState, version: int = 1) -> Any:
    return SimpleNamespace(
        proposal_id=f"PRP-{state.value}-{version}",
        decision_case_id=CASE,
        state=state,
        proposal_version=version,
        effective_decide_by_utc=DUE,
    )


@pytest.mark.parametrize(
    ("proposals", "decided", "want"),
    [
        (
            [proposal(ProposalState.EXECUTED)],
            {"PRP-executed-1": ON_TIME},
            ("passed", "decided_on_time", "no"),
        ),
        (
            [proposal(ProposalState.APPROVED)],
            {"PRP-approved-1": DUE + timedelta(hours=1)},
            ("passed", "decided_late", "no"),
        ),
        ([proposal(ProposalState.APPROVED)], {}, ("passed", "decided", "no")),
        ([proposal(ProposalState.PROPOSED)], {}, ("passed", "missed", "yes")),
        ([proposal(ProposalState.EXPIRED)], {}, ("passed", "expired", "yes")),
        ([proposal(ProposalState.WITHDRAWN)], {}, ("passed", "closed", "no")),
        ([], {}, ("passed", "no_proposal", "yes")),
        (
            [proposal(ProposalState.EXPIRED), proposal(ProposalState.EXECUTED, 2)],
            {"PRP-executed-2": ON_TIME},
            ("passed", "decided_on_time", "no"),
        ),
    ],
)
def test_clock_state_reads_the_latest_proposal_and_its_authority_time(
    proposals: list[Any], decided: dict[str, datetime], want: tuple[str, str, str]
) -> None:
    got = clock_state(CASE, DUE, proposals, LATER, decided)
    assert (got["deadline"], got["decision"], got["missed"]) == want


def test_an_open_proposal_before_its_deadline_is_waiting() -> None:
    got = clock_state(CASE, DUE, [proposal(ProposalState.IN_REVIEW)], DUE - timedelta(hours=1), {})
    assert (got["deadline"], got["decision"], got["missed"]) == ("open", "waiting", "no")


class States:
    """A platform runner's reads: the decisions read only (no database, so no authority times)."""

    scenario = "helene"

    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    async def decisions(self, at: datetime, states: Any) -> list[Any]:
        return self.rows


def tools_at(at: datetime) -> CopilotTools:
    table = member_table()
    return CopilotTools(
        ctx=clock_context(ctx(at), table), member_table=table, search=None, search_ctx=ctx(at)
    )


@pytest.mark.parametrize(
    ("at", "settled"), [(datetime(2024, 9, 26, 15, 5, tzinfo=UTC), False), (LATER, True)]
)
async def test_the_platform_runner_settles_a_clock_only_after_the_final_advisory_and_the_state_replays(
    at: datetime, settled: bool, tmp_path: Path
) -> None:
    from sgw.agent.copilot.runner import PlatformToolRunner

    recorder = RecordingToolRunner(PlatformToolRunner(States([proposal(ProposalState.EXECUTED)])))
    out = await recorder.run("get_decision_case", {"decision_case_id": CASE}, tools_at(at))
    assert ("decision=decided" in str(out.content)) is settled
    assert ("deadline=passed" in str(out.content)) is settled
    recorder.save(tmp_path / "tools.json")
    again = await RecordedToolRunner(tmp_path / "tools.json").run(
        "get_decision_case", {"decision_case_id": CASE}, tools_at(at)
    )
    assert again.content == out.content
    saved = json.loads((tmp_path / "tools.json").read_text())
    assert [row.get("hints", {}).get("decision") for row in saved.values()] == (
        ["decided"] if settled else []
    )


async def test_local_decision_reads_do_not_use_up_the_platform_call_limit() -> None:
    cases = ["DC-D3-HSP-TALLOWBRANCH-WATER", "DC-D3-PS17-PRESSURE", CASE, "DC-D3-PS17-FUEL"]
    batch = LlmResponse(
        content=[
            {
                "type": "tool_use",
                "id": f"toolu_{n}",
                "name": "get_decision_case",
                "input": {"decision_case_id": c},
            }
            for n, c in enumerate(cases)
        ],
        stop_reason="tool_use",
        model="claude-sonnet-5-5",
    )

    class Llm:
        def __init__(self) -> None:
            self.replies = [batch, final(text("This is not in the documents."))]

        async def create(self, request: Any) -> LlmResponse:
            return self.replies.pop(0)

    spec = BY_NAME["water"]
    finding = await run_worker(
        spec,
        WorkerTask("water", "Which decisions keep Tallowbranch hospital supplied with water?", ()),
        ctx(),
        llm=Llm(),
        config=node_config(spec.node),
        member_table=member_table(),
        runner=LocalToolRunner(),
        search=None,
        period="Scenario period.",
        max_steps=3,
    )
    model_calls = [c for c in finding.tool_calls if c["tool"] == "get_decision_case"]
    assert [c["status"] for c in model_calls[-len(cases) :]] == ["ok"] * len(cases)


def test_passages_of_the_procedure_the_findings_name_come_first() -> None:
    from sgw.agent.copilot.synthesis import named_first

    def hit(doc: str) -> Any:
        return SimpleNamespace(hit=SimpleNamespace(doc_id=doc))

    hits = [hit("PCN 02.044"), hit("GEP 00.005"), hit("DOM 14.206")]
    order = named_first(hits, "DOM 14.206 sets the revision rule.")
    assert [g.hit.doc_id for g in order] == ["DOM 14.206", "PCN 02.044", "GEP 00.005"]
