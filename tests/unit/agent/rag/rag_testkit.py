from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sgw.agent.nodes.llm import LlmResponse, node_config
from sgw.agent.rag.answer import NODE
from sgw.agent.rag.llm_config import RAG_NODES_FILE
from sgw.agent.rag.search import Hit
from sgw.agent.rag.tool import GuardedHit, guard_hit
from sgw.contracts.llm_nodes import NodeConfig
from sgw.contracts.tools import InjectedContext
from sgw.contracts.vocab import ApprovalFunction, Classification, RunMode

AS_OF = datetime(2024, 9, 27, 12, tzinfo=UTC)


def config() -> NodeConfig:
    return node_config(NODE, RAG_NODES_FILE)


def ctx(as_of: datetime = AS_OF, ceiling: Classification = Classification.C1) -> InjectedContext:
    return InjectedContext(
        as_of=as_of,
        user_id="ops_dm_02",
        user_role=list(ApprovalFunction)[0],
        region_ids=[],
        run_mode=list(RunMode)[0],
        classification_ceiling=ceiling,
    )


def hit(source: str, blocks: tuple[str, ...], *, trust: str = "verified_internal", **kw: Any) -> GuardedHit:
    doc_id, _, rest = source.partition("@")
    version = rest.split("#")[0]
    fields: dict[str, Any] = {
        "chunk_id": source,
        "doc_id": doc_id,
        "version": version,
        "citation_id": f"{doc_id} Rev {version}" if version != "issued" else doc_id,
        "title": kw.pop("title", "Procedure"),
        "section": "6.0 PROCEDURE",
        "page_from": 2,
        "page_to": 3,
        "blocks": blocks,
        "trust": trust,
        "classification": "C1",
        "effective_from": datetime(2024, 6, 10, tzinfo=UTC),
        "family": "sop",
        "expires_at": None,
        "ordinal": 3,
        "score": 0.03,
        "lane": "hybrid",
    }
    fields.update(kw)
    return guard_hit(Hit(**fields))


def cited(
    text: str, source: str, cited_text: str, index: int = 0, start: int = 0, end: int = 1
) -> dict[str, Any]:
    return {
        "type": "text",
        "text": text,
        "citations": [
            {
                "type": "search_result_location",
                "source": source,
                "title": "t",
                "cited_text": cited_text,
                "search_result_index": index,
                "start_block_index": start,
                "end_block_index": end,
            }
        ],
    }


def reply(*blocks: dict[str, Any]) -> LlmResponse:
    return LlmResponse(content=list(blocks), stop_reason="end_turn", model="claude-sonnet-5-5")
