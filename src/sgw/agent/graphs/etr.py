"""`etr` graph (K5 GRAPHS: workflow W5, decision D4): the global ETR proposal.

WP-17's estimates (global + operating areas) become evidence; the `etr_brief` LLM node explains them and code
appends the honest caveat (K17 coverage on synthetic storms, not checked on a real storm, never drawn on the
replayed outage curve); `publish_global_etr` is T3 (`command` + `operations`); after the approval store says
approved, `execute` publishes one K2 `EtrPublished` per estimate."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from sgw.agent.nodes import spine
from sgw.reports import nodes

GRAPH_ID = "etr"


def build(checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    g: Any = StateGraph(nodes.ReportState, context_schema=spine.SpineDeps)
    g.add_node("load_context", nodes.etr_start)
    g.add_node("input_guard", spine.input_guard)
    g.add_node("etr_evidence", nodes.etr_evidence)
    g.add_node("etr_brief", nodes.etr_brief)
    g.add_node("verify", spine.verify_node)
    g.add_node("policy_gate", spine.policy_gate)
    g.add_node("approval", spine.approval)
    g.add_node("execute", nodes.etr_execute)
    g.add_node("audit", spine.audit)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "input_guard")
    g.add_edge("input_guard", "etr_evidence")
    g.add_edge("etr_evidence", "etr_brief")
    g.add_edge("etr_brief", "verify")
    g.add_edge("verify", "policy_gate")
    g.add_conditional_edges("policy_gate", spine.after_gate, ["approval", "audit"])
    g.add_edge("approval", "execute")
    g.add_conditional_edges("execute", spine.after_execute, ["approval", "audit"])
    g.add_edge("audit", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())
