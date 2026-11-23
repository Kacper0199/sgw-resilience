"""K5 `search_procedures`: the model-visible retrieval tool. Its result is a list of Anthropic `search_result`
blocks and nothing else (a tool result mixing `search_result` with other blocks is refused by the gateway,
`sgw_mixed_search_result`). `as_of`, role and classification ceiling come from `InjectedContext`, never from
the model's arguments.

Each block's `source` is the chunk id (`<doc_id>@<revision>#<nn>`), so a citation names the exact revision and
passage it came from. Content blocks are the chunk's steps, paragraphs and tables after the input guard.
Records that are not controlled documents carry `[field record, unverified]` in the title.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import psycopg

from sgw.agent.rag.embed import Embedder
from sgw.agent.rag.guard import guard_block
from sgw.agent.rag.search import Hit, search
from sgw.contracts.tools import TOOLS, InjectedContext, SearchProceduresArgs, SearchResultBlock
from sgw.contracts.vocab import Classification

UNVERIFIED = "[field record, unverified]"
CLASS_ORDER = ["C0", "C1", "C2", "C3", "C3-N", "C4", "CX"]


@dataclass(frozen=True)
class GuardedHit:
    hit: Hit
    blocks: tuple[str, ...]
    withheld: tuple[str, ...]

    @property
    def tainted(self) -> bool:
        return bool(self.withheld)


def readable_classes(ctx: InjectedContext) -> list[str]:
    meta = TOOLS["search_procedures"][0]
    ceiling = CLASS_ORDER.index(ctx.classification_ceiling.value)
    return [c.value for c in meta.reads_classes if CLASS_ORDER.index(c.value) <= ceiling]


def guard_hit(hit: Hit) -> GuardedHit:
    blocks: list[str] = []
    withheld: list[str] = []
    for b in hit.blocks:
        g = guard_block(b)
        blocks.append(g.text)
        withheld.extend(g.withheld)
    return GuardedHit(hit, tuple(blocks), tuple(withheld))


def title_of(hit: Hit) -> str:
    marker = f"{UNVERIFIED} " if hit.trust != "verified_internal" else ""
    section = f" | {hit.section}" if hit.section else ""
    return f"{marker}{hit.citation_id} | {hit.title}{section} | {hit.pages}"


def to_block(g: GuardedHit) -> SearchResultBlock:
    return SearchResultBlock(
        source=g.hit.chunk_id,
        title=title_of(g.hit),
        content=[{"type": "text", "text": text} for text in g.blocks],
    )


def search_procedures(
    args: SearchProceduresArgs,
    ctx: InjectedContext,
    *,
    conn: psycopg.Connection[Any],
    embedder: Embedder,
) -> tuple[list[SearchResultBlock], list[GuardedHit]]:
    hits = search(
        conn, args.query, as_of=ctx.as_of, embedder=embedder, classes=readable_classes(ctx), top_k=args.top_k
    )
    guarded = [guard_hit(h) for h in hits]
    return [to_block(g) for g in guarded], guarded


def tool_result_content(blocks: Sequence[SearchResultBlock]) -> list[dict[str, Any]]:
    """The `content` of the `tool_result` for a `search_procedures` call: search_result blocks only."""
    return [b.model_dump(mode="json") for b in blocks]


def prompt_classes(hits: Sequence[GuardedHit]) -> list[Classification]:
    """Classes of the text that enters a prompt: the classes of the passages shown."""
    present = {g.hit.classification for g in hits} or {"C0"}
    return [Classification(c) for c in CLASS_ORDER if c in present]
