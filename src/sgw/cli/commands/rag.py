from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from sgw.cli.support import CliError, guard

app = typer.Typer(
    name="rag",
    help="Procedure corpus and retrieval (WP-18): build, chunk headers, index, search, eval, answer_sop.",
)

DEFAULT_DB = "sgw_wp18"
DEFAULT_AS_OF = "2024-09-27T12:00:00Z"


def _dsn(database: str) -> str:
    env = os.environ.get("SGW_RAG_DATABASE_URL")
    if env:
        return env
    from sgw.cli.support import load_credentials

    return load_credentials().owner_dsn(database)


def _as_of(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@app.command("corpus")
@guard
def corpus(
    check: Annotated[bool, typer.Option("--check", help="Fail on drift instead of writing.")] = False,
) -> None:
    """Run the template generator, render every document and write MANIFEST.yaml."""
    from sgw.agent.rag.build import build

    result = build(check=check)
    typer.echo(json.dumps(result["counts"], indent=1))
    if result["drift"]:
        typer.echo(f"{len(result['drift'])} file(s) {'differ' if check else 'written'}")
        if check:
            for p in result["drift"][:20]:
                typer.echo(f"  {p}")
            raise CliError("corpus drift: run `uv run sgw rag corpus`")


@app.command("headers")
@guard
def headers(
    gateway: Annotated[str, typer.Option("--gateway", help="Gateway base URL.")] = "http://127.0.0.1:8100",
    nodes_file: Annotated[Path | None, typer.Option("--nodes-file")] = None,
    concurrency: Annotated[int, typer.Option("--concurrency")] = 4,
    limit: Annotated[int, typer.Option("--limit", help="At most this many documents (0 = all).")] = 0,
) -> None:
    """Generate missing chunk headers through the gateway (one Haiku call per document) and save them."""
    from sgw.agent.nodes.llm import GatewayClient, node_config
    from sgw.agent.rag.chunking import chunk_document
    from sgw.agent.rag.corpus import load_corpus
    from sgw.agent.rag.headers import HEADERS_FILE, NODE, generate_headers, load_headers, save_headers
    from sgw.agent.rag.llm_config import RAG_NODES_FILE
    from sgw.agent.rag.render import render

    docs = load_corpus()
    groups = [(d, chunk_document(render(d))) for d in docs]
    existing = load_headers()
    todo = [
        g
        for g in groups
        if not all(c.content_sha in existing and existing[c.content_sha].source == "llm" for c in g[1])
    ]
    if limit:
        keep = {g[0].version_id for g in todo[:limit]}
        groups = [
            g for g in groups if g[0].version_id in keep or all(c.content_sha in existing for c in g[1])
        ]
    config = node_config(NODE, nodes_file or RAG_NODES_FILE)
    records, stats = asyncio.run(
        generate_headers(groups, GatewayClient(gateway), config, existing=existing, concurrency=concurrency)
    )
    merged = {**existing, **{r.content_sha: r for r in records}}
    save_headers(list(merged.values()))
    typer.echo(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in stats.items()}))
    for f in stats["failed"][:10]:
        typer.echo(f"  failed: {f}")
    typer.echo(f"saved {len(merged)} headers to {HEADERS_FILE}")


@app.command("index")
@guard
def index(database: Annotated[str, typer.Option("--database", "-d")] = DEFAULT_DB) -> None:
    """Embed (cache first) and load the corpus into Postgres."""
    import psycopg

    from sgw.agent.rag.corpus import load_corpus
    from sgw.agent.rag.embed import CachedPassages, default_embedder
    from sgw.agent.rag.headers import load_headers
    from sgw.agent.rag.index import build_index, prepare

    docs = load_corpus()
    hdrs = load_headers()
    cache = CachedPassages()
    with psycopg.connect(_dsn(database)) as conn:
        stats = build_index(conn, docs, hdrs, embedder=default_embedder(), cache=cache)
    cache.save(keep=[ic.embed_input for _, _, ics in prepare(docs, hdrs) for ic in ics])
    typer.echo(json.dumps(stats))


@app.command("search")
@guard
def search_cmd(
    query: str,
    database: Annotated[str, typer.Option("--database", "-d")] = DEFAULT_DB,
    as_of: Annotated[str, typer.Option("--as-of")] = DEFAULT_AS_OF,
    top_k: Annotated[int, typer.Option("--top-k")] = 8,
) -> None:
    """Hybrid search over the documents in force at --as-of."""
    import psycopg

    from sgw.agent.rag.embed import default_embedder
    from sgw.agent.rag.search import search

    with psycopg.connect(_dsn(database)) as conn:
        hits = search(conn, query, as_of=_as_of(as_of), embedder=default_embedder(), top_k=top_k)
    for n, h in enumerate(hits, start=1):
        typer.echo(f"{n:2} {h.lane:6} {h.score:.4f} {h.citation_id:28} {h.section[:40]:40} {h.pages}")


@app.command("eval")
@guard
def eval_cmd(
    items: Annotated[Path, typer.Option("--items")] = Path("evals/dev/retrieval.yaml"),
    database: Annotated[str, typer.Option("--database", "-d")] = DEFAULT_DB,
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Retrieval metrics (recall@8, superseded hits, exact-id rank 1) on an items file."""
    import psycopg

    from sgw.agent.rag.embed import default_embedder
    from sgw.agent.rag.evaluate import evaluate_retrieval, load_items

    with psycopg.connect(_dsn(database)) as conn:
        report = evaluate_retrieval(conn, load_items(items), default_embedder())
    typer.echo(json.dumps(report["summary"], indent=1))
    for row in report["items"]:
        if row["recall"] < 1 or row["superseded_hits"]:
            typer.echo(
                f"  {row['id']}: recall {row['recall']:.2f} superseded {row['superseded_hits']} "
                f"top {row['top'][:4]}"
            )
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _ctx(as_of: str) -> object:
    from sgw.contracts.tools import InjectedContext
    from sgw.contracts.vocab import ApprovalFunction, Classification, RunMode

    return InjectedContext(
        as_of=_as_of(as_of),
        user_id="ops_dm_02",
        user_role=list(ApprovalFunction)[0],
        region_ids=[],
        run_mode=list(RunMode)[0],
        classification_ceiling=Classification.C1,
    )


@app.command("answer")
@guard
def answer_cmd(
    question: str,
    gateway: Annotated[str, typer.Option("--gateway")] = "http://127.0.0.1:8100",
    database: Annotated[str, typer.Option("--database", "-d")] = DEFAULT_DB,
    as_of: Annotated[str, typer.Option("--as-of")] = DEFAULT_AS_OF,
) -> None:
    """answer_sop: cited answer from the in-force corpus (template fallback when checks fail)."""
    import psycopg

    from sgw.agent.nodes.llm import GatewayClient, node_config
    from sgw.agent.rag.answer import NODE, answer_sop
    from sgw.agent.rag.embed import default_embedder
    from sgw.agent.rag.llm_config import RAG_NODES_FILE

    with psycopg.connect(_dsn(database)) as conn:
        out = asyncio.run(
            answer_sop(
                question,
                _ctx(as_of),  # type: ignore[arg-type]
                conn=conn,
                embedder=default_embedder(),
                llm=GatewayClient(gateway),
                config=node_config(NODE, RAG_NODES_FILE),
            )
        )
    typer.echo(f"mode={out.mode} reason={out.reason} tainted={out.tainted}")
    for v in out.violations:
        typer.echo(f"  violation: {v}")
    typer.echo(out.text)


@app.command("answer-eval")
@guard
def answer_eval_cmd(
    items: Annotated[Path, typer.Option("--items")] = Path("tests/unit/agent/rag/data/answer_items.yaml"),
    gateway: Annotated[str, typer.Option("--gateway")] = "http://127.0.0.1:8100",
    database: Annotated[str, typer.Option("--database", "-d")] = DEFAULT_DB,
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Run answer_sop on an items file and grade citation validity (replay gateway: keyless)."""
    import psycopg

    from sgw.agent.nodes.llm import GatewayClient
    from sgw.agent.rag.embed import default_embedder
    from sgw.agent.rag.evaluate import evaluate_answers, load_items

    with psycopg.connect(_dsn(database)) as conn:
        report = asyncio.run(
            evaluate_answers(conn, load_items(items), GatewayClient(gateway), default_embedder())
        )
    typer.echo(json.dumps(report["summary"], indent=1))
    for row in report["items"]:
        typer.echo(
            f"  {row['id']}: {row['mode']} {row['reason']} cites {row['valid']}/{row['citations']} "
            f"{row['violations'][:2]}"
        )
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
