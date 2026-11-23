"""The team's analysts call the R27 executors through `PlatformToolRunner` — persona refusals, real
statuses, evidence numbered after the worker's earlier items, timings — and evidence offers chips (photo,
check, surge) only when the answer names them."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sgw.agent.copilot.link import evidence_refs, references
from sgw.agent.copilot.runner import PlatformToolRunner
from sgw.agent.copilot.tools import CopilotTools
from sgw.agent.render.evidence import EvidenceItem, SlotValue
from sgw.agent.tools.reads import NotAvailable
from sgw.contracts.api_models import ReadinessItem
from sgw.contracts.vocab import ApprovalFunction, Classification, Domain, Trust

from ..agent_testkit import platform_member_table as member_table
from .copilot_testkit import ctx

AT = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)


class FakeReads:
    def __init__(self) -> None:
        self.asked: list[datetime] = []

    async def readiness(self) -> list[ReadinessItem]:
        return [
            ReadinessItem(
                item_id="RDY-GEN-PS52",
                title="Generator load test at PS-52",
                domain=Domain.WATER,
                status="gap",
                owner_function=ApprovalFunction.WATER_OPERATIONS,
                due_utc=datetime(2024, 9, 27, 12, tzinfo=UTC),
            )
        ]

    async def feeds(self, at: datetime | None) -> list[Any]:
        self.asked.append(at)
        raise NotAvailable("no feed snapshot at 2024-09-26T15:05:00Z")


def tools_for(role: ApprovalFunction = ApprovalFunction.COMMAND) -> CopilotTools:
    heard: list[tuple[str, str]] = []
    t = CopilotTools(
        ctx=ctx(datetime(2024, 9, 26, 15, tzinfo=UTC)).model_copy(update={"user_role": role}),
        member_table=member_table(),
        search=None,
        search_ctx=ctx(AT).model_copy(update={"user_role": role}),
        observer=lambda phase, call, n: heard.append((phase, call["tool"])),
    )
    t.heard = heard  # type: ignore[attr-defined]
    return t


async def test_r27_tools_run_at_the_true_time_and_number_after_earlier_evidence() -> None:
    reads = FakeReads()
    runner = PlatformToolRunner(reads)
    tools = tools_for()
    await runner.run("get_decision_case", {"decision_case_id": "DC-D3-PS17-POWER"}, tools)
    out = await runner.run("get_readiness", {}, tools)
    await runner.run("get_feed_health", {}, tools)
    assert reads.asked == [AT]
    assert [i.id for i in tools.items] == ["E1", "E2"] and "E2" in str(out.content)
    assert [c["status"] for c in tools.calls] == ["ok", "ok", "empty"]
    assert all(isinstance(c["ms"], int) and c["at"] for c in tools.calls)
    assert tools.heard == [  # type: ignore[attr-defined]
        ("start", "get_decision_case"),
        ("end", "get_decision_case"),
        ("start", "get_readiness"),
        ("end", "get_readiness"),
        ("start", "get_feed_health"),
        ("end", "get_feed_health"),
    ]


async def test_statuses_are_real_and_role_refusals_are_answers() -> None:
    runner = PlatformToolRunner(FakeReads())
    tools = tools_for(ApprovalFunction.WATER_OPERATIONS)
    await runner.run("get_feed_health", {}, tools)
    refused = await runner.run("get_outages", {}, tools)
    await runner.run("drop_table", {}, tools)
    assert [c["status"] for c in tools.calls] == ["empty", "refused", "refused"]
    assert "not shown to the water operations role" in str(refused.content)
    assert [a["code"] for a in tools.alerts] == ["SEC-13"]
    assert "get_outages" not in runner.allowed("water_operations")


def _item(kind: str, label: str, entity_ids: list[str], **values: SlotValue) -> EvidenceItem:
    return EvidenceItem(
        id="E1",
        kind=kind,
        label=label,
        as_of=AT,
        citation="test",
        classification=Classification.C1,
        trust=Trust.SYSTEM,
        values=values,
        entity_ids=entity_ids,
    )


def test_photo_check_and_surge_chips_come_from_the_evidence_when_named() -> None:
    onset = SlotValue(value=datetime(2024, 9, 27, 4, tzinfo=UTC), format="utc_minute")
    pool = evidence_refs(
        [
            _item(
                "damage_photo", "Damage photo LADI-0042 on FDR-AIK-2207-S1", ["LADI-0042", "FDR-AIK-2207-S1"]
            ),
            _item("readiness_check", "Generator load test at PS-52 (RDY-GEN-PS52)", ["RDY-GEN-PS52"]),
            _item("outage_surge", "Outage surge in Aiken County, SC", ["SRG-1", "45003"], onset=onset),
            _item("pump_station", "PS-17 pump station", ["PS-17"]),
        ]
    )
    assert [(r["kind"], r["id"]) for r in pool] == [
        ("photo", "LADI-0042"),
        ("check", "RDY-GEN-PS52"),
        ("surge", "45003@2024-09-27T04:00:00Z"),
    ]
    text = "The Outage surge in Aiken County, SC began before RDY-GEN-PS52 was closed; LADI-0042 shows it."
    refs = references(
        text, evidence_ids=[], citations=[], member_table=member_table(), as_of=AT, region_ids=[], pool=pool
    )
    assert [(r["kind"], r["id"]) for r in refs] == [
        ("surge", "45003@2024-09-27T04:00:00Z"),
        ("check", "RDY-GEN-PS52"),
        ("photo", "LADI-0042"),
    ]
    assert (
        references(
            "Nothing named.", evidence_ids=[], citations=[], member_table=member_table(), as_of=AT, pool=pool
        )
        == []
    )
