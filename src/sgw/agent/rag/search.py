"""Hybrid retrieval over the in-force corpus at a scenario time.

1. In-force filter (SQL, before ranking): per document the latest revision effective on or before `as_of`,
   dropped when expired at `as_of`. Superseded and not-yet-effective revisions never reach a ranking list, so
   they cannot be returned, cited or pinned.
2. Classification filter: only chunks whose class the caller may read (K5 `search_procedures`: C0, C1).
3. Dense lane (pgvector cosine, bge-small) and full-text lane (Postgres FTS, OR of the query lexemes),
   fused by reciprocal rank fusion (k = 60).
4. Pinned-id lane: a document id, legacy id or citation id written in the query (`WQC 07.114`, `WOP-118`,
   `GEP 2H.01 Rev F`) puts that document's best chunk at rank 1, ahead of the fused list.
5. One result per document revision (`top_k` documents), carrying its best `per_doc` chunks in document
   order; the result `source` names them (`WQC 07.114@E#03+05`).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from sgw.agent.rag.embed import Embedder, to_pgvector
from sgw.agent.rag.index import norm_alias

RRF_K = 60
LANE_DEPTH = 40
MAX_ALIAS_TOKENS = 4

_CANDIDATES = """
WITH live AS (
    SELECT DISTINCT ON (v.doc_id) v.doc_version_id, v.doc_id, m.expires_at
    FROM doc_version v JOIN rag_version_meta m USING (doc_version_id)
    WHERE v.effective_from <= %(as_of)s AND v.available_at <= %(as_of)s
    ORDER BY v.doc_id, v.effective_from DESC
), inforce AS (
    SELECT doc_version_id, doc_id FROM live WHERE expires_at IS NULL OR expires_at > %(as_of)s
), cand AS (
    SELECT c.chunk_id, i.doc_id, c.embedding, c.tsv
    FROM chunk c JOIN inforce i USING (doc_version_id)
    WHERE c.classification = ANY(%(classes)s)
), q AS (
    SELECT to_tsquery('simple', coalesce(string_agg(quote_literal(l), ' | '), '')) AS q
    FROM unnest(tsvector_to_array(to_tsvector('english', %(query)s))) AS l
), dense AS (
    SELECT chunk_id, doc_id, row_number() OVER (ORDER BY embedding <=> %(qvec)s::vector) AS r
    FROM cand ORDER BY embedding <=> %(qvec)s::vector LIMIT %(depth)s
), sparse AS (
    SELECT chunk_id, doc_id, row_number() OVER (ORDER BY ts_rank_cd(tsv, q.q) DESC, chunk_id) AS r
    FROM cand, q WHERE tsv @@ q.q ORDER BY ts_rank_cd(tsv, q.q) DESC, chunk_id LIMIT %(depth)s
), pinned AS (
    SELECT chunk_id, doc_id,
           row_number() OVER (PARTITION BY doc_id ORDER BY embedding <=> %(qvec)s::vector) AS r
    FROM cand WHERE doc_id = ANY(%(pinned)s)
)
SELECT coalesce(d.chunk_id, s.chunk_id) AS chunk_id, coalesce(d.doc_id, s.doc_id) AS doc_id,
       d.r AS dense_rank, s.r AS sparse_rank, NULL::bigint AS pin_rank
FROM dense d FULL JOIN sparse s USING (chunk_id)
UNION ALL
SELECT chunk_id, doc_id, NULL, NULL, r FROM pinned WHERE r <= 2
"""

_DETAILS = """
SELECT c.chunk_id, v.doc_id, v.version, m.citation_id, d.title, cm.section, cm.page_from, cm.page_to,
       cm.blocks, d.trust, c.classification, v.effective_from, m.family, m.expires_at, cm.ordinal
FROM chunk c
JOIN doc_version v USING (doc_version_id)
JOIN rag_version_meta m USING (doc_version_id)
JOIN rag_chunk_meta cm USING (chunk_id)
JOIN document d ON d.doc_id = v.doc_id
WHERE c.chunk_id = ANY(%(ids)s)
"""


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    doc_id: str
    version: str
    citation_id: str
    title: str
    section: str
    page_from: int
    page_to: int
    blocks: tuple[str, ...]
    trust: str
    classification: str
    effective_from: datetime
    family: str
    expires_at: datetime | None
    ordinal: int
    score: float
    lane: str

    @property
    def revision(self) -> str | None:
        return None if self.version == "issued" else self.version

    @property
    def pages(self) -> str:
        if self.page_from == self.page_to:
            return f"p. {self.page_from}"
        return f"pp. {self.page_from}-{self.page_to}"


def find_aliases(conn: psycopg.Connection[Any], query: str) -> list[str]:
    """Document ids written in the query, longest match first."""
    tokens = [t for t in re.split(r"\s+", query.strip()) if t]
    grams: set[str] = set()
    for n in range(1, MAX_ALIAS_TOKENS + 1):
        for i in range(len(tokens) - n + 1):
            norm = norm_alias(" ".join(tokens[i : i + n]))
            if len(norm) >= 4 and re.search(r"\d", norm):
                grams.add(norm)
    if not grams:
        return []
    rows = conn.execute(
        "SELECT doc_id, max(length(alias_norm)) AS l FROM rag_alias WHERE alias_norm = ANY(%s) "
        "GROUP BY doc_id ORDER BY l DESC, doc_id",
        (sorted(grams),),
    ).fetchall()
    return [r[0] for r in rows]


def _merged_hit(source: str, rows: Sequence[Any], score: float, lane: str) -> Hit:
    first = rows[0]
    sections = list(dict.fromkeys(s for r in rows for s in str(r[5]).split("; ") if s))
    return Hit(
        chunk_id=source,
        doc_id=first[1],
        version=first[2],
        citation_id=first[3],
        title=first[4],
        section="; ".join(sections),
        page_from=min(r[6] for r in rows),
        page_to=max(r[7] for r in rows),
        blocks=tuple(b for r in rows for b in r[8]),
        trust=first[9],
        classification=first[10],
        effective_from=first[11],
        family=first[12],
        expires_at=first[13],
        ordinal=first[14],
        score=score,
        lane=lane,
    )


def search(
    conn: psycopg.Connection[Any],
    query: str,
    *,
    as_of: datetime,
    embedder: Embedder,
    classes: Sequence[str] = ("C0", "C1"),
    top_k: int = 8,
    per_doc: int = 2,
) -> list[Hit]:
    pinned = find_aliases(conn, query)
    qvec = to_pgvector(embedder.query(query))
    rows = conn.execute(
        _CANDIDATES,
        {
            "as_of": as_of,
            "classes": list(classes),
            "query": query,
            "qvec": qvec,
            "depth": LANE_DEPTH,
            "pinned": pinned,
        },
    ).fetchall()
    fused: dict[str, float] = {}
    doc_of: dict[str, str] = {}
    pin_rank: dict[str, int] = {}
    for chunk_id, doc_id, dense_rank, sparse_rank, prank in rows:
        doc_of[chunk_id] = doc_id
        if prank is not None:
            pin_rank[chunk_id] = int(prank)
            continue
        score = 0.0
        if dense_rank is not None:
            score += 1.0 / (RRF_K + dense_rank)
        if sparse_rank is not None:
            score += 1.0 / (RRF_K + sparse_rank)
        fused[chunk_id] = score
    order: list[tuple[str, float, str]] = []
    for doc_id in pinned:
        best = sorted(
            (c for c, d in doc_of.items() if d == doc_id and c in pin_rank),
            key=lambda c: (-fused.get(c, 0.0), pin_rank[c]),
        )
        order += [(c, 1.0 + fused.get(c, 0.0), "pinned") for c in best[:1]]
    order += [(c, s, "hybrid") for c, s in sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))]
    groups: dict[str, list[tuple[str, float, str]]] = {}
    seen: set[str] = set()
    for chunk_id, score, lane in order:
        doc_id = doc_of[chunk_id]
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        if doc_id not in groups:
            if len(groups) >= top_k:
                continue
            groups[doc_id] = []
        if len(groups[doc_id]) < per_doc:
            groups[doc_id].append((chunk_id, score, lane))
    if not groups:
        return []
    ids = [c for g in groups.values() for c, _, _ in g]
    details = {r[0]: r for r in conn.execute(_DETAILS, {"ids": ids}).fetchall()}
    hits = []
    for members in groups.values():
        rows = sorted((details[c] for c, _, _ in members), key=lambda r: r[14])
        source = f"{rows[0][0].rsplit('#', 1)[0]}#" + "+".join(f"{r[14]:02d}" for r in rows)
        hits.append(_merged_hit(source, rows, members[0][1], members[0][2]))
    return hits


def hits_for_sources(conn: psycopg.Connection[Any], sources: Sequence[str]) -> list[Hit]:
    """Rebuild results from their `source` strings (`<doc_id>@<version>#03+05`), in the given order: replays a
    recorded run on exactly the passages it showed, independent of ranking."""
    wanted: list[tuple[str, list[str]]] = []
    for src in sources:
        base, _, ords = src.rpartition("#")
        wanted.append((src, [f"{base}#{o}" for o in ords.split("+")]))
    ids = [c for _, cs in wanted for c in cs]
    details = {r[0]: r for r in conn.execute(_DETAILS, {"ids": ids}).fetchall()}
    return [_merged_hit(src, [details[c] for c in cs], 0.0, "replay") for src, cs in wanted]
