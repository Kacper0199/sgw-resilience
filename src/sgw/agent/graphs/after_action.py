"""`after_action` graph (K5 GRAPHS: workflow W13, decision D5): after-action lite.

Code verifies the audit chain, then reads back clocks met or missed, break-glass uses with their co-sign
status and the ledger timeline (only from the verified part of the chain), and builds the SC 103-314
interruption records; the `after_action_summary` LLM node summarises them with every number in a slot; code
renders the after-action review and the SC 103-314-style report draft. Drafts only: nothing is filed or
approved here."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from sgw.agent.nodes import spine
from sgw.reports import nodes

GRAPH_ID = "after_action"


def build(checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    g: Any = StateGraph(nodes.ReportState, context_schema=spine.SpineDeps)
    g.add_node("load_context", nodes.after_action_start)
    g.add_node("input_guard", spine.input_guard)
    g.add_node("after_action_evidence", nodes.after_action_evidence)
    g.add_node("after_action_summary", nodes.after_action_summary)
    g.add_node("verify", spine.verify_node)
    g.add_node("render_reports", nodes.render_reports)
    g.add_node("audit", spine.audit)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "input_guard")
    g.add_edge("input_guard", "after_action_evidence")
    g.add_edge("after_action_evidence", "after_action_summary")
    g.add_edge("after_action_summary", "verify")
    g.add_edge("verify", "render_reports")
    g.add_edge("render_reports", "audit")
    g.add_edge("audit", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())
