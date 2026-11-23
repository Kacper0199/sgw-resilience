"""Evidence behind a decision card: `GET /api/proposals/{proposal_id}/evidence`.

A proposal's `evidence_ids` (`E1`, `E2`, ...) are ids inside the evidence bundle of the agent run that made
it, not global ids, so they resolve through the proposal: its `run_id`, the run's checkpoint thread
(`<thread_id>:<run_id>`) and the bundle the graph stored in its state. One record per id, in the card's
order: kind, title (the item label), source (its citation), as-of time, model version, classification and
trust. Labels are shown up to C1 to every reader and at C2 to users whose domains include the proposal's
domain; otherwise (and always above C2) the title is withheld and `withheld` is true. Proposals made outside
a run (seed, API) have no bundle: their records say `recorded: false`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from psycopg.rows import dict_row

from sgw.agent.render.evidence import EvidenceBundle, EvidenceItem
from sgw.api.deps import CurrentUser, DbConn
from sgw.api.errors import NotFound
from sgw.api.readmodels.http import read_span
from sgw.api.routers import runs
from sgw.api.sessions import AuthUser
from sgw.contracts.api_models import EvidenceRecord
from sgw.contracts.vocab import Classification

router = APIRouter(tags=["decisions"])
PROPOSAL = (
    "SELECT proposal_id, evidence_ids, run_id, domain::text AS domain FROM proposal WHERE proposal_id = %s"
)
RUN = "SELECT thread_id, graph FROM agent_run WHERE run_id = %s"
OPEN = frozenset({Classification.C0, Classification.C1})


async def _one(conn: Any, sql: str, args: tuple[Any, ...]) -> dict[str, Any] | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, args)
        row: dict[str, Any] | None = await cur.fetchone()
        return row


def _may_see(level: Classification, user: AuthUser, domain: str) -> bool:
    if level in OPEN:
        return True
    return level is Classification.C2 and domain in {d.value for d in user.domains}


def _record(item: EvidenceItem, run_id: str, graph: str, user: AuthUser, domain: str) -> EvidenceRecord:
    shown = _may_see(item.label_classification, user, domain) and _may_see(item.classification, user, domain)
    return EvidenceRecord(
        id=item.id,
        recorded=True,
        kind=item.kind,
        title=item.label if shown else None,
        source=item.citation if shown else None,
        as_of_utc=item.as_of,
        model_version=item.model_version,
        classification=item.classification,
        trust=item.trust.value,
        withheld=not shown,
        run_id=run_id,
        graph=graph,
    )


async def _bundle(
    runtime: runs.AgentRuntime, thread_id: str, run_id: str, graph: str
) -> EvidenceBundle | None:
    build = runs.GRAPHS.get(graph)
    if build is None:
        return None
    config = {"configurable": {"thread_id": f"{thread_id}:{run_id}"}}
    snap = await build(runtime.checkpointer).aget_state(config)
    raw = dict(snap.values or {}).get("bundle")
    return EvidenceBundle.model_validate(raw) if raw else None


@router.get(
    "/api/proposals/{proposal_id}/evidence",
    operation_id="listProposalEvidence",
    response_model=list[EvidenceRecord],
)
async def list_proposal_evidence(
    proposal_id: str, user: CurrentUser, conn: DbConn, runtime: runs.Runtime
) -> list[EvidenceRecord]:
    with read_span("proposals.evidence", user):
        p = await _one(conn, PROPOSAL, (proposal_id,))
        if p is None:
            raise NotFound(f"proposal {proposal_id} not found", code="PROPOSAL_NOT_FOUND")
        ids = [str(e) for e in p["evidence_ids"] or []]
        run = await _one(conn, RUN, (p["run_id"],)) if p["run_id"] else None
        bundle = await _bundle(runtime, run["thread_id"], p["run_id"], run["graph"]) if run else None
        items = bundle.by_id() if bundle else {}
        return [
            _record(items[e], p["run_id"], run["graph"], user, p["domain"])
            if e in items and run
            else EvidenceRecord(id=e, recorded=False)
            for e in ids
        ]
