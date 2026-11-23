"""Deterministic evidence for `assess`: computed decision clocks, the D1 event-type recommendation
when forecast inputs are given, and untrusted field notes (quarantined, they only taint the run).

Code picks every tool call (DC-08); the model never chooses a tool here. Tool names are K5 names; anything
else is refused and raises a security alert (SEC-13/14).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from sgw.agent.render.evidence import EvidenceItem, SlotValue
from sgw.contracts.tools import TOOLS
from sgw.contracts.vocab import Classification, Trust
from sgw.models.clocks.ps17 import ps17_specs
from sgw.models.clocks.service import SERVICE_ID, SERVICE_VERSION, ComputedCase, QueueResult, compute_queue
from sgw.models.ranking.event_type import EventTypeRecommendation, recommend

CASE_ASSETS: dict[str, tuple[str, ...]] = {
    "DC-D2-CREWS-AIK": ("STG-AIK-SANDHILL-YARD", "STG-RCH-MILLPOND-YARD"),
    "DC-D3-PS17-FUEL": ("PS-17",),
    "DC-D3-PS17-POWER": ("PS-17",),
    "DC-D3-PS17-PRESSURE": ("PS-17",),
    "DC-D3-HSP-TALLOWBRANCH-WATER": (),
}
SPINE_TOOLS = frozenset({"get_decision_case", "get_forecast"})


class UnknownTool(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"tool {name!r} is not registered for the assess spine")
        self.name = name


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def clock_queue(member_table: Mapping[str, Any], advisory: str) -> tuple[QueueResult, datetime]:
    adv = member_table["advisories"][advisory]
    now = _utc(adv["issued_utc"])
    return compute_queue(ps17_specs(adv, member_table), now=now), now


def ordered_cases(queue: QueueResult) -> list[ComputedCase]:
    return sorted(
        queue.cases.values(),
        key=lambda c: (not c.case.on_critical_path, c.case.effective_decide_by_utc, c.case.decision_case_id),
    )


def case_item(n: int, computed: ComputedCase, as_of: datetime) -> EvidenceItem:
    case, clock = computed.case, computed.case.clock
    values: dict[str, SlotValue] = {
        "decide_by": SlotValue(value=clock.decide_by_utc, format="utc_minute"),
        "decide_by_p10": SlotValue(value=clock.decide_by_p10_utc, format="utc_minute"),
        "decide_by_p90": SlotValue(value=clock.decide_by_p90_utc, format="utc_minute"),
        "consequence": SlotValue(value=clock.consequence_utc, format="utc_minute"),
        "effective_decide_by": SlotValue(value=case.effective_decide_by_utc, format="utc_minute"),
        "lead_time": SlotValue(value=clock.action_lead_time_min, format="minutes"),
    }
    if case.no_regret_share_ppm is not None:
        values["member_share"] = SlotValue(value=case.no_regret_share_ppm, format="percent_ppm")
    if case.next_advisory_utc is not None:
        values["next_advisory"] = SlotValue(value=case.next_advisory_utc, format="utc_minute")
    hints = {
        "verdict": case.no_regret_verdict.value.replace("/", "_"),
        "critical_path": "on" if case.on_critical_path else "off",
        "domain": case.domain.value,
        "missed": "yes" if computed.missed else "no",
    }
    if case.prerequisite_ids:
        hints["has_prerequisites"] = "yes"
    return EvidenceItem(
        id=f"E{n}",
        kind="decision_clock",
        label=f"{case.title} ({case.decision_case_id}, {case.step.value})",
        as_of=as_of,
        model_version=f"{SERVICE_ID} {SERVICE_VERSION}",
        citation=f"{clock.consequence_basis.basis_id} - {clock.lead_time_basis.basis_id}"
        + (f" ({clock.lead_time_basis.citation})" if clock.lead_time_basis.citation else ""),
        classification=Classification.C2,
        label_classification=Classification.C1,
        trust=Trust.SYSTEM,
        values=values,
        hints=hints,
        entity_ids=[case.decision_case_id, *CASE_ASSETS.get(case.decision_case_id, ())],
    )


def event_type_item(n: int, rec: EventTypeRecommendation, as_of: datetime) -> EvidenceItem:
    values = {
        "recommended_type": SlotValue(
            value=f"Type {rec.recommended_type} ({rec.recommended_name})", format="text"
        ),
        "escalation_type": SlotValue(value=f"Type {rec.escalation_type}", format="text"),
        "peak_share_p50": SlotValue(value=round(rec.peak_share_p50 * 1_000_000), format="percent_ppm"),
        "peak_share_p90": SlotValue(value=round(rec.peak_share_p90 * 1_000_000), format="percent_ppm"),
    }
    if rec.analogs:
        values["nearest_analog"] = SlotValue(
            value=f"{rec.analogs[0].storm} {rec.analogs[0].year}", format="text"
        )
    return EvidenceItem(
        id=f"E{n}",
        kind="event_type",
        label="D1 event-type recommendation (the Incident Commander sets the type)",
        as_of=as_of,
        model_version=f"{rec.model_id} {rec.model_version}",
        citation=f"{rec.model_id} thresholds, driver: {rec.driver}",
        classification=Classification.C1,
        trust=Trust.SYSTEM,
        values=values,
        hints={"driver": rec.driver.replace(" ", "_").replace("%", "pct")},
        entity_ids=[],
    )


def note_item(n: int, note: Mapping[str, Any], as_of: datetime) -> EvidenceItem:
    return EvidenceItem(
        id=f"E{n}",
        kind="field_note",
        label="field note",
        as_of=as_of,
        citation=str(note.get("source", "fsm")),
        classification=Classification.C1,
        trust=Trust.EXTERNAL,
        raw_text=str(note.get("text", ""))[:4000],
    )


ToolFn = Callable[[Mapping[str, Any], Mapping[str, Any]], list[dict[str, Any]]]


def _get_decision_case(args: Mapping[str, Any], ctx: Mapping[str, Any]) -> list[dict[str, Any]]:
    queue, now = clock_queue(ctx["member_table"], ctx["advisory"])
    cases = [c for c in ordered_cases(queue) if c.case.decision_case_id == args["decision_case_id"]]
    return [
        {"case_id": c.case.decision_case_id, "as_of": now.isoformat(), "kind": "decision_clock"}
        for c in cases
    ]


def _get_forecast(args: Mapping[str, Any], ctx: Mapping[str, Any]) -> list[dict[str, Any]]:
    inputs = ctx.get("event_type_inputs")
    if not inputs or args.get("target") != "outages":
        return []
    return [{"kind": "event_type", "inputs": dict(inputs)}]


REGISTRY: dict[str, ToolFn] = {"get_decision_case": _get_decision_case, "get_forecast": _get_forecast}


def call_tool(name: str, args: Mapping[str, Any], ctx: Mapping[str, Any]) -> list[dict[str, Any]]:
    if name not in REGISTRY or name not in TOOLS:
        raise UnknownTool(name)
    _, args_model, _ = TOOLS[name]
    args_model.model_validate(dict(args))
    return REGISTRY[name](args, ctx)


def plan_calls(ctx: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    queue, _ = clock_queue(ctx["member_table"], ctx["advisory"])
    calls: list[tuple[str, dict[str, Any]]] = [
        ("get_decision_case", {"decision_case_id": c.case.decision_case_id}) for c in ordered_cases(queue)
    ]
    if ctx.get("event_type_inputs"):
        calls.append(
            ("get_forecast", {"target": "outages", "entity_id": str(ctx.get("region_id", "SC-45003"))})
        )
    return calls


def build_items(
    tool_results: Sequence[Mapping[str, Any]], ctx: Mapping[str, Any], notes: Sequence[Mapping[str, Any]]
) -> list[EvidenceItem]:
    """Fuse tool results into the ordered bundle: binding clocks first (critical path, earliest effective
    decide-by), then the event type, then quarantined notes. Evidence order is part of the replay hash."""
    queue, now = clock_queue(ctx["member_table"], ctx["advisory"])
    wanted = {r["case_id"] for r in tool_results if r.get("kind") == "decision_clock"}
    items: list[EvidenceItem] = []
    for computed in ordered_cases(queue):
        if computed.case.decision_case_id in wanted:
            items.append(case_item(len(items) + 1, computed, now))
    for r in tool_results:
        if r.get("kind") == "event_type":
            rec = recommend(**r["inputs"])
            items.append(event_type_item(len(items) + 1, rec, now))
    for note in notes:
        items.append(note_item(len(items) + 1, note, now))
    return items
