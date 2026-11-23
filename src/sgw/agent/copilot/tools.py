"""The copilot's read-only tools (K5, model-visible, `side_effect: none`).

Bound: `get_decision_case`, `get_water_status`, `get_forecast`, `search_procedures`. Each executor
validates its arguments against the K5 args model, takes `as_of`, role and ceiling only from
`InjectedContext`, and returns either evidence (K15 view lines, values withheld, slot names given) or
`search_result` blocks. Nothing here writes: there is no executor for `draft_proposal` or
`optimise_prepositioning`, and a request for any tool outside the bound set is refused, counted and raised
as an alert (SEC-13 unregistered, SEC-14 write or privileged), never executed."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from sgw.agent.copilot.search import SearchFn, SearchUnavailable
from sgw.agent.nodes import evidence_source as es
from sgw.agent.rag.tool import GuardedHit, to_block, tool_result_content
from sgw.agent.render.evidence import EvidenceBundle, EvidenceItem, build_view
from sgw.contracts.tools import MODEL_VISIBLE_TOOLS, TOOLS, InjectedContext
from sgw.contracts.vocab import Classification, Trust

REPO = Path(__file__).resolve().parents[4]
NETWORK_FILE = REPO / "data" / "fixtures" / "helene" / "network.json"
BOUND_TOOLS: tuple[str, ...] = ("get_decision_case", "get_water_status", "get_forecast", "search_procedures")
WRITE_TOOLS = frozenset(
    name for name, (meta, _, _) in TOOLS.items() if meta.side_effect != "none" or not meta.model_visible
)
PRIVILEGED_WORDS = frozenset(
    {
        "sql",
        "shell",
        "exec",
        "execute",
        "write",
        "update",
        "delete",
        "insert",
        "approve",
        "dispatch",
        "http",
        "url",
        "ot",
        "scada",
        "draft",
        "send",
        "close",
        "create",
        "set",
    }
)

DESCRIPTIONS = {
    "get_decision_case": (
        "Computed decision clock for one decision case at the advisory in force at the question's time: "
        "decide-by, effective decide-by (after prerequisites), consequence time, lead time, no-regret share "
        "and verdict. Values are withheld; the result names slots such as {E1.effective_decide_by} that you "
        "write in your answer. Cases: {cases}"
    ),
    "get_water_status": (
        "Water network status for the Aiken detail area: pump stations with their zone, tank, feeder and "
        "onsite generator (or none). zone_ids filters by zone (WZ-...); empty means all zones."
    ),
    "get_forecast": (
        "Model forecast for an entity (outages, etr, pressure or load) when the platform has one for this "
        "question's time. Values are withheld; the result names slots."
    ),
    "search_procedures": (
        "Search SGW plans, procedures and records in force at the question's time. Returns passages you can "
        "cite. Use the user's terms and document ids in the query."
    ),
}


@lru_cache(maxsize=1)
def _named() -> dict[str, Any]:
    named: dict[str, Any] = json.loads(NETWORK_FILE.read_text(encoding="utf-8"))["named"]
    return named


def case_catalog(member_table: Mapping[str, Any]) -> str:
    queue, _ = es.clock_queue(member_table, "N")
    return "; ".join(f"{c.case.decision_case_id} ({c.case.title})" for c in es.ordered_cases(queue))


def _schema(name: str) -> dict[str, Any]:
    schema = TOOLS[name][1].model_json_schema()
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
    return schema


def tool_definitions(member_table: Mapping[str, Any]) -> list[dict[str, Any]]:
    assert set(BOUND_TOOLS) <= set(MODEL_VISIBLE_TOOLS)
    return [
        {
            "name": name,
            "description": DESCRIPTIONS[name].replace("{cases}", case_catalog(member_table)),
            "input_schema": _schema(name),
        }
        for name in BOUND_TOOLS
    ]


def advisory_in_force(member_table: Mapping[str, Any], as_of: datetime) -> tuple[str, datetime]:
    """The advisory whose decision clocks apply at `as_of`, with its issue time: the latest one issued at or
    before `as_of`, or the first one while none is issued yet (its clocks are the ones the tools show)."""
    advisories = sorted(
        ((str(name), es._utc(adv["issued_utc"])) for name, adv in member_table["advisories"].items()),
        key=lambda kv: kv[1],
    )
    current = advisories[0]
    for name, issued in advisories:
        if issued <= as_of:
            current = (name, issued)
    return current


def advisory_at(member_table: Mapping[str, Any], as_of: datetime) -> str:
    return advisory_in_force(member_table, as_of)[0]


def clock_context(ctx: InjectedContext, member_table: Mapping[str, Any]) -> InjectedContext:
    """`ctx` with `as_of` set to the issue time of the advisory in force: the scenario time the copilot's
    prompt and its decision and water tools see, so one advisory gives one prompt however the clock runs."""
    return ctx.model_copy(update={"as_of": advisory_in_force(member_table, ctx.as_of)[1]})


@dataclass
class ToolOutcome:
    content: str | list[dict[str, Any]]
    is_error: bool = False
    new_items: list[EvidenceItem] = field(default_factory=list)
    hits: list[GuardedHit] = field(default_factory=list)


ToolObserver = Callable[[str, dict[str, Any], int], None]


@dataclass
class CopilotTools:
    """`ctx` is the clock context (`clock_context`); `search_ctx` keeps the true scenario time, because the
    documents in force are a fact of that time, not of the advisory. `observer` hears every call as it
    starts and ends (`"start"`/`"end"`, the call record, its index)."""

    ctx: InjectedContext
    member_table: Mapping[str, Any]
    search: SearchFn | None
    search_ctx: InjectedContext | None = None
    observer: ToolObserver | None = None
    items: list[EvidenceItem] = field(default_factory=list)
    hits: list[GuardedHit] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    write_attempts: int = 0
    calls: list[dict[str, Any]] = field(default_factory=list)
    water_readings: bool = False
    """R34 (team prompts v3): water status also carries each zone's pressure at the scenario time."""

    def refuse(self, name: str) -> ToolOutcome:
        low = name.lower()
        write = name in WRITE_TOOLS or bool(set(re.split(r"[^a-z0-9]+", low)) & PRIVILEGED_WORDS)
        self.write_attempts += int(write)
        alert = {
            "code": "SEC-14" if write else "SEC-13",
            "kind": "write_tool_refused" if write else "unregistered_tool",
            "node": "investigate",
            "tool": name[:64],
        }
        self.alerts.append(alert)
        return ToolOutcome("This tool does not exist. The copilot is read-only and has no other tools.", True)

    def _view_text(self, new: list[EvidenceItem]) -> str:
        if not new:
            return "No evidence matched."
        bundle = EvidenceBundle(run_id="copilot", items=self.items)
        return build_view(bundle, include=[i.id for i in new]).text

    def _add(self, item: EvidenceItem) -> EvidenceItem:
        item = item.model_copy(update={"id": f"E{len(self.items) + 1}"})
        self.items.append(item)
        return item

    def _decision_case(self, args: dict[str, Any]) -> ToolOutcome:
        advisory = advisory_at(self.member_table, self.ctx.as_of)
        queue, now = es.clock_queue(self.member_table, advisory)
        cases = [c for c in es.ordered_cases(queue) if c.case.decision_case_id == args["decision_case_id"]]
        if not cases:
            return ToolOutcome(f"Unknown decision case. Known cases: {case_catalog(self.member_table)}", True)
        item = self._add(es.case_item(1, cases[0], now))
        needs = cases[0].case.prerequisite_ids
        label = f"{item.label}, latest advisory" + (f"; needs {', '.join(needs)} first" if needs else "")
        item = item.model_copy(update={"label": label, "entity_ids": [*item.entity_ids, *needs]})
        self.items[-1] = item
        return ToolOutcome(self._view_text([item]), new_items=[item])

    def _water_status(self, args: dict[str, Any]) -> ToolOutcome:
        zones = set(args.get("zone_ids") or [])
        readings = self._zone_readings() if self.water_readings else {}
        new: list[EvidenceItem] = []
        for ps, info in sorted(_named()["pump_stations"].items()):
            if zones and info["zone"] not in zones:
                continue
            gen = info.get("onsite_generator")
            hints, values = {"onsite_generator": "yes" if gen else "no"}, {}
            if ps in readings:
                hints, values = {**hints, **readings[ps][0]}, readings[ps][1]
            new.append(
                self._add(
                    EvidenceItem(
                        id="E1",
                        kind="pump_station",
                        label=f"{ps} pump station: zone {info['zone']}, tank {info['tank']}, feeder "
                        f"{info['feeder']}, onsite generator {gen or 'none'}",
                        as_of=self.ctx.as_of,
                        citation="water twin network"
                        + (" and its zone pressure at this time" if ps in readings else "")
                        + " (synthetic SGW data)",
                        classification=Classification.C1,
                        trust=Trust.SYSTEM,
                        hints=hints,
                        values=values,
                        entity_ids=[ps, info["zone"], info["tank"], info["feeder"], *([gen] if gen else [])],
                    )
                )
            )
        return ToolOutcome(self._view_text(new), new_items=new)

    def _zone_readings(self) -> dict[str, tuple[dict[str, str], dict[str, Any]]]:
        """Pressure, the state floor, backup power and generator state per pump station at the scenario
        time, as the Water page shows them (the water twin's readings, `api.readmodels.water`)."""
        from sgw.agent.render.evidence import SlotValue
        from sgw.api.readmodels.water import zone_readings

        out: dict[str, tuple[dict[str, str], dict[str, Any]]] = {}
        for r in zone_readings((self.search_ctx or self.ctx).as_of):
            z = r.zone
            hints = {
                "below_floor": "yes" if z.pressure_psi_x10 < z.floor_psi_x10 else "no",
                "backup_power": "yes" if z.on_backup_power else "no",
                **({"generator_state": z.generator_state} if z.generator_state else {}),
            }
            values = {
                "pressure": SlotValue(value=round(z.pressure_psi_x10 / 10), format="count", unit="psi"),
                "pressure_floor": SlotValue(value=round(z.floor_psi_x10 / 10), format="count", unit="psi"),
            }
            out[z.pump_station_id] = (hints, values)
        return out

    def _forecast(self, args: dict[str, Any]) -> ToolOutcome:
        return ToolOutcome(
            f"No {args['target']} forecast for {args['entity_id']} is available to the copilot at this time."
        )

    def _search(self, args: dict[str, Any]) -> ToolOutcome:
        if self.search is None:
            return ToolOutcome("Document search is unavailable.", True)
        from sgw.contracts.tools import SearchProceduresArgs

        try:
            hits = self.search(SearchProceduresArgs.model_validate(args), self.search_ctx or self.ctx)
        except SearchUnavailable:
            return ToolOutcome("Document search is unavailable.", True)
        known = {g.hit.chunk_id for g in self.hits}
        self.hits.extend(g for g in hits if g.hit.chunk_id not in known)
        if not hits:
            return ToolOutcome("No in-force passages matched.")
        return ToolOutcome(tool_result_content([to_block(g) for g in hits]), hits=hits)

    def run(self, name: str, raw_args: Any) -> ToolOutcome:
        """Execute one requested call and record it with its real outcome: `ok`, `refused` (not a bound tool)
        or `error` (invalid arguments, unavailable source). Recorded arguments are clipped (`clip_args`)."""
        call: dict[str, Any] = {"tool": name[:64], "args": clip_args(raw_args), "status": "ok"}
        n = len(self.calls)
        self.calls.append(call)
        if self.observer is not None:
            self.observer("start", call, n)
        outcome = self._run(name, raw_args)
        if name not in BOUND_TOOLS:
            call["status"] = "refused"
        elif outcome.is_error:
            call["status"] = "error"
        if self.observer is not None:
            self.observer("end", call, n)
        return outcome

    def _run(self, name: str, raw_args: Any) -> ToolOutcome:
        if name not in BOUND_TOOLS:
            return self.refuse(name)
        try:
            args = TOOLS[name][1].model_validate(raw_args).model_dump(mode="json")
        except ValidationError as exc:
            return ToolOutcome(f"Invalid arguments: {exc.errors()[0]['msg']}", True)
        if name == "get_decision_case":
            return self._decision_case(args)
        if name == "get_water_status":
            return self._water_status(args)
        if name == "get_forecast":
            return self._forecast(args)
        return self._search(args)


MAX_ARGS_CHARS = 512


def clip_args(raw: Any) -> dict[str, Any]:
    """Model-written arguments as recorded in run events and audit: at most `MAX_ARGS_CHARS` of their JSON."""
    if not isinstance(raw, dict):
        return {"_non_object": True}
    text = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str)
    if len(text) <= MAX_ARGS_CHARS:
        return dict(raw)
    return {"_truncated": text[:MAX_ARGS_CHARS], "_chars": len(text)}
