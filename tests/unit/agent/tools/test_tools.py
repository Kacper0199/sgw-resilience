"""P2a tool executors without a database: persona refusal, refusal of unregistered and write tools, the
slot-only evidence line format, ledger numbering, and parity with the file-backed REST read models
(anomalies, readiness, what-if grid, damage queue) at the same scenario time."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from sgw.agent.render.slots import format_value
from sgw.agent.tools.context import ToolContext
from sgw.agent.tools.outcome import EvidenceLedger
from sgw.agent.tools.personas import TOOL_DOMAIN, tools_for
from sgw.agent.tools.reads import FileReads, NotAvailable
from sgw.agent.tools.registry import EXECUTORS, run
from sgw.contracts.api_models import (
    CrewItem,
    FeedHealthItem,
    ForecastResponse,
    OutageItem,
    ProposalSummary,
    QuantileBand,
    RiskItem,
    RiskResponse,
)
from sgw.contracts.tools import MODEL_VISIBLE_TOOLS, InjectedContext
from sgw.contracts.vocab import (
    ActionType,
    ApprovalFunction,
    Classification,
    CrewStatus,
    FeedMode,
    InitiatorKind,
    ProposalState,
    RiskBand,
    RunMode,
    Tier,
    UiSeverity,
)

T_LANDFALL = datetime(2024, 9, 27, 12, 0, tzinfo=UTC)
LINE_RE = re.compile(r"^\[E\d{1,3}\] [a-z_]+: [^;]+(; [a-z_]+=[^;]+)*; source=.+$")
SLOT_RE = re.compile(r"\{(E\d{1,3})\.([a-z][a-z0-9_]*)\}")
SUMMARY_KINDS = {
    "county_outage_total",
    "outage_summary",
    "crew_summary",
    "outage_surge_summary",
    "whatif_baseline",
}
K5_EXECUTORS = {"get_risk", "get_outages", "get_crews", "list_anomalies", "get_feed_health", "run_what_if"}
NEW_TOOLS = {"list_decisions", "get_readiness", "get_etr", "list_outage_surges", "get_damage_photos"}


class FakeReads(FileReads):
    """The DB-backed read models as fixed REST responses; the file-backed ones are the real artefacts."""

    def __init__(self, surge_report: Any = None) -> None:
        super().__init__()
        self.surge_report = surge_report

    async def risk(self, at: datetime, level: str) -> RiskResponse:
        items = [
            RiskItem(
                entity_id=fips,
                level="county",
                p_ppm=p,
                band=band,
                severity=UiSeverity.SEVERE,
                expected_impact=impact,
                drivers=["gust_max"],
            )
            for fips, p, band, impact in (
                ("45003", 812_000, RiskBand.VERY_HIGH, 61_234),
                ("13245", 455_000, RiskBand.HIGH, 22_001),
            )
        ]
        return RiskResponse(as_of=at, snapshot_id="SNAP-RISK-N", items=items, advisory_label="N")

    async def forecast(self, at: datetime, target: str, entity: str) -> ForecastResponse:
        if entity != "GLOBAL":
            raise NotAvailable(f"no {target} forecast for {entity} issued at or before 2024-09-27T12:00Z")
        series = [
            QuantileBand(valid_at=at, p10=41.5, p50=63.25, p90=97.75),
            QuantileBand(valid_at=at, p10=38.5, p50=58.5, p90=88.25),
        ]
        return ForecastResponse(
            forecast_id="FC-ETR-7",
            target="etr",
            entity_id=entity,
            model_version="etr-aft-v2",
            issued_at=at,
            series=series,
        )

    async def outages(self, at: datetime) -> list[OutageItem]:
        return [
            OutageItem(
                outage_id="OUT-AIK-2207",
                feeder_id="FDR-AIK-2207",
                customers_out=4_321,
                started_at=at,
                critical_facility_ids=["PS-17"],
            ),
            OutageItem(
                outage_id="OUT-AIK-2238",
                feeder_id="FDR-AIK-2238",
                customers_out=987,
                started_at=at,
                critical_facility_ids=[],
            ),
        ]

    async def crews(self, at: datetime) -> list[CrewItem]:
        return [
            CrewItem(
                crew_id="CRW-AIK-04",
                status=CrewStatus.STAGED,
                location_id="YARD-AIK-N",
                headcount=6,
                shift_end=at,
            ),
            CrewItem(
                crew_id="CRW-AIK-09", status=CrewStatus.ONSITE, location_id=None, headcount=4, shift_end=None
            ),
        ]

    async def crew_plan(self, at: datetime) -> Any:
        raise NotAvailable("no crew plan published")

    async def feeds(self, at: datetime | None) -> list[FeedHealthItem]:
        return [
            FeedHealthItem(
                source_id="nhc_advisories",
                feed_mode=FeedMode.REPLAY,
                ingest_lag_s=754,
                product_age_s=3_725,
                freshness_limit_s=21_600,
                stale=False,
                display_name="NHC advisories",
            )
        ]

    async def decisions(self, at: datetime, states: Sequence[str] | None) -> list[ProposalSummary]:
        row = {
            "proposal_id": "PRP-PS17-GEN",
            "decision_case_id": "DC-PS17-GEN",
            "action_type": next(iter(ActionType)).value,
            "title": "Stage a generator at PS-17",
            "tier": Tier.T3.value,
            "state": ProposalState.IN_REVIEW.value,
            "proposal_version": 1,
            "action_hash": "a" * 64,
            "decide_by_utc": "2024-09-26T04:45:00Z",
            "effective_decide_by_utc": "2024-09-26T03:29:00Z",
            "on_critical_path": True,
            "functions_required": ["water_operations", "logistics"],
            "approvals": [],
            "expires_at": None,
            "severity": "critical",
            "proposed_by": {
                "user_id": "wtr_lead_01",
                "display_name": "Water Incident Lead",
                "function": "water_operations",
                "initiator_kind": next(iter(InitiatorKind)).value,
            },
            "owner_function": "water_operations",
        }
        rows = [ProposalSummary.model_validate(row)]
        return [r for r in rows if not states or r.state.value in states]

    async def surges(self, at: datetime, fips: Sequence[str] | None, active_only: bool, limit: int) -> Any:
        if self.surge_report is None:
            raise NotAvailable("outage surge detection is not available")
        return self.surge_report


def ctx(role: ApprovalFunction = ApprovalFunction.COMMAND, start: int = 1, reads: Any = None) -> ToolContext:
    injected = InjectedContext(
        as_of=T_LANDFALL,
        user_id="ic_01",
        user_role=role,
        region_ids=["SC-45003"],
        run_mode=RunMode.REPLAY,
        classification_ceiling=Classification.C1,
    )
    return ToolContext(injected=injected, reads=reads or FakeReads(), ledger=EvidenceLedger(start=start))


SURGES = {
    "as_of": "2024-09-27T12:00:00Z",
    "scenario": "helene",
    "data_through": "2024-09-27T12:00:00Z",
    "counties_monitored": 123,
    "counties_surging": 7,
    "surges_total": 9,
    "first_detected_at": "2024-09-27T03:15:00Z",
    "model_version": "surge-cusum-v1",
    "source": "data/artefacts/surge/helene_series.csv.gz",
    "label": "C",
    "surges": [
        {
            "surge_id": "SRG-45003-240927T0315",
            "fips": "45003",
            "county": "Aiken",
            "state": "SC",
            "onset_at": "2024-09-27T02:45:00Z",
            "detected_at": "2024-09-27T03:15:00Z",
            "status": "active",
            "customers_out": 48_211,
            "peak_customers_out": 51_002,
            "baseline_customers_out": 37,
            "share_out": 0.6123,
            "confidence": 0.87,
            "confidence_band": "high",
            "dq_flags": [],
        }
    ],
}

CALLS: dict[str, dict[str, Any]] = {
    "get_risk": {"level": "county"},
    "get_forecast": {"target": "etr", "entity_id": "GLOBAL"},
    "get_outages": {},
    "get_crews": {},
    "list_anomalies": {"limit": 5},
    "get_feed_health": {},
    "run_what_if": {"scenario": "advisory_shift", "parameters": {}},
    "list_decisions": {},
    "get_readiness": {},
    "get_etr": {},
    "list_outage_surges": {},
    "get_damage_photos": {"limit": 3},
}


def test_executors_cover_the_k5_reads_and_the_new_tools() -> None:
    assert set(EXECUTORS) >= K5_EXECUTORS | NEW_TOOLS
    assert set(EXECUTORS) <= set(MODEL_VISIBLE_TOOLS)
    assert set(CALLS) == set(EXECUTORS)


@pytest.mark.parametrize("name", sorted(CALLS))
async def test_evidence_lines_are_slot_only(name: str) -> None:
    c = ctx(reads=FakeReads(SURGES))
    out = await run(name, CALLS[name], c)
    assert out.status == "ok" and not out.is_error, out.content
    assert isinstance(out.content, str)
    lines = out.content.splitlines()
    assert len(lines) == len(out.new_items) > 0
    for line, item in zip(lines, out.new_items, strict=True):
        assert LINE_RE.match(line), line
        assert line.startswith(f"[{item.id}] {item.kind}: ")
        assert {f for ref, f in SLOT_RE.findall(line) if ref == item.id} == set(item.values)
        assert item.entity_ids or item.kind in SUMMARY_KINDS, item
    for value_text in (format_value(v) for i in out.new_items for v in i.values.values()):
        if len(value_text) >= 3:
            assert value_text not in out.content, (name, value_text)


async def test_ids_follow_the_worker_ledger() -> None:
    c = ctx(start=101)
    first = await run("get_risk", {"level": "county"}, c)
    second = await run("get_crews", {}, c)
    assert [i.id for i in first.new_items] == ["E101", "E102"]
    assert second.new_items[0].id == "E103"
    assert [i.id for i in c.ledger.items] == [f"E{n}" for n in range(101, 101 + len(c.ledger.items))]


@pytest.mark.parametrize("tool", sorted(t for t, d in TOOL_DOMAIN.items() if d.value == "electric"))
async def test_water_roles_are_refused_electric_tools_without_an_error(tool: str) -> None:
    for role in (ApprovalFunction.WATER_OPERATIONS, ApprovalFunction.COMPLIANCE):
        c = ctx(role)
        out = await run(tool, CALLS.get(tool, {}), c)
        assert out.status == "refused" and not out.is_error and not out.new_items and not out.alerts
        assert "not shown to the" in str(out.content)
        assert c.ledger.items == []
        assert tool not in tools_for(role)


async def test_electric_roles_are_refused_water_anomalies() -> None:
    out = await run("list_anomalies", {}, ctx(ApprovalFunction.PLANNING))
    assert out.status == "refused" and not out.is_error
    assert "list_anomalies" not in tools_for(ApprovalFunction.PLANNING)


def test_the_duty_manager_reads_water_in_ask() -> None:
    ops = set(tools_for(ApprovalFunction.OPERATIONS))
    assert {"get_water_status", "list_anomalies", "get_outages"} <= ops
    assert set(tools_for(ApprovalFunction.COMMAND)) == set(MODEL_VISIBLE_TOOLS)
    assert set(tools_for(ApprovalFunction.COMMUNICATIONS)).isdisjoint(TOOL_DOMAIN)


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("scada_write", "SEC-14"),
        ("draft_proposal", "SEC-14"),
        ("optimise_prepositioning", "SEC-14"),
        ("weather_lookup", "SEC-13"),
    ],
)
async def test_unregistered_and_write_tools_are_refused_and_alerted(name: str, code: str) -> None:
    c = ctx()
    out = await run(name, {"cmd": "x"}, c)
    assert out.status == "refused" and out.is_error and not out.new_items
    assert out.alerts[0]["code"] == code and out.alerts[0]["tool"] == name
    assert c.ledger.items == []


async def test_invalid_arguments_and_unpublished_reads() -> None:
    bad = await run("get_risk", {"level": "state"}, ctx())
    assert bad.status == "error" and bad.is_error and str(bad.content).startswith("Invalid arguments")
    smuggled = await run("get_risk", {"level": "county", "as_of": "2030-01-01T00:00:00Z"}, ctx())
    assert smuggled.status == "error"
    missing = await run("get_etr", {"entity_id": "SC-NOWHERE"}, ctx())
    assert missing.status == "empty" and not missing.is_error
    assert not re.search(r"\d{4}-\d{2}-\d{2}T", str(missing.content))
    hexes = await run("get_risk", {"level": "h3"}, ctx())
    assert hexes.status == "empty"
    surges = await run("list_outage_surges", {}, ctx())
    assert surges.status == "empty" and "not available" in str(surges.content)


async def test_risk_and_etr_carry_the_read_model_values() -> None:
    c = ctx()
    risk = await run("get_risk", {"level": "county", "entity_ids": ["45003"]}, c)
    (aiken,) = risk.new_items
    assert aiken.entity_ids == ["45003"] and aiken.band is RiskBand.VERY_HIGH
    assert aiken.values["p"].value == 812_000 and aiken.values["expected_out"].value == 61_234
    assert "Aiken County, SC (45003)" in aiken.label
    etr = (await run("get_etr", {}, c)).new_items[0]
    assert (etr.values["p10"].value, etr.values["p50"].value, etr.values["p90"].value) == (38.5, 58.5, 88.25)
    assert etr.hints["trend_since_previous_issue"] == "lower" and etr.model_version == "etr-aft-v2"


async def test_outages_crews_feeds_decisions_filters() -> None:
    c = ctx()
    crit = await run("get_outages", {"only_critical": True}, c)
    total, summary, outage = crit.new_items
    assert total.kind == "county_outage_total"
    assert summary.values["open_outage_events"].value == 1
    assert summary.values["customers_on_these_events"].value == 4_321
    assert "PS-17" in outage.entity_ids and outage.hints["critical_facility"] == "yes"
    staged = await run("get_crews", {"status": ["staged"]}, c)
    assert staged.new_items[0].values["staged"].value == 1 and staged.new_items[0].values["people"].value == 6
    feed = (await run("get_feed_health", {"source_ids": ["nhc_advisories"]}, c)).new_items[0]
    assert feed.hints == {"feed_mode": "replay", "stale": "no"}
    decided = await run("list_decisions", {"states": ["approved"]}, c)
    assert decided.status == "empty"
    board = (await run("list_decisions", {}, c)).new_items[0]
    assert board.entity_ids == ["PRP-PS17-GEN", "DC-PS17-GEN"]
    assert board.values["effective_decide_by"].value == datetime(2024, 9, 26, 3, 29, tzinfo=UTC)
    assert board.hints["critical_path"] == "on" and "owner" not in board.hints
    assert "signed by Water operations and Logistics" in board.label
    assert "owned by Water operations" in board.label


async def test_surges_follow_the_su_interface() -> None:
    out = await run("list_outage_surges", {"county_fips": ["45003"]}, ctx(reads=FakeReads(SURGES)))
    summary, surge = out.new_items
    assert summary.values["counties_surging"].value == 7 and summary.model_version == "surge-cusum-v1"
    assert surge.entity_ids == ["SRG-45003-240927T0315", "45003"]
    assert surge.values["share_out"].value == 612_300 and surge.hints["confidence"] == "high"
    assert surge.hints["status"] == "active" and surge.hints["data_quality"] == "ok"


async def test_parity_with_file_backed_read_models() -> None:
    from sgw.api.readmodels import anomalies, readiness
    from sgw.models.cv import read as cv_read
    from sgw.models.whatif import read as whatif_read

    c = ctx()
    alarms = anomalies.anomalies(T_LANDFALL)
    got = (await run("list_anomalies", {"limit": 100}, c)).new_items
    assert [i.entity_ids[0] for i in got] == [a.anomaly_id for a in alarms]
    assert [i.values["score"].value for i in got] == [a.score_ppm for a in alarms]
    assert [i.values["detected"].value for i in got] == [a.detected_at for a in alarms]

    rows = readiness.readiness()
    got = (await run("get_readiness", {}, c)).new_items
    assert [i.entity_ids[0] for i in got] == [r.item_id for r in rows]
    assert [i.hints["status"] for i in got] == [r.status for r in rows]
    gaps = (await run("get_readiness", {"status": "gap", "domain": "water"}, c)).new_items
    assert [i.entity_ids[0] for i in gaps] == [
        r.item_id for r in rows if r.status == "gap" and r.domain.value == "water"
    ]

    grid = whatif_read.whatif()
    got = (await run("run_what_if", {"scenario": "crew_shift", "parameters": {}}, c)).new_items
    base, aid_late = got
    assert base.values["customer_hours"].value == round(grid.baseline.customer_hours)
    late = next(s for s in grid.scenarios if s.id == "aid_late")
    assert aid_late.entity_ids == ["aid_late"]
    assert aid_late.values["peak_customers_out"].value == late.peak_customers_out
    every = (
        await run("run_what_if", {"scenario": "advisory_shift", "parameters": {"scenario_id": "wind_up"}}, c)
    ).new_items
    assert every[1].entity_ids == ["wind_up"]
    none = await run("run_what_if", {"scenario": "pump_station_outage", "parameters": {}}, c)
    assert len(none.new_items) == 1 + len(grid.scenarios)

    queue = cv_read.damage_queue(cv_read.MAX_LIMIT)
    got = (await run("get_damage_photos", {"limit": 5}, c)).new_items
    photos = [i for i in got if i.kind == "damage_photo"]
    assert [p.entity_ids[0] for p in photos] == [r.image_id for r in queue.rows[:5]]
    assert [p.values["queue_rank"].value for p in photos] == [r.rank for r in queue.rows[:5]]
    case = queue.cases[0]
    scoped = (await run("get_damage_photos", {"case_id": case.case_id, "limit": 25}, c)).new_items
    assert scoped[0].kind == "damage_case" and scoped[0].entity_ids[0] == case.case_id
    assert {p.entity_ids[0] for p in scoped[1:]} == set(case.photo_ids)


async def test_all_feeder_outages_lead_with_the_briefing_county_total() -> None:
    from sgw.reports.sources import replay_status

    got = await run("get_outages", {}, ctx())
    total, summary, *_ = got.new_items
    assert total.kind == "county_outage_total" and summary.kind == "outage_summary"
    assert total.values["customers_out"].value == replay_status(T_LANDFALL).customers_out_now
    assert "narrower" in summary.label and "customers_out" not in summary.values


async def test_crews_list_the_mobile_resources_at_their_depot() -> None:
    got = await run("get_crews", {}, ctx())
    mobile = {i.entity_ids[0]: i for i in got.new_items if i.kind == "mobile_resource"}
    assert set(mobile) == {"MGEN-HALBERD-500", "FTK-WREN-3", "WTK-CORDGRASS-2"}
    gen = mobile["MGEN-HALBERD-500"]
    assert gen.values["capacity"].value == 500 and gen.values["capacity"].unit == "kW"
    assert "Graniteville depot" in gen.label and not re.search(
        r"\d", gen.label.replace("MGEN-HALBERD-500", "")
    )


def ian_ctx(at: datetime) -> ToolContext:
    from sgw.agent.tools.reads import PackReads

    c = ctx(reads=PackReads("postgresql://unused", "ian"))
    c.injected = c.injected.model_copy(update={"as_of": at})
    return c


async def test_on_the_ian_pack_outages_and_crews_are_the_scripted_exercise_data() -> None:
    from sgw.scenarios import packs
    from sgw.scenarios.reads import status

    at = datetime(2022, 10, 1, 12, 0, tzinfo=UTC)
    pack = packs.load("ian")
    got = await run("get_outages", {}, ian_ctx(at))
    total, facilities, *out = got.new_items
    assert total.values["customers_out"].value == status(pack, at).customers_out_now > 0
    assert "Scripted exercise data" in total.citation and facilities.kind == "facilities_summary"
    assert [i.entity_ids[0] for i in out] == pack.facilities_out(at)
    assert not [i for i in got.new_items if i.kind == "outage_summary"]
    crews = await run("get_crews", {}, ian_ctx(at))
    assert crews.new_items and all("MGEN" not in " ".join(i.entity_ids) for i in crews.new_items)
    assert "Scripted exercise data" in crews.new_items[0].citation


async def test_on_the_ian_pack_helene_models_say_not_modelled() -> None:
    at = datetime(2022, 10, 1, 12, 0, tzinfo=UTC)
    for tool, args in (
        ("list_outage_surges", {}),
        ("get_damage_photos", {}),
        ("get_risk", {"level": "county"}),
    ):
        out = await run(tool, args, ian_ctx(at))
        assert out.status == "empty" and "not modelled for this scenario" in str(out.content), tool


class MissedReads(FakeReads):
    async def missed_cases(self, at: datetime) -> list[Any]:
        from types import SimpleNamespace

        return [
            SimpleNamespace(
                decision_case_id="DC-D3-PS17-PRESSURE",
                title="Hold Cedarfall zone pressure above the state floor",
                effective_decide_by=datetime(2024, 9, 26, 5, 59, tzinfo=UTC),
            )
        ]


async def test_the_board_lists_a_deadline_that_passed_with_no_proposal_as_missed() -> None:
    """V4-10b: the board Ask reads is the Decisions page's: closed with no proposal is missed; a state
    filter (the proposal states) leaves it out."""
    board = (await run("list_decisions", {}, ctx(reads=MissedReads()))).new_items
    assert [b.entity_ids for b in board] == [["PRP-PS17-GEN", "DC-PS17-GEN"], ["DC-D3-PS17-PRESSURE"]]
    missed = board[1]
    assert missed.label.endswith("(DC-D3-PS17-PRESSURE), missed, no proposal before its deadline")
    assert missed.hints == {"state": "no_proposal", "due": "passed"}
    filtered = await run("list_decisions", {"states": ["in_review"]}, ctx(reads=MissedReads()))
    assert [b.entity_ids[-1] for b in filtered.new_items] == ["DC-PS17-GEN"]
