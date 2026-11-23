"""Read models for `/v1`: decisions (case + its latest proposal) and commitments with milestones."""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from sgw.contracts.api_models import CommitmentMilestoneV1, CommitmentV1, DecisionV1

LIST_LIMIT = 500
_DECISIONS = (
    "SELECT c.decision_case_id, c.title, p.tier, p.state, c.decide_by_utc, c.effective_decide_by_utc,"
    " c.on_critical_path FROM decision_case c"
    " JOIN LATERAL (SELECT tier, state FROM proposal WHERE decision_case_id = c.decision_case_id"
    " ORDER BY created_at DESC, proposal_id DESC LIMIT 1) p ON true"
)


def _decision(row: dict[str, Any]) -> DecisionV1:
    return DecisionV1.model_validate(row)


async def list_decisions(conn: AsyncConnection[Any], limit: int = LIST_LIMIT) -> list[DecisionV1]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            _DECISIONS + " ORDER BY c.effective_decide_by_utc, c.decision_case_id LIMIT %s",  # noqa: S608
            (limit,),
        )
        return [_decision(r) for r in await cur.fetchall()]


async def get_decision(conn: AsyncConnection[Any], decision_case_id: str) -> DecisionV1 | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_DECISIONS + " WHERE c.decision_case_id = %s", (decision_case_id,))  # noqa: S608
        row = await cur.fetchone()
    return _decision(row) if row else None


async def list_commitments(conn: AsyncConnection[Any], limit: int = LIST_LIMIT) -> list[CommitmentV1]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT commitment_id, decision_case_id, state, promised_by_utc, projected_utc FROM commitment"
            " ORDER BY promised_by_utc, commitment_id LIMIT %s",
            (limit,),
        )
        rows = await cur.fetchall()
        ids = [r["commitment_id"] for r in rows]
        await cur.execute(
            "SELECT commitment_id, name, due_utc, met_utc FROM commitment_milestone"
            " WHERE commitment_id = ANY(%s) ORDER BY commitment_id, seq",
            (ids,),
        )
        milestones: dict[str, list[CommitmentMilestoneV1]] = {}
        for m in await cur.fetchall():
            milestones.setdefault(m["commitment_id"], []).append(
                CommitmentMilestoneV1(name=m["name"], due_utc=m["due_utc"], met_utc=m["met_utc"])
            )
    return [CommitmentV1(**r, milestones=milestones.get(r["commitment_id"], [])) for r in rows]
