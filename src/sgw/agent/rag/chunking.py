"""Section-aware chunking of rendered documents.

Chunks never cross a top-level section, except that very short neighbouring sections (a one-line Purpose and
Scope) are merged. Long sections split at block boundaries (a step, a paragraph, a whole table) near
`TARGET_WORDS`, with the section heading repeated and the previous short block carried over as overlap.
bge-small reads at most 512 tokens, so chunks stay well below that with their header.
"""

from __future__ import annotations

from dataclasses import dataclass

from sgw.agent.rag.corpus import Document, sha256_text
from sgw.agent.rag.render import Block, RenderedDoc

TARGET_WORDS = 230
MAX_WORDS = 320
SMALL_SECTION_WORDS = 70
OVERLAP_MAX_WORDS = 45


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc: Document
    ordinal: int
    section: str
    page_from: int
    page_to: int
    blocks: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.blocks)

    @property
    def content_sha(self) -> str:
        return sha256_text(self.text)

    @property
    def base_header(self) -> str:
        section = f" | {self.section}" if self.section else ""
        return f"{self.doc.citation_id} | {self.doc.title}{section}"

    @property
    def pages(self) -> str:
        return (
            f"p. {self.page_from}"
            if self.page_from == self.page_to
            else f"pp. {self.page_from}-{self.page_to}"
        )


def _words(block: Block) -> int:
    return len(block.text.split())


def _top(section: str) -> str:
    return section.split(" > ")[0]


def _split_table(block: Block) -> list[Block]:
    if _words(block) <= MAX_WORDS:
        return [block]
    head, rows = block.lines[:3], block.lines[3:-1]
    parts: list[Block] = []
    cur: list[str] = []
    for line in rows:
        cur.append(line)
        if len(" ".join(cur).split()) >= TARGET_WORDS:
            parts.append(Block(block.section, "table", head + cur + [block.lines[-1]], block.page))
            cur = []
    if cur:
        parts.append(Block(block.section, "table", head + cur + [block.lines[-1]], block.page))
    return parts


def _groups(blocks: list[Block], merge_front: bool) -> list[list[Block]]:
    groups: list[list[Block]] = []
    for block in blocks:
        for piece in _split_table(block) if block.kind == "table" else [block]:
            if groups and _top(groups[-1][-1].section) == _top(piece.section):
                groups[-1].append(piece)
            else:
                groups.append([piece])
    merged: list[list[Block]] = []
    for g in groups:
        if (
            merged
            and sum(map(_words, merged[-1])) < SMALL_SECTION_WORDS
            and sum(map(_words, merged[-1])) + sum(map(_words, g)) <= TARGET_WORDS
            and (merge_front or merged[-1][0].section != "Control box")
        ):
            merged[-1].extend(g)
        else:
            merged.append(g)
    return merged


def chunk_document(rendered: RenderedDoc) -> list[Chunk]:
    doc = rendered.doc
    pieces: list[list[Block]] = []
    for group in _groups(rendered.blocks, merge_front=doc.layout == "record"):
        cur: list[Block] = []
        words = 0
        for block in group:
            w = _words(block)
            if cur and words + w > MAX_WORDS or (cur and words >= TARGET_WORDS):
                pieces.append(cur)
                heading = [b for b in cur if b.kind == "heading"][:1]
                carry = (
                    cur[-1] if cur[-1].kind != "heading" and _words(cur[-1]) <= OVERLAP_MAX_WORDS else None
                )
                cur = [*heading, *([carry] if carry else [])]
                words = sum(map(_words, cur))
            cur.append(block)
            words += w
        if cur:
            pieces.append(cur)
    chunks: list[Chunk] = []
    for n, blocks in enumerate(pieces):
        tops = list(dict.fromkeys(_top(b.section) for b in blocks if b.section))
        chunks.append(
            Chunk(
                chunk_id=f"{doc.version_id}#{n:02d}",
                doc=doc,
                ordinal=n,
                section="; ".join(tops),
                page_from=min(b.page for b in blocks),
                page_to=max(b.page for b in blocks),
                blocks=tuple(b.text for b in blocks),
            )
        )
    return chunks
