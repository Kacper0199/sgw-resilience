"""One copilot turn: N1 `route_intent` then N4 `investigate`, or the fixed read-only reply.

The user turn is untrusted: the router's guard withholds instruction sentences, and the investigator only
ever sees the guarded text. `out_of_scope` (other topics, requests to change, run, send or approve
anything) gets the fixed read-only reply with no investigator call. A turn with withheld text taints the
run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sgw.agent.copilot.investigate import NODE as INVESTIGATE
from sgw.agent.copilot.investigate import READ_ONLY, CopilotAnswer, investigate
from sgw.agent.copilot.search import SearchFn
from sgw.agent.extract.guard import WITHHELD, guard_untrusted
from sgw.agent.nodes.llm import NODES_FILE, LlmClient, node_config
from sgw.agent.route.intent import NODE as ROUTE
from sgw.agent.route.intent import Intent, RouteResult, route_intent
from sgw.contracts.tools import InjectedContext


@dataclass
class CopilotTurn:
    route: RouteResult
    answer: CopilotAnswer

    @property
    def tainted(self) -> bool:
        return self.route.tainted or self.answer.tainted

    def as_state(self) -> dict[str, Any]:
        return {
            "route": self.route.model_dump(mode="json", exclude={"usage"}),
            "answer": self.answer.as_state(),
        }


async def copilot_turn(
    question: str,
    ctx: InjectedContext,
    *,
    llm: LlmClient,
    member_table: Mapping[str, Any],
    search: SearchFn | None,
    nodes_file: Path = NODES_FILE,
    run_id: str | None = None,
    models: Mapping[str, str] | None = None,
) -> CopilotTurn:
    models = models or {}
    route = await route_intent(
        question,
        llm=llm,
        config=node_config(ROUTE, nodes_file),
        run_id=run_id,
        model_override=models.get(ROUTE),
    )
    if route.intent is Intent.OUT_OF_SCOPE:
        return CopilotTurn(
            route, CopilotAnswer(question, "not_in_documents", READ_ONLY, READ_ONLY, reason="out_of_scope")
        )
    shown = guard_untrusted(" ".join(question.split())[:2000]).shown.replace(WITHHELD, "").strip()
    answer = await investigate(
        shown,
        ctx,
        llm=llm,
        config=node_config(INVESTIGATE, nodes_file),
        member_table=member_table,
        search=search,
        run_id=run_id,
        model_override=models.get(INVESTIGATE),
        entities=route.entity_ids,
        intent=route.intent.value,
    )
    return CopilotTurn(route, answer)
