"""`assess` graph (K5 GRAPHS: workflows W1, W2; decisions D1, D2): the deterministic spine with two
single-call LLM nodes. Code picks every tool call and computes every number; the LLM explains the computed
clocks; approval is an interrupt with no side effects; execution asks the approval store."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from sgw.agent.nodes import spine

GRAPH_ID = "assess"


def build(checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    g: Any = StateGraph(spine.SpineState, context_schema=spine.SpineDeps)
    g.add_node("load_context", spine.load_context)
    g.add_node("input_guard", spine.input_guard)
    g.add_node("call_tool", spine.call_tool)
    g.add_node("fuse", spine.fuse)
    g.add_node("optimise", spine.optimise)
    g.add_node("narrate", spine.narrate_node)
    g.add_node("draft_rationale", spine.rationale_node)
    g.add_node("verify", spine.verify_node)
    g.add_node("policy_gate", spine.policy_gate)
    g.add_node("approval", spine.approval)
    g.add_node("execute", spine.execute)
    g.add_node("audit", spine.audit)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "input_guard")
    g.add_conditional_edges("input_guard", spine.collect_evidence, ["call_tool"])
    g.add_edge("call_tool", "fuse")
    g.add_edge("fuse", "optimise")
    g.add_edge("optimise", "narrate")
    g.add_edge("narrate", "draft_rationale")
    g.add_edge("draft_rationale", "verify")
    g.add_edge("verify", "policy_gate")
    g.add_conditional_edges("policy_gate", spine.after_gate, ["approval", "audit"])
    g.add_edge("approval", "execute")
    g.add_conditional_edges("execute", spine.after_execute, ["approval", "audit"])
    g.add_edge("audit", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())
