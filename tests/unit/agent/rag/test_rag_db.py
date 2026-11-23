"""Retrieval and answer_sop against Postgres (pgvector + FTS) built from the committed corpus, headers
and embedding cache. The answer_sop runs replay through the real gateway from the committed
recordings, on exactly the passages each recorded run showed."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
import yaml

from sgw.agent.nodes.llm import GatewayClient, GatewayTags
from sgw.agent.rag.answer import answer_from_hits
from sgw.agent.rag.corpus import in_force, load_corpus
from sgw.agent.rag.embed import CachedPassages, default_embedder
from sgw.agent.rag.evaluate import evaluate_retrieval, grade_answer, load_items
from sgw.agent.rag.headers import load_headers
from sgw.agent.rag.index import build_index
from sgw.agent.rag.llm_config import RAG_FIXTURES, RAG_NODES_FILE
from sgw.agent.rag.search import hits_for_sources, search
from sgw.agent.rag.tool import guard_hit, search_procedures
from sgw.approval import testkit as tk
from sgw.contracts.tools import SearchProceduresArgs
from sgw.contracts.vocab import Classification

from ..agent_testkit import replay_gateway
from .rag_testkit import config, ctx

REPO = Path(__file__).resolve().parents[4]
DATA = Path(__file__).resolve().parent / "data"
NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
GATE = 0.90
PLANTED = ("signature needed", "20 minutes", "CANARY", "every generator is full", "stop reporting", "://")


@pytest.fixture(scope="module")
def conn() -> Iterator[psycopg.Connection[Any]]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with tk.scratch_database(prefix="sgw_wp18_t") as url, psycopg.connect(url) as c:
        build_index(c, load_corpus(), load_headers(), embedder=default_embedder(), cache=CachedPassages())
        c.commit()
        yield c


def test_dev_retrieval_meets_the_gate(conn: psycopg.Connection[Any]) -> None:
    report = evaluate_retrieval(
        conn, load_items(REPO / "evals" / "dev" / "retrieval.yaml"), default_embedder()
    )
    s = report["summary"]
    assert s["recall_at_k"] >= GATE and s["superseded_hit_items"] == 0, report["items"]


def test_builder_retrieval_meets_the_gate(conn: psycopg.Connection[Any]) -> None:
    report = evaluate_retrieval(conn, load_items(DATA / "builder_retrieval.yaml"), default_embedder())
    s = report["summary"]
    assert s["recall_at_k"] >= GATE and s["superseded_hit_items"] == 0
    found, total = map(int, s["exact_id_rank1"].split("/"))
    assert found == total


@pytest.mark.parametrize(
    "as_of", ["2022-12-01", "2023-06-15", "2024-03-01", "2024-09-20", "2024-09-27", "2025-03-01"]
)
def test_no_revision_out_of_force_is_ever_returned(conn: psycopg.Connection[Any], as_of: str) -> None:
    at = datetime.fromisoformat(as_of).replace(tzinfo=UTC)
    docs = load_corpus()
    live = {(d.doc_id, d.version) for d in in_force(docs, at)}
    queries = [f"{d.doc_id} Rev {d.revision}" for d in docs if d.status == "superseded"] + [
        "superseded revision retained for record",
        "global ETR deadline after the all-clear",
        "refuel request tank level standby generator",
        "onboarding briefing for mutual aid crews",
    ]
    for q in queries:
        for h in search(conn, q, as_of=at, embedder=default_embedder(), top_k=8):
            assert (h.doc_id, h.version) in live, (q, h.citation_id)


def test_pinned_lane_finds_current_and_legacy_ids(conn: psycopg.Connection[Any]) -> None:
    at = datetime(2024, 9, 27, 12, tzinfo=UTC)
    first = search(conn, "what does WOP-118 say", as_of=at, embedder=default_embedder())[0]
    assert (first.citation_id, first.lane) == ("WDS 03.318 Rev E", "pinned")
    first = search(conn, "GEP 2H.01 Rev E/1 phase table", as_of=at, embedder=default_embedder())[0]
    assert first.citation_id == "GEP 2H.01 Rev F"


def test_classification_ceiling_filters_results(conn: psycopg.Connection[Any]) -> None:
    args = SearchProceduresArgs(query="substation flood protection SCADA network", top_k=8)
    _, c1 = search_procedures(args, ctx(), conn=conn, embedder=default_embedder())
    _, c0 = search_procedures(args, ctx(ceiling=Classification.C0), conn=conn, embedder=default_embedder())
    assert c1 and all(g.hit.classification in ("C0", "C1") for g in c1)
    assert all(g.hit.classification == "C0" for g in c0)


def _recordings() -> dict[str, dict[str, Any]]:
    out = {}
    for path in sorted((RAG_FIXTURES / "answer_sop").glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        content = rec["request"]["messages"][0]["content"]
        question = content[-1]["text"].removeprefix("Question: ")
        out[question] = {"sources": [b["source"] for b in content if b["type"] == "search_result"]}
    return out


async def test_answer_sop_replay_cites_only_returned_in_force_passages(conn: psycopg.Connection[Any]) -> None:
    items = yaml.safe_load((DATA / "answer_items.yaml").read_text(encoding="utf-8"))
    recs = _recordings()
    docs = load_corpus()
    total = valid = llm_answers = 0
    with replay_gateway(RAG_FIXTURES, RAG_NODES_FILE) as url:
        client = GatewayClient(url, tags=GatewayTags(purpose="test", wave="W4"))
        for item in items["items"]:
            as_of = datetime.fromisoformat(item.get("as_of", items["default_as_of"]).replace("Z", "+00:00"))
            hits = [guard_hit(h) for h in hits_for_sources(conn, recs[item["question"]]["sources"])]
            out = await answer_from_hits(item["question"], ctx(as_of), hits, llm=client, config=config())
            assert out.reason in (None, "not_covered", "checks_failed"), (item["id"], out.reason)
            grade = grade_answer(
                out, docs=docs, as_of=as_of, returned={g.hit.chunk_id: "\n".join(g.blocks) for g in hits}
            )
            total += grade["citations"]
            valid += grade["valid"]
            llm_answers += out.mode == "llm" and out.reason is None
            if item.get("expect") == "not_covered":
                assert out.reason == "not_covered" and not out.citations, item["id"]
            assert not any(p in out.text for p in PLANTED), item["id"]
    assert total > 0 and valid == total
    assert llm_answers >= 13


async def test_answer_sop_replay_with_live_search_matches_the_recordings(
    conn: psycopg.Connection[Any],
) -> None:
    """Real search, then the answer stage, through a replay gateway: if the corpus, index, ranking or prompt
    drifts from the recordings, the request hash changes, the gateway returns a replay miss and this fails."""
    from sgw.agent.rag.answer import answer_sop

    items = yaml.safe_load((DATA / "answer_items.yaml").read_text(encoding="utf-8"))
    docs = load_corpus()
    total = valid = fallbacks = 0
    with replay_gateway(RAG_FIXTURES, RAG_NODES_FILE) as url:
        client = GatewayClient(url, tags=GatewayTags(purpose="test", wave="W4"))
        for item in items["items"]:
            as_of = datetime.fromisoformat(item.get("as_of", items["default_as_of"]).replace("Z", "+00:00"))
            out = await answer_sop(
                item["question"],
                ctx(as_of),
                conn=conn,
                embedder=default_embedder(),
                llm=client,
                config=config(),
            )
            assert out.reason in (None, "not_covered", "checks_failed"), (item["id"], out.reason)
            shown = {
                g.hit.chunk_id: "\n".join(g.blocks)
                for g in map(
                    guard_hit,
                    search(conn, item["question"], as_of=as_of, embedder=default_embedder(), top_k=6),
                )
            }
            grade = grade_answer(out, docs=docs, as_of=as_of, returned=shown)
            total += grade["citations"]
            valid += grade["valid"]
            fallbacks += out.mode == "template"
            if item["id"] == "A-21":
                assert out.reason == "not_covered" and not out.citations
    assert total > 0 and valid == total
    assert fallbacks <= 6
