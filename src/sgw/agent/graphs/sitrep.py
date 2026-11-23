"""`sitrep` graph (K5 GRAPHS: workflow W7): the situation report draft.

Code reads the status (customers out, peak, share restored, counties, trend) from the replay, the published
global ETR and the open decision clocks; the `sitrep` LLM node writes the paragraph with every number in a
slot; with the LLM unavailable or disabled (`FAULT_LLM_DOWN=1` -> M2) the template writes the same slots. The
draft is T1 (tier from the approval policy): a person promotes it; the graph never does."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from sgw.agent.nodes import spine
from sgw.reports import nodes

GRAPH_ID = "sitrep"


def build(checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    g: Any = StateGraph(nodes.ReportState, context_schema=spine.SpineDeps)
    g.add_node("load_context", nodes.sitrep_start)
    g.add_node("input_guard", spine.input_guard)
    g.add_node("sitrep_evidence", nodes.sitrep_evidence)
    g.add_node("sitrep", nodes.sitrep_text)
    g.add_node("verify", spine.verify_node)
    g.add_node("sitrep_draft", nodes.sitrep_draft)
    g.add_node("audit", spine.audit)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "input_guard")
    g.add_edge("input_guard", "sitrep_evidence")
    g.add_edge("sitrep_evidence", "sitrep")
    g.add_edge("sitrep", "verify")
    g.add_edge("verify", "sitrep_draft")
    g.add_edge("sitrep_draft", "audit")
    g.add_edge("audit", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())
