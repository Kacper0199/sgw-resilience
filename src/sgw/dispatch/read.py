"""Read side of crew dispatch: open assignments with their target labels as known at a scenario time, the
assignable targets, and the persona facts the policy needs. Shared by the crews read model
(`sgw.models.restoration.field.crews`), the API and the write service, so every reader sees the same rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import AsyncConnection, Connection
from psycopg.rows import dict_row

from sgw.contracts.api_models import CrewAssignment, CrewTarget

ACTIVE_STATES = ("proposed", "assigned")
OPEN_CASE_STATES = ("proposed", "in_review", "escalated", "approved")

ASSIGNMENTS = """
SELECT a.assignment_id, a.crew_id, a.target_kind, a.target_id, a.state,
       a.required_function::text AS required_function,
       a.proposed_by, a.proposed_at, a.decided_by, a.decided_at,
       coalesce(c.title, y.name, a.target_id) AS target_label, lp.proposal_id AS decision_proposal_id
FROM crew_assignment a
LEFT JOIN decision_case c ON a.target_kind = 'decision' AND c.decision_case_id = a.target_id
LEFT JOIN asset y ON a.target_kind = 'yard' AND y.asset_id = a.target_id
LEFT JOIN LATERAL (SELECT p.proposal_id, p.state::text AS state FROM proposal p
                   WHERE p.decision_case_id = c.decision_case_id
                   ORDER BY p.created_at DESC, p.proposal_id DESC LIMIT 1) lp ON a.target_kind = 'decision'
WHERE a.state = ANY(%(states)s) AND a.proposed_at <= %(at)s
ORDER BY a.crew_id
"""

TARGETS = """
SELECT 'decision' AS kind, c.decision_case_id AS target_id, c.title AS label, lp.proposal_id,
       c.effective_decide_by_utc AS sort_at
FROM decision_case c JOIN LATERAL (SELECT p.proposal_id, p.state::text AS state FROM proposal p
                   WHERE p.decision_case_id = c.decision_case_id
                   ORDER BY p.created_at DESC, p.proposal_id DESC LIMIT 1) lp ON true
WHERE lp.state = ANY(%(open)s)
UNION ALL
SELECT 'yard', a.asset_id, a.name, NULL, NULL FROM asset a WHERE a.kind = 'staging_yard'
ORDER BY 1, 5 NULLS LAST, 2
"""

SUBJECT = (
    "SELECT user_id, roles, functions::text[] AS functions, can_approve, on_shift"
    " FROM app_user WHERE user_id = %s"
)


YARD_PLACES = {
    "REEDYSHOALS": "Reedy Shoals",
    "ASHLEYFERRY": "Ashley Ferry",
    "OGEECHEEWHARF": "Ogeechee Wharf",
    "NORTHOCONEE": "North Oconee",
    "LYNCHESRUN": "Lynches Run",
    "OCONEEFLATS": "Oconee Flats",
    "CONGAREEBEND": "Congaree Bend",
    "OKEFENOKEEGATE": "Okefenokee Gate",
    "CATAWBALANDING": "Catawba Landing",
}


def yard_label(asset_id: str, name: str | None = None) -> str:
    """A yard id such as STG-AIK-SANDHILL-YARD reads as "Sandhill yard" (STG-GVL-REEDYSHOALS-YARD as "Reedy
    Shoals yard"), the words the Crews page and the decision titles use."""
    parts = asset_id.split("-")
    if len(parts) >= 4 and parts[0] == "STG":
        return f"{YARD_PLACES.get(parts[2], parts[2].capitalize())} yard"
    return (name or asset_id).replace(" (synthetic)", "")


def _label(row: dict[str, Any]) -> str:
    if row["target_kind"] == "yard":
        return yard_label(row["target_id"], row["target_label"])
    return str(row["target_label"])


def assignment_of(row: dict[str, Any]) -> CrewAssignment:
    return CrewAssignment(
        assignment_id=row["assignment_id"],
        target_kind=row["target_kind"],
        target_id=row["target_id"],
        target_label=_label(row),
        decision_proposal_id=row.get("decision_proposal_id"),
        state=row["state"],
        required_function=row["required_function"],
        proposed_by=row["proposed_by"],
        proposed_at=row["proposed_at"],
        decided_by=row["decided_by"],
        decided_at=row["decided_at"],
    )


def _target(row: dict[str, Any]) -> CrewTarget:
    label = yard_label(row["target_id"], row["label"]) if row["kind"] == "yard" else str(row["label"])
    return CrewTarget(
        kind=row["kind"], target_id=row["target_id"], label=label, proposal_id=row["proposal_id"]
    )


async def assignments(conn: AsyncConnection[Any], at: datetime) -> dict[str, CrewAssignment]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(ASSIGNMENTS, {"states": list(ACTIVE_STATES), "at": at})
        return {r["crew_id"]: assignment_of(r) for r in await cur.fetchall()}


async def targets(conn: AsyncConnection[Any]) -> list[CrewTarget]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(TARGETS, {"open": list(OPEN_CASE_STATES)})
        return [_target(r) for r in await cur.fetchall()]


async def subject(conn: AsyncConnection[Any], user_id: str) -> dict[str, Any]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(SUBJECT, (user_id,))
        row = await cur.fetchone()
    return subject_of(row, user_id)


def subject_sync(conn: Connection[Any], user_id: str) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(SUBJECT, (user_id,)).fetchone()
    return subject_of(row, user_id)


def subject_of(row: dict[str, Any] | None, user_id: str) -> dict[str, Any]:
    if row is None:
        return {"user_id": user_id, "roles": [], "functions": [], "can_approve": False, "on_shift": False}
    return {
        "user_id": row["user_id"],
        "roles": list(row["roles"] or []),
        "functions": list(row["functions"] or []),
        "can_approve": bool(row["can_approve"]),
        "on_shift": bool(row["on_shift"]),
    }


def targets_sync(conn: Connection[Any]) -> list[CrewTarget]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(TARGETS, {"open": list(OPEN_CASE_STATES)}).fetchall()
    return [_target(r) for r in rows]
