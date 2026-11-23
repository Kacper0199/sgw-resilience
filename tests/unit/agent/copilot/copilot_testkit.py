from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sgw.agent.nodes.llm import LlmRequest, LlmResponse
from sgw.agent.rag.tool import GuardedHit
from sgw.contracts.tools import InjectedContext, SearchProceduresArgs
from sgw.contracts.vocab import ApprovalFunction, Classification, RunMode

from ..rag.rag_testkit import hit

AS_OF = datetime(2024, 9, 26, 10, tzinfo=UTC)


def ctx(as_of: datetime = AS_OF) -> InjectedContext:
    return InjectedContext(
        as_of=as_of,
        user_id="ops_dm_01",
        user_role=ApprovalFunction.OPERATIONS,
        region_ids=["SC-45003"],
        run_mode=RunMode.REPLAY,
        classification_ceiling=Classification.C1,
    )


ETR_SOURCE = "DOM 14.206@K#07"
ETR_TEXT = "Revise the global ETR when the P50 moves by more than 12 h from the published value."


def etr_hits() -> list[GuardedHit]:
    return [hit(ETR_SOURCE, (ETR_TEXT,))]


class FakeSearch:
    def __init__(self, hits: list[GuardedHit] | None = None) -> None:
        self.hits = etr_hits() if hits is None else hits
        self.calls: list[str] = []

    def __call__(self, args: SearchProceduresArgs, c: InjectedContext) -> list[GuardedHit]:
        self.calls.append(args.query)
        return self.hits


def use(name: str, args: dict[str, Any], n: int = 0) -> LlmResponse:
    return LlmResponse(
        content=[{"type": "tool_use", "id": f"toolu_{n}", "name": name, "input": args}],
        stop_reason="tool_use",
        model="claude-sonnet-5-5",
    )


def final(*blocks: dict[str, Any]) -> LlmResponse:
    return LlmResponse(content=list(blocks), stop_reason="end_turn", model="claude-sonnet-5-5")


def text(t: str, citations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "text", "text": t}
    if citations:
        out["citations"] = citations
    return out


def cite(source: str, cited_text: str) -> dict[str, Any]:
    return {
        "type": "search_result_location",
        "source": source,
        "title": "t",
        "cited_text": cited_text,
        "search_result_index": 0,
        "start_block_index": 0,
        "end_block_index": 1,
    }


class Script:
    """Per-node queues of replies; records every request."""

    def __init__(self, **queues: list[LlmResponse | Exception | Callable[[LlmRequest], LlmResponse]]) -> None:
        self.queues = {k: list(v) for k, v in queues.items()}
        self.requests: list[LlmRequest] = []

    async def create(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        q = self.queues.get(request.node) or []
        if not q:
            from sgw.agent.nodes.llm import LlmUnavailable

            raise LlmUnavailable("gateway_unreachable", "script empty")
        reply = q.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            return reply(request)
        return reply


def route(intent: str, refs: list[str] | None = None) -> LlmResponse:
    import json

    return final(text(json.dumps({"intent": intent, "entity_refs": refs or []})))


NOT_IN_DOCS_REPLY = final(text("This is not in the documents."))
