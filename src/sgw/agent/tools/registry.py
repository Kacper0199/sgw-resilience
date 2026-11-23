"""`run(name, args, ctx) -> ToolOutcome`: the one entry point an agent worker calls.

Order of checks: a name that is not a registered model-visible read tool is refused with a SEC-13 alert
(SEC-14 when it names a write or privileged action) and never executed; a tool this role's pages do not show
is refused without an error (`personas.may_call`); arguments are validated against the K5 args model; the
executor reads the REST read model at the injected time; its items are numbered in the worker's ledger and
the K15 view of them is the content the model sees. A read model with nothing for this time answers
`empty`; an unavailable source answers `error` with a plain reason, never a stack trace."""

from __future__ import annotations

import logging
import re
from typing import Any

import psycopg
from pydantic import ValidationError

from sgw.agent.tools.context import ToolContext
from sgw.agent.tools.executors import EXECUTORS
from sgw.agent.tools.outcome import ToolOutcome
from sgw.agent.tools.personas import may_call, tools_for
from sgw.agent.tools.reads import NotAvailable
from sgw.contracts.tools import TOOLS

log = logging.getLogger("sgw.agent.tools")
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
UNREGISTERED = "This tool does not exist. The copilot is read-only and has no other tools."

__all__ = ["EXECUTORS", "run", "tools_for"]


def refusal_alert(name: str, node: str) -> dict[str, Any]:
    write = name in WRITE_TOOLS or bool(set(re.split(r"[^a-z0-9]+", name.lower())) & PRIVILEGED_WORDS)
    return {
        "code": "SEC-14" if write else "SEC-13",
        "kind": "write_tool_refused" if write else "unregistered_tool",
        "node": node,
        "tool": name[:64],
    }


async def run(name: str, raw_args: Any, ctx: ToolContext, *, node: str = "worker") -> ToolOutcome:
    if name not in EXECUTORS:
        return ToolOutcome(UNREGISTERED, "refused", True, alerts=[refusal_alert(name, node)])
    if not may_call(ctx.role, name):
        role = ctx.role.value.replace("_", " ")
        return ToolOutcome(
            f"This information is not shown to the {role} role, so the copilot cannot read it.", "refused"
        )
    try:
        args = (
            TOOLS[name][1]
            .model_validate(raw_args if isinstance(raw_args, dict) else {})
            .model_dump(mode="json")
        )
    except ValidationError as exc:
        return ToolOutcome(f"Invalid arguments: {exc.errors()[0]['msg']}", "error", True)
    try:
        items = await EXECUTORS[name](args, ctx)
    except NotAvailable as exc:
        return ToolOutcome(f"Nothing to show: {_plain(str(exc))}", "empty")
    except (psycopg.Error, OSError) as exc:
        log.warning("tool %s read failed: %s", name, type(exc).__name__)
        return ToolOutcome("This source is unavailable right now.", "error", True)
    if not items:
        return ToolOutcome("No evidence matched.", "empty")
    numbered = [ctx.ledger.add(i) for i in items]
    return ToolOutcome(ctx.ledger.view_text(numbered), "ok", new_items=numbered)


def _plain(reason: str) -> str:
    return re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z?", "this time", reason)[:200]
