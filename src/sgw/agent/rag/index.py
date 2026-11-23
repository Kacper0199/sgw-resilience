"""Build the retrieval index in Postgres: K1 `document`, `doc_version`, `chunk` (pgvector 384-d + generated
FTS column) plus the WP-18 metadata tables (migration 3600). A build replaces the whole corpus in one
transaction, so readers never see a half-built index."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import psycopg

from sgw.agent.rag.chunking import Chunk, chunk_document
from sgw.agent.rag.corpus import Document, sha256_text
from sgw.agent.rag.embed import CachedPassages, Embedder, to_pgvector
from sgw.agent.rag.headers import HeaderRecord
from sgw.agent.rag.render import render

ALIAS_MIN_LEN = 4


def norm_alias(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def aliases(doc: Document) -> list[tuple[str, str]]:
    out = [(norm_alias(doc.doc_id), "doc_id"), (norm_alias(doc.citation_id), "citation_id")]
    if doc.legacy_id:
        out.append((norm_alias(doc.legacy_id), "legacy_id"))
    return [(a, k) for a, k in out if len(a) >= ALIAS_MIN_LEN and re.search(r"\d", a)]


def embed_text(chunk: Chunk, header: str) -> str:
    return "\n".join(p for p in (chunk.base_header, header, chunk.text) if p)


@dataclass(frozen=True)
class IndexedChunk:
    chunk: Chunk
    header: HeaderRecord | None

    @property
    def context_header(self) -> str:
        extra = self.header.header if self.header and self.header.header else ""
        return f"{self.chunk.base_header}\n{extra}".strip()

    @property
    def embed_input(self) -> str:
        return embed_text(self.chunk, self.header.header if self.header else "")


def prepare(
    docs: Sequence[Document], headers: dict[str, HeaderRecord]
) -> list[tuple[Document, Any, list[IndexedChunk]]]:
    out = []
    for doc in docs:
        rendered = render(doc)
        chunks = chunk_document(rendered)
        out.append((doc, rendered, [IndexedChunk(c, headers.get(c.content_sha)) for c in chunks]))
    return out


def _document_rows(docs: Iterable[Document]) -> dict[str, Document]:
    latest: dict[str, Document] = {}
    for d in docs:
        if d.doc_id not in latest or d.effective > latest[d.doc_id].effective:
            latest[d.doc_id] = d
    return latest


def build_index(
    conn: psycopg.Connection[Any],
    docs: Sequence[Document],
    headers: dict[str, HeaderRecord],
    *,
    embedder: Embedder | None,
    cache: CachedPassages | None = None,
) -> dict[str, int]:
    prepared = prepare(docs, headers)
    cache = cache or CachedPassages()
    all_chunks = [ic for _, _, ics in prepared for ic in ics]
    vectors = cache.embed([ic.embed_input for ic in all_chunks], embedder)
    vec_by_id = {ic.chunk.chunk_id: vectors[i] for i, ic in enumerate(all_chunks)}
    with conn.transaction():
        for table in ("rag_alias", "rag_chunk_meta", "chunk", "rag_version_meta", "doc_version", "document"):
            conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names
        for doc in _document_rows(docs).values():
            conn.execute(
                "INSERT INTO document (doc_id, title, source, licence, classification, trust) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    doc.doc_id,
                    doc.title,
                    doc.source_url or doc.source_path,
                    doc.licence,
                    doc.class_code,
                    doc.trust,
                ),
            )
        for doc, rendered, ics in prepared:
            for alias, kind in aliases(doc):
                conn.execute(
                    "INSERT INTO rag_alias (alias_norm, doc_id, kind) VALUES (%s, %s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (alias, doc.doc_id, kind),
                )
            conn.execute(
                "INSERT INTO doc_version (doc_version_id, doc_id, version, available_at, effective_from, "
                "status, "
                "content_hash) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    doc.version_id,
                    doc.doc_id,
                    doc.version,
                    doc.effective_at,
                    doc.effective_at,
                    "superseded" if doc.status == "superseded" else "current",
                    sha256_text(rendered.text),
                ),
            )
            conn.execute(
                "INSERT INTO rag_version_meta (doc_version_id, revision, change_no, citation_id, legacy_id, "
                "family, "
                "owner_function, expires_at, origin, page_count, rendered_sha256) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    doc.version_id,
                    doc.revision,
                    doc.change,
                    doc.citation_id,
                    doc.legacy_id,
                    doc.family,
                    doc.owner_function,
                    doc.expires_at,
                    doc.origin,
                    rendered.page_count,
                    sha256_text(rendered.text),
                ),
            )
            for ic in ics:
                c = ic.chunk
                conn.execute(
                    "INSERT INTO chunk (chunk_id, doc_version_id, path, text, context_header, embedding, "
                    "classification) VALUES (%s, %s, %s, %s, %s, %s::vector, %s)",
                    (
                        c.chunk_id,
                        doc.version_id,
                        f"{c.section} ({c.pages})",
                        c.text,
                        ic.context_header,
                        to_pgvector(vec_by_id[c.chunk_id]),
                        doc.class_code,
                    ),
                )
                conn.execute(
                    "INSERT INTO rag_chunk_meta (chunk_id, ordinal, section, page_from, page_to, blocks, "
                    "base_header, "
                    "header_source, content_sha256) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)",
                    (
                        c.chunk_id,
                        c.ordinal,
                        c.section,
                        c.page_from,
                        c.page_to,
                        json.dumps(list(c.blocks)),
                        c.base_header,
                        ic.header.source if ic.header else "base",
                        c.content_sha,
                    ),
                )
    return {
        "documents": len(_document_rows(docs)),
        "versions": len(prepared),
        "chunks": len(all_chunks),
        "llm_headers": sum(1 for ic in all_chunks if ic.header and ic.header.source == "llm"),
    }
