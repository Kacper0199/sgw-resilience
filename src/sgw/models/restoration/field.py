"""Field state from the ledger for the API: open outages (OMS `OutageEvent`) and crew status (FSM
`CrewStatus`) as known at a scenario time. The latest event per outage or crew wins (ledger order); only
C0/C1 events are read, and nothing known after the scenario time."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from sgw.contracts.api_models import CrewItem, OutageItem, Provenance
from sgw.contracts.vocab import BlockReason, CrewStatus, NumberLabel
from sgw.dispatch import read as dispatch_read

PUBLIC_CLASSES = ("C0", "C1")
MAX_ROWS = 1000
REPLAY_LABEL = "S (synthetic Helene replay)"

_OUTAGES = """
WITH seen AS (
    SELECT payload, event_time, scenario_known_at, ledger_seq, source_id
    FROM event
    WHERE type = 'OutageEvent' AND scenario_known_at <= %(at)s AND classification::text = ANY(%(classes)s)
), latest AS (
    SELECT DISTINCT ON (payload->>'outage_id') payload, scenario_known_at, source_id
    FROM seen ORDER BY payload->>'outage_id', ledger_seq DESC
), started AS (
    SELECT payload->>'outage_id' AS outage_id, min(event_time) AS started_at FROM seen GROUP BY 1
)
SELECT l.payload, l.scenario_known_at, l.source_id, s.started_at
FROM latest l JOIN started s ON s.outage_id = l.payload->>'outage_id'
WHERE l.payload->>'status' <> 'restored'
ORDER BY (l.payload->>'customers_out')::int DESC, l.payload->>'outage_id'
LIMIT %(limit)s
"""

_CREWS = """
WITH latest AS (
    SELECT DISTINCT ON (payload->>'crew_id') payload, scenario_known_at, source_id, region_id
    FROM event
    WHERE type = 'CrewStatus' AND scenario_known_at <= %(at)s AND classification::text = ANY(%(classes)s)
    ORDER BY payload->>'crew_id', ledger_seq DESC
)
SELECT coalesce(l.payload->>'crew_id', c.crew_id) AS crew_id,
       coalesce(l.payload->>'status', c.status::text) AS status,
       l.payload->>'location_id' AS location_id, l.payload->>'block_reason' AS block_reason,
       coalesce((l.payload->>'headcount')::int, c.headcount) AS headcount,
       c.shift_end, l.scenario_known_at, l.source_id, coalesce(l.region_id, c.region_id) AS region_id
FROM latest l FULL JOIN crew c ON c.crew_id = l.payload->>'crew_id'
ORDER BY 1
LIMIT %(limit)s
"""


async def open_outages(conn: AsyncConnection[Any], at: datetime) -> list[OutageItem]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_OUTAGES, {"at": at, "classes": list(PUBLIC_CLASSES), "limit": MAX_ROWS})
        rows = await cur.fetchall()
    return [
        OutageItem(
            outage_id=r["payload"]["outage_id"],
            feeder_id=r["payload"]["feeder_id"],
            customers_out=int(r["payload"]["customers_out"]),
            started_at=r["started_at"],
            critical_facility_ids=list(r["payload"].get("critical_facility_ids") or []),
            provenance=Provenance(
                source=r["source_id"], as_of=r["scenario_known_at"], label=NumberLabel.S, detail=REPLAY_LABEL
            ),
        )
        for r in rows
    ]


def _block_reason(value: str | None) -> BlockReason | None:
    return BlockReason(value) if value is not None and value in BlockReason._value2member_map_ else None


async def crews(conn: AsyncConnection[Any], at: datetime, status: CrewStatus | None = None) -> list[CrewItem]:
    """Crews as known at `at`, each with its open dispatch assignment and, when blocked, the reason."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_CREWS, {"at": at, "classes": list(PUBLIC_CLASSES), "limit": MAX_ROWS})
        rows = await cur.fetchall()
    assigned = await dispatch_read.assignments(conn, at)
    out = [
        CrewItem(
            crew_id=r["crew_id"],
            status=CrewStatus(r["status"]),
            location_id=r["location_id"],
            headcount=int(r["headcount"] or 0),
            shift_end=r["shift_end"],
            region_id=r["region_id"],
            assignment=assigned.get(r["crew_id"]),
            block_reason=_block_reason(r["block_reason"]) if r["status"] == "blocked" else None,
            provenance=Provenance(
                source=r["source_id"] or "crew",
                as_of=r["scenario_known_at"],
                label=NumberLabel.S,
                detail=REPLAY_LABEL,
            ),
        )
        for r in rows
    ]
    return [c for c in out if status is None or c.status is status]
