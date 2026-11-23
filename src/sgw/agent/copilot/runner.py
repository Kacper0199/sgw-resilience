"""The tool interface the copilot's workers call: `await run(name, args, tools)`, plus what a role may call.

`PlatformToolRunner` runs the R27 executors (`sgw.agent.tools.run`: the REST read models at the injected
time, persona and domain refusals, SEC-13/14 alerts) and keeps the copilot's own executors for the decision
clocks, the water network and procedure search (`CopilotTools`). Every call lands in the worker's
`CopilotTools`: recorded with its real status (ok, empty, refused, error), its start time and duration, the
live frames, and its evidence numbered after the worker's earlier items, so slot ids stay unique per worker.
`LocalToolRunner` answers the R27 tools with a fixed stub (tests and hosts without a database).
The R27 read models see the true scenario time (outages, crews, feeds change within an advisory); the
decision clocks keep the advisory's issue time. `allowed(role)` is the persona filter
(`sgw.agent.tools.personas`): a worker is offered only tools its role's pages show; any other call is refused
like an unknown tool."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from sgw.agent.copilot.tools import BOUND_TOOLS, CopilotTools, ToolOutcome, clip_args
from sgw.contracts.tools import MODEL_VISIBLE_TOOLS, TOOLS
from sgw.contracts.vocab import ApprovalFunction

READ_TOOLS: frozenset[str] = frozenset(
    n for n in MODEL_VISIBLE_TOOLS if TOOLS[n][0].side_effect == "none" and TOOLS[n][0].model_visible
)
OWN_TOOLS = frozenset({"get_decision_case", "get_water_status", "search_procedures"})
CASE_TOOL = "get_decision_case"
LOCAL_READS = frozenset({"get_decision_case", "get_water_status"})
SETTLED_HINTS = ("deadline", "decision", "missed")
STUB_TEXT = "No {name} data is available to the copilot in this build."

DESCRIPTIONS: Mapping[str, str] = {
    "get_risk": "Outage risk from the outage model at the question's time, by county or by named asset "
    "(level county or asset). Values are withheld; the result names slots.",
    "get_outages": "Open power outages on feeders at the question's time, optionally only those with "
    "critical customers.",
    "get_crews": "Crews with their status and location, and the crew pre-positioning plan options from the "
    "optimiser.",
    "list_anomalies": "Sensor anomalies and spoofing flags from the water anomaly detectors, newest first.",
    "get_feed_health": "Freshness and health of the data feeds the platform reads (SCADA, OMS, AMI and "
    "weather).",
    "run_what_if": "A precomputed what-if scenario (pump station outage, feeder restore order, crew shift, "
    "advisory shift); read-only lookup.",
    "list_decisions": "The decision queue: open proposals with their decision case, deadline and signatures.",
    "get_readiness": "Pre-season readiness checks with their status (ready, gap, unknown) and owner.",
    "get_etr": "Estimated time of restoration from the restoration model, globally or for an area.",
    "list_outage_surges": "Outage surges detected per county from public outage data, with onset time and "
    "data-quality flags.",
    "get_damage_photos": "Field damage photos ranked by the damage triage model, and the damage cases they "
    "form; a reviewer confirms every photo.",
}


class ToolRunner(Protocol):
    def allowed(self, role: str) -> frozenset[str]: ...

    def definitions(self, names: list[str], member_table: Mapping[str, Any]) -> list[dict[str, Any]]: ...

    async def run(self, name: str, args: Any, tools: CopilotTools) -> ToolOutcome: ...


def _schema(name: str) -> dict[str, Any]:
    schema = TOOLS[name][1].model_json_schema()
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
    return schema


def definitions(names: list[str], member_table: Mapping[str, Any]) -> list[dict[str, Any]]:
    from sgw.agent.copilot.tools import tool_definitions

    bound = {d["name"]: d for d in tool_definitions(member_table)}
    out: list[dict[str, Any]] = []
    for name in names:
        if name in OWN_TOOLS:
            out.append(bound[name])
        elif name in READ_TOOLS:
            desc = DESCRIPTIONS.get(name) or bound.get(name, {}).get("description") or name
            out.append({"name": name, "description": desc, "input_schema": _schema(name)})
    return out


async def record(
    tools: CopilotTools, name: str, args: Any, outcome: Callable[[dict[str, Any]], Awaitable[ToolOutcome]]
) -> ToolOutcome:
    """One call in the worker's record: start time, duration, live start/end frames, final status."""
    call: dict[str, Any] = {
        "tool": name[:64],
        "args": clip_args(args),
        "status": "ok",
        "at": datetime.now(UTC).isoformat(),
    }
    n = len(tools.calls)
    tools.calls.append(call)
    if tools.observer is not None:
        tools.observer("start", call, n)
    started = time.monotonic()
    result = await outcome(call)
    call["ms"] = int((time.monotonic() - started) * 1000)
    if tools.observer is not None:
        tools.observer("end", call, n)
    return result


async def _own(name: str, args: Any, tools: CopilotTools, call: dict[str, Any]) -> ToolOutcome:
    outcome = tools._run(name, args)
    if outcome.is_error:
        call["status"] = "error"
    return outcome


def allowed_for(role: str) -> frozenset[str]:
    """The persona map of `sgw.agent.tools.personas` (page visibility by role and domain)."""
    from sgw.agent.tools.personas import tools_for

    try:
        function = ApprovalFunction(role)
    except ValueError:
        return frozenset()
    return frozenset(tools_for(function))


class LocalToolRunner:
    """The copilot's own executors; every R27 tool answers a fixed stub."""

    def allowed(self, role: str) -> frozenset[str]:
        return allowed_for(role)

    def definitions(self, names: list[str], member_table: Mapping[str, Any]) -> list[dict[str, Any]]:
        return definitions(names, member_table)

    async def run(self, name: str, args: Any, tools: CopilotTools) -> ToolOutcome:
        if name not in READ_TOOLS:
            return await refuse(tools, name, args)
        if name in BOUND_TOOLS:
            return await record(tools, name, args, lambda call: _own(name, args, tools, call))
        text = STUB_TEXT.format(name=name.replace("_", " ").removeprefix("get "))

        async def stub(call: dict[str, Any]) -> ToolOutcome:
            call["status"] = "empty"
            return ToolOutcome(text)

        return await record(tools, name, args, stub)


PACK_NOT_MODELLED = {
    "get_decision_case": "The decision clock model",
    "get_water_status": "The water network",
    "get_forecast": "The outage and restoration forecast",
}


class PlatformToolRunner:
    """R27 executors over the platform read models (`DbReads`), the copilot's own for the rest."""

    def __init__(self, reads: Any) -> None:
        self.reads = reads

    def allowed(self, role: str) -> frozenset[str]:
        return allowed_for(role)

    def definitions(self, names: list[str], member_table: Mapping[str, Any]) -> list[dict[str, Any]]:
        return definitions(names, member_table)

    async def run(self, name: str, args: Any, tools: CopilotTools) -> ToolOutcome:
        from sgw.agent.tools.context import ToolContext
        from sgw.agent.tools.outcome import EvidenceLedger
        from sgw.agent.tools.registry import run as run_tool

        pack = getattr(self.reads, "pack", None)
        if pack is not None and name in PACK_NOT_MODELLED:
            return ToolOutcome(
                f"{PACK_NOT_MODELLED[name]} is not modelled for this scenario ({pack.label}); the scenario's"
                " decisions are on the decision queue (list_decisions)."
            )

        if name == CASE_TOOL:

            async def case(call: dict[str, Any]) -> ToolOutcome:
                own = await _own(name, args, tools, call)
                if own.is_error:
                    found = await self._rule_case(own, args, tools)
                    if found is not own:
                        call["status"] = "ok"
                    return found
                return await self._settle(own, args, tools)

            return await record(tools, name, args, case)
        if name in OWN_TOOLS:
            return await record(tools, name, args, lambda call: _own(name, args, tools, call))
        if name not in READ_TOOLS:
            return await refuse(tools, name, args)

        async def execute(call: dict[str, Any]) -> ToolOutcome:
            ctx = ToolContext(
                injected=tools.search_ctx or tools.ctx,
                reads=self.reads,
                ledger=EvidenceLedger(start=len(tools.items) + 1),
            )
            out = await run_tool(name, args, ctx, node="worker")
            call["status"] = out.status
            tools.items.extend(out.new_items)
            tools.alerts.extend(out.alerts)
            tools.write_attempts += sum(a.get("code") == "SEC-14" for a in out.alerts)
            return ToolOutcome(out.content, out.is_error, new_items=list(out.new_items))

        return await record(tools, name, args, execute)

    async def _rule_case(self, outcome: ToolOutcome, args: Any, tools: CopilotTools) -> ToolOutcome:
        """A case the advisory clocks do not hold (rule-made: hospital tanker, boil-water notices and lifts,
        ETR publication and revision) answers from the decision board at the scenario time, with its state."""
        from sgw.agent.tools.context import ToolContext
        from sgw.agent.tools.outcome import EvidenceLedger
        from sgw.agent.tools.registry import run as run_tool

        case_id = str((args if isinstance(args, dict) else {}).get("decision_case_id", ""))
        ctx = ToolContext(
            injected=tools.search_ctx or tools.ctx,
            reads=self.reads,
            ledger=EvidenceLedger(start=len(tools.items) + 1),
        )
        board = await run_tool("list_decisions", {"limit": 50}, ctx, node="worker")
        mine = [i for i in board.new_items if case_id in i.entity_ids][:1]
        if not mine:
            return outcome
        item = mine[0].model_copy(update={"id": f"E{len(tools.items) + 1}"})
        tools.items.append(item)
        return ToolOutcome(tools._view_text([item]), new_items=[item])

    async def _settle(self, outcome: ToolOutcome, args: Any, tools: CopilotTools) -> ToolOutcome:
        from sgw.agent.copilot.clock_state import (
            advisories_over,
            authority_times,
            clock_due,
            clock_state,
            settled,
        )

        at = (tools.search_ctx or tools.ctx).as_of
        if outcome.is_error or not advisories_over(getattr(self.reads, "scenario", "helene"), at):
            return outcome
        case_id = str((args if isinstance(args, dict) else {}).get("decision_case_id", ""))
        proposals = [p for p in await self.reads.decisions(at, None) if p.decision_case_id == case_id]
        dsn = getattr(self.reads, "dsn", None)
        ids = [p.proposal_id for p in proposals]
        decided = await asyncio.to_thread(authority_times, dsn, ids, at) if dsn else {}
        return settled(tools, outcome, clock_state(case_id, clock_due(outcome), proposals, at, decided))


def default_runner(scenario: str = "helene") -> ToolRunner:
    """The platform runner on the API's database; the local one where no database is configured."""
    dsn = os.environ.get("SGW_DATABASE_URL")
    if not dsn:
        return LocalToolRunner()
    from sgw.agent.tools.reads import DbReads, PackReads
    from sgw.scenarios import packs

    return PlatformToolRunner(PackReads(dsn, scenario) if packs.is_pack(scenario) else DbReads(dsn, scenario))


async def refuse(tools: CopilotTools, name: str, args: Any) -> ToolOutcome:
    """A call outside the worker's allowed tools: refused, counted and alerted like an unknown tool."""

    async def refused(call: dict[str, Any]) -> ToolOutcome:
        call["status"] = "refused"
        return tools.refuse(name)

    return await record(tools, name, args, refused)


async def over_limit(tools: CopilotTools, name: str, args: Any) -> ToolOutcome:
    """A call past the worker's limit reads nothing: `empty` (not a source, not a failure), marked `limit`."""

    async def limited(call: dict[str, Any]) -> ToolOutcome:
        call["status"] = "empty"
        call["limit"] = True
        return ToolOutcome("The tool call limit for this task is reached.", True)

    return await record(tools, name, args, limited)


def _key(name: str, args: Any, tools: CopilotTools) -> str:
    import json

    at = (tools.search_ctx or tools.ctx).as_of.isoformat()
    body = json.dumps(args if isinstance(args, dict) else {}, sort_keys=True, default=str)
    return f"{name}|{body}|{at}|{tools.ctx.user_role.value}|{len(tools.items) + 1}"


class RecordingToolRunner:
    """Wraps a runner and keeps what every R27 call returned (status, content, evidence), keyed by tool,
    arguments, time, role and the worker's next evidence number, so a run replays without the database."""

    def __init__(self, inner: ToolRunner) -> None:
        self.inner = inner
        self.seen: dict[str, dict[str, Any]] = {}

    def allowed(self, role: str) -> frozenset[str]:
        return self.inner.allowed(role)

    def definitions(self, names: list[str], member_table: Mapping[str, Any]) -> list[dict[str, Any]]:
        return self.inner.definitions(names, member_table)

    @property
    def on_pack(self) -> bool:
        """A scenario pack answers the decision-case tool "not modelled" (no evidence): that answer is kept,
        or the replay would compute the Helene clock from the member table instead."""
        return getattr(getattr(self.inner, "reads", None), "pack", None) is not None

    async def run(self, name: str, args: Any, tools: CopilotTools) -> ToolOutcome:
        key = _key(name, args, tools)
        out = await self.inner.run(name, args, tools)
        if name == CASE_TOOL and out.new_items and out.new_items[0].kind == "decision":
            self.seen[key] = {
                "status": tools.calls[-1]["status"],
                "content": out.content,
                "is_error": out.is_error,
                "items": [i.model_dump(mode="json") for i in out.new_items],
            }
        elif name == CASE_TOOL and out.new_items and "decision" in out.new_items[0].hints:
            self.seen[key] = {"hints": {k: out.new_items[0].hints[k] for k in SETTLED_HINTS}}
        elif name in PACK_NOT_MODELLED and self.on_pack and not out.new_items:
            self.seen[key] = {"pack": True, "content": out.content, "is_error": out.is_error}
        elif name not in OWN_TOOLS:
            self.seen[key] = {
                "status": tools.calls[-1]["status"],
                "content": out.content,
                "is_error": out.is_error,
                "items": [i.model_dump(mode="json") for i in out.new_items],
            }
        return out

    def save(self, path: Any) -> None:
        import json
        from pathlib import Path

        target = Path(path)
        data = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else {}
        data.update(self.seen)
        target.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


class RecordedToolRunner:
    """Replays `RecordingToolRunner` output for the R27 tools; the copilot's own tools run as usual. A call
    with no recording answers `error` ("source unavailable"), like a missing read model."""

    def __init__(self, path: Any) -> None:
        import json
        from pathlib import Path

        target = Path(path)
        self.data: dict[str, dict[str, Any]] = (
            json.loads(target.read_text(encoding="utf-8")) if target.is_file() else {}
        )

    def allowed(self, role: str) -> frozenset[str]:
        return allowed_for(role)

    def definitions(self, names: list[str], member_table: Mapping[str, Any]) -> list[dict[str, Any]]:
        return definitions(names, member_table)

    async def run(self, name: str, args: Any, tools: CopilotTools) -> ToolOutcome:
        from sgw.agent.render.evidence import EvidenceItem

        row = self.data.get(_key(name, args, tools))
        if name in PACK_NOT_MODELLED and row is not None and row.get("pack"):
            return ToolOutcome(row["content"], bool(row["is_error"]))
        if name == CASE_TOOL and row is not None and "items" in row:
            from sgw.agent.render.evidence import EvidenceItem

            async def board_case(call: dict[str, Any]) -> ToolOutcome:
                call["status"] = row["status"]
                items = [EvidenceItem.model_validate(i) for i in row["items"]]
                tools.items.extend(items)
                return ToolOutcome(row["content"], bool(row["is_error"]), new_items=items)

            return await record(tools, name, args, board_case)
        if name == CASE_TOOL:
            from sgw.agent.copilot.clock_state import settled

            async def case(call: dict[str, Any]) -> ToolOutcome:
                return settled(tools, await _own(name, args, tools, call), (row or {}).get("hints") or {})

            return await record(tools, name, args, case)
        if name in OWN_TOOLS:
            return await record(tools, name, args, lambda call: _own(name, args, tools, call))
        if name not in READ_TOOLS:
            return await refuse(tools, name, args)

        async def replay(call: dict[str, Any]) -> ToolOutcome:
            if row is None:
                call["status"] = "error"
                return ToolOutcome("This source is unavailable right now.", True)
            call["status"] = row["status"]
            items = [EvidenceItem.model_validate(i) for i in row["items"]]
            tools.items.extend(items)
            return ToolOutcome(row["content"], bool(row["is_error"]), new_items=items)

        return await record(tools, name, args, replay)


def call_key(name: str, args: Any) -> str:
    import json

    return f"{name}|{json.dumps(args if isinstance(args, dict) else {}, sort_keys=True, default=str)}"


async def again(tools: CopilotTools, name: str, args: Any, earlier: ToolOutcome) -> ToolOutcome:
    """A repeated call: recorded, answered with the earlier result."""

    async def same(call: dict[str, Any]) -> ToolOutcome:
        call["status"] = "ok"
        return ToolOutcome(earlier.content, earlier.is_error)

    return await record(tools, name, args, same)
