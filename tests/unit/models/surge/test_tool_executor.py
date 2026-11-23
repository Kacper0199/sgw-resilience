from __future__ import annotations

from datetime import UTC, datetime

from sgw.agent.tools.context import ToolContext
from sgw.agent.tools.outcome import EvidenceLedger
from sgw.agent.tools.reads import FileReads
from sgw.agent.tools.registry import run
from sgw.contracts.tools import InjectedContext
from sgw.contracts.vocab import ApprovalFunction, Classification, RunMode
from sgw.models.surge.read import list_outage_surges

AS_OF = datetime(2024, 9, 27, 9, 0, tzinfo=UTC)


def _ctx(at: datetime) -> ToolContext:
    injected = InjectedContext(
        as_of=at,
        user_id="ic_01",
        user_role=ApprovalFunction.COMMAND,
        region_ids=["SC-45003"],
        run_mode=RunMode.REPLAY,
        classification_ceiling=Classification.C1,
    )
    return ToolContext(injected=injected, reads=FileReads(), ledger=EvidenceLedger(start=1))


async def test_copilot_tool_serves_the_real_detector_at_the_replay_clock() -> None:
    out = await run("list_outage_surges", {"active_only": True, "limit": 50}, _ctx(AS_OF))
    report = list_outage_surges(AS_OF, active_only=True, limit=50)
    summary, *surges = out.new_items
    assert out.status == "ok"
    assert summary.values["counties_surging"].value == report.counties_surging > 90
    assert [s.entity_ids[0] for s in surges] == [s.surge_id for s in report.surges]
    assert all(s.model_version == "surge-cusum-v1" for s in out.new_items)


async def test_copilot_tool_before_the_baseline_is_empty_not_an_error() -> None:
    out = await run("list_outage_surges", {}, _ctx(datetime(2024, 9, 13, tzinfo=UTC)))
    assert out.status == "empty" and not out.is_error
