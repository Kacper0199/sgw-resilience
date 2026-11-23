"""Retrieval metrics as defined in evals/README.md: recall@8 (fraction of relevant documents, at the revision
in force at as_of, found in the top 8), superseded-hit rate (items with a `must_not_retrieve` document or any
revision not in force at as_of in the top 8) and exact-id rank-1 rate. The in-force check here is computed
from the source files, independently of the SQL filter it tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import yaml

from sgw.agent.rag.corpus import Document, in_force, load_corpus
from sgw.agent.rag.embed import Embedder
from sgw.agent.rag.search import Hit, search


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def load_items(path: Path) -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")))


def _matches(hit: Hit, doc_id: str, revision: str | None) -> bool:
    return hit.doc_id == doc_id and (revision is None or hit.version == revision)


def evaluate_retrieval(
    conn: psycopg.Connection[Any],
    spec: dict[str, Any],
    embedder: Embedder,
    *,
    docs: Sequence[Document] | None = None,
) -> dict[str, Any]:
    docs = docs if docs is not None else load_corpus()
    k = int(spec.get("k", 8))
    default_as_of = spec.get("default_as_of", "2024-09-27T12:00:00Z")
    rows = []
    for item in spec["items"]:
        as_of = _dt(item.get("as_of", default_as_of))
        live = {(d.doc_id, d.version) for d in in_force(docs, as_of)}
        hits = search(conn, item["query"], as_of=as_of, embedder=embedder, top_k=k)
        relevant = item.get("relevant", [])
        found = sum(1 for r in relevant if any(_matches(h, r["doc_id"], r.get("revision")) for h in hits))
        bad = [
            h.citation_id
            for h in hits
            if (h.doc_id, h.version) not in live
            or any(_matches(h, m["doc_id"], m.get("revision")) for m in item.get("must_not_retrieve", []))
        ]
        rank1 = (
            bool(hits)
            and bool(relevant)
            and _matches(hits[0], relevant[0]["doc_id"], relevant[0].get("revision"))
        )
        rows.append(
            {
                "id": item["id"],
                "kind": item.get("kind"),
                "recall": found / len(relevant) if relevant else 1.0,
                "superseded_hits": len(bad),
                "superseded": bad,
                "rank1": rank1,
                "top": [f"{h.citation_id} [{h.lane}]" for h in hits],
            }
        )
    n = len(rows)
    exact = [r for r in rows if r["kind"] in ("exact_id", "legacy_id")]
    summary = {
        "split": spec.get("split"),
        "n": n,
        "recall_at_k": round(sum(r["recall"] for r in rows) / n, 4) if n else None,
        "items_full_recall": sum(1 for r in rows if r["recall"] == 1.0),
        "superseded_hit_items": sum(1 for r in rows if r["superseded_hits"]),
        "exact_id_rank1": f"{sum(r['rank1'] for r in exact)}/{len(exact)}" if exact else None,
        "k": k,
    }
    return {"summary": summary, "items": rows}


def _fact_values(fact: str) -> list[str]:
    import re

    return [
        v
        for v in re.findall(r"[A-Z][A-Z0-9]*(?:[-/][A-Z0-9]+)+|\d+(?:[.,]\d+)*", fact)
        if not re.fullmatch(r"[A-Z]", v)
    ]


def grade_answer(
    answer: Any,
    *,
    docs: Sequence[Document],
    as_of: datetime,
    returned: dict[str, str],
    facts: Sequence[str] = (),
) -> dict[str, Any]:
    """Citation validity per evals/README.md, checked against the source files: the cited passage was
    returned in this run, its revision is in force at as_of, and the cited span is text of that passage.
    `returned` maps chunk id -> passage text as shown to the model. `fact_cited` says whether some cited
    span carries every value of an expected fact."""
    live = {(d.doc_id, d.version) for d in in_force(docs, as_of)}
    rows = []
    for c in answer.citations:
        shown = "".join(returned.get(c.source, "").split())
        rows.append(
            {
                "citation": c.citation_id,
                "returned": c.source in returned,
                "in_force": (c.doc_id, c.version) in live,
                "span_in_passage": bool(c.cited_text) and "".join(c.cited_text.split()) in shown,
            }
        )
    valid = sum(1 for r in rows if r["returned"] and r["in_force"] and r["span_in_passage"])
    spans = " ".join(c.cited_text for c in answer.citations)
    fact_cited = [all(v in spans for v in _fact_values(f)) for f in facts]
    return {"citations": len(rows), "valid": valid, "rows": rows, "fact_cited": fact_cited}


async def evaluate_answers(
    conn: psycopg.Connection[Any],
    spec: dict[str, Any],
    llm: Any,
    embedder: Embedder,
    *,
    docs: Sequence[Document] | None = None,
) -> dict[str, Any]:
    from sgw.agent.nodes.llm import node_config
    from sgw.agent.rag.answer import NODE, answer_sop
    from sgw.agent.rag.llm_config import RAG_NODES_FILE
    from sgw.agent.rag.search import search as run_search
    from sgw.agent.rag.tool import guard_hit
    from sgw.contracts.tools import InjectedContext
    from sgw.contracts.vocab import ApprovalFunction, Classification, RunMode

    docs = docs if docs is not None else load_corpus()
    config = node_config(NODE, RAG_NODES_FILE)
    default_as_of = spec.get("default_as_of", "2024-09-27T12:00:00Z")
    rows = []
    for item in spec["items"]:
        as_of = _dt(item.get("as_of", default_as_of))
        ctx = InjectedContext(
            as_of=as_of,
            user_id="ops_dm_02",
            user_role=list(ApprovalFunction)[0],
            region_ids=[],
            run_mode=list(RunMode)[0],
            classification_ceiling=Classification.C1,
        )
        ans = await answer_sop(item["question"], ctx, conn=conn, embedder=embedder, llm=llm, config=config,
                               run_id=f"eval-{item['id']}")  # fmt: skip
        shown = {
            g.hit.chunk_id: "\n".join(g.blocks)
            for g in map(
                guard_hit, run_search(conn, item["question"], as_of=as_of, embedder=embedder, top_k=6)
            )
        }
        grade = grade_answer(ans, docs=docs, as_of=as_of, returned=shown, facts=item.get("facts", []))
        rows.append(
            {
                "id": item["id"],
                "mode": ans.mode,
                "reason": ans.reason,
                "tainted": ans.tainted,
                "violations": ans.violations,
                "text": ans.text,
                "expect": item.get("expect", "answer"),
                **{k: grade[k] for k in ("citations", "valid", "rows", "fact_cited")},
            }
        )
    total = sum(r["citations"] for r in rows)
    valid = sum(r["valid"] for r in rows)
    llm_rows = [r for r in rows if r["mode"] == "llm"]
    summary = {
        "n": len(rows),
        "citation_validity": f"{valid}/{total}",
        "citation_validity_ppm": round(1_000_000 * valid / total) if total else None,
        "llm_answers": len(llm_rows),
        "template_fallbacks": sum(1 for r in rows if r["mode"] == "template"),
        "not_covered": sum(1 for r in rows if r["reason"] == "not_covered"),
        "facts_cited": f"{sum(sum(r['fact_cited']) for r in rows)}/{sum(len(r['fact_cited']) for r in rows)}",
    }
    return {"summary": summary, "items": rows}
