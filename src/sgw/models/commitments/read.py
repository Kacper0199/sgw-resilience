"""Read side of the commitment watch for K3 `/api/commitments` (list, detail, milestones)."""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from sgw.contracts.api_models import (
    CommitmentDetail,
    CommitmentDriftEntry,
    CommitmentMilestone,
    CommitmentSummary,
)
from sgw.models.commitments.watch import ceil_min

LIST_LIMIT = 500

_SUMMARY = """
SELECT c.commitment_id, c.decision_case_id, c.proposal_id, dc.title, c.state, c.promised_by_utc,
       c.projected_utc,
       count(m.seq) FILTER (WHERE m.met_utc IS NOT NULL)::int AS milestones_met,
       count(m.seq)::int AS milestones_total
FROM commitment c
JOIN decision_case dc ON dc.decision_case_id = c.decision_case_id
LEFT JOIN commitment_milestone m ON m.commitment_id = c.commitment_id
WHERE (%(state)s::text IS NULL OR c.state = %(state)s::text)
  AND (%(cid)s::text IS NULL OR c.commitment_id = %(cid)s::text)
GROUP BY c.commitment_id, dc.title
ORDER BY c.promised_by_utc, c.commitment_id
LIMIT %(limit)s
"""

_MILESTONES = """
SELECT m.seq, m.name, m.due_utc, m.met_utc, p.lead_key, p.remaining_min, p.signal ->> 'type' AS signal_type
FROM commitment_milestone m
LEFT JOIN commitment_milestone_plan p ON p.commitment_id = m.commitment_id AND p.seq = m.seq
WHERE m.commitment_id = %s
ORDER BY m.seq
"""

_DRIFT = """
SELECT seq, detected_at, state, reason, milestone_seq, promised_by_utc, projected_utc, drift_min,
       tolerance_min, reopened, proposal_version, note
FROM commitment_drift WHERE commitment_id = %s ORDER BY seq
"""


def _summary(row: dict[str, Any]) -> CommitmentSummary:
    projected = row["projected_utc"]
    drift = None if projected is None else max(ceil_min(projected - row["promised_by_utc"]), 0)
    return CommitmentSummary(**row, drift_min=drift)


async def _summaries(
    conn: AsyncConnection[Any], *, state: str | None = None, commitment_id: str | None = None
) -> list[CommitmentSummary]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_SUMMARY, {"state": state, "cid": commitment_id, "limit": LIST_LIMIT})
        return [_summary(r) for r in await cur.fetchall()]


async def list_commitments(conn: AsyncConnection[Any], state: str | None = None) -> list[CommitmentSummary]:
    return await _summaries(conn, state=state)


async def milestones(conn: AsyncConnection[Any], commitment_id: str) -> list[CommitmentMilestone] | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT 1 FROM commitment WHERE commitment_id = %s", (commitment_id,))
        if await cur.fetchone() is None:
            return None
        await cur.execute(_MILESTONES, (commitment_id,))
        return [CommitmentMilestone(**r) for r in await cur.fetchall()]


async def detail(conn: AsyncConnection[Any], commitment_id: str) -> CommitmentDetail | None:
    found = await _summaries(conn, commitment_id=commitment_id)
    if not found:
        return None
    steps = await milestones(conn, commitment_id) or []
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_DRIFT, (commitment_id,))
        log = [CommitmentDriftEntry(**r) for r in await cur.fetchall()]
    return CommitmentDetail(**found[0].model_dump(), milestones=steps, drift_log=log)
