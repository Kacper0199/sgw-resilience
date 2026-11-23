"""Read side of the WP-22 readiness cases for K3 `/api/readiness`.

The cases and their K16 rule-deadline clocks come from `data/fixtures/bluesky/readiness_cases.json`
(through WP-12 `compute_queue`); the state of each case's work order comes from the same fixture's EAM feed
(`eam.jsonl`, the latest event known at the scenario time). An open work order is a gap, a completed one is
ready, no work order is unknown. `due_utc` is the effective decide-by (critical path included). A result the
check's owner recorded (`readiness_result`) overrides the work order: ready, not ready (a gap) or
waived, recorded at the same pre-season review.

Owner function per work type (assumption P-BEUI2b-03, from the SOP family the lead time cites in
`src/sgw/models/clocks/lead_times.yaml`: SOP-WTR to water operations, SOP-ELE-7 vegetation to operations,
SOP-ELE-2 staging and mutual aid to logistics, the fuel contract to logistics).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any, Literal

from psycopg import AsyncConnection

from sgw.contracts.api_models import Provenance, ReadinessItem, ReadinessResult
from sgw.contracts.vocab import ApprovalFunction, Domain, NumberLabel

REPO = Path(__file__).resolve().parents[4]
FIXTURE_DIR = REPO / "data" / "fixtures" / "bluesky"
CASES_SOURCE = "data/fixtures/bluesky/readiness_cases.json"
OWNER_BY_WORK_TYPE: dict[str, ApprovalFunction] = {
    "generator_load_test": ApprovalFunction.WATER_OPERATIONS,
    "fuel_contract_top_up": ApprovalFunction.LOGISTICS,
    "vegetation_clearance": ApprovalFunction.OPERATIONS,
    "staging_site_lease": ApprovalFunction.LOGISTICS,
    "mutual_aid_mou": ApprovalFunction.LOGISTICS,
    "water_tanker_standby": ApprovalFunction.WATER_OPERATIONS,
}
RESULT_STATUS: dict[str, Literal["ready", "gap", "waived"]] = {
    "ready": "ready",
    "not_ready": "gap",
    "waived": "waived",
}
READY_STATES = frozenset({"completed", "closed", "done"})
GAP_STATES = frozenset({"open", "in_progress", "scheduled", "assigned"})


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


@cache
def cases() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURE_DIR / "readiness_cases.json").read_text(encoding="utf-8"))
    return data


@cache
def work_orders() -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    with (FIXTURE_DIR / "eam.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            event = json.loads(line)
            if event.get("type") == "WorkOrder":
                rows.append(event)
    return tuple(rows)


def _work_order_status(case_id: str, at: datetime) -> str | None:
    key = f"wo-{case_id}"
    known = [
        e for e in work_orders() if str(e.get("dedup_key", "")).endswith(key) and _utc(e["known_at"]) <= at
    ]
    if not known:
        return None
    return str(max(known, key=lambda e: e["known_at"])["payload"]["status"])


def _status(wo: str | None) -> Literal["ready", "gap", "unknown"]:
    if wo in READY_STATES:
        return "ready"
    if wo in GAP_STATES:
        return "gap"
    return "unknown"


def review_time() -> datetime:
    """The pre-season review the readiness cases were built for."""
    return _utc(cases()["scenario_now_utc"])


def readiness() -> list[ReadinessItem]:
    """Every check as it stood at the pre-season review, whatever the replay clock says: the checks belong to
    May, the storm to September, and counting one against the other made them '160 d overdue'."""
    at = review_time()
    out: list[ReadinessItem] = []
    for c in sorted(cases()["cases"], key=lambda c: (c["priority"], c["case"]["decision_case_id"])):
        case = c["case"]
        out.append(
            ReadinessItem(
                item_id=case["decision_case_id"],
                title=case["title"],
                domain=Domain(case["domain"]),
                status=_status(_work_order_status(case["decision_case_id"], at)),
                owner_function=OWNER_BY_WORK_TYPE[c["work_type"]],
                due_utc=_utc(case["effective_decide_by_utc"]),
                evaluated_at_utc=at,
            )
        )
    return out


async def latest_results(conn: AsyncConnection[Any]) -> dict[str, ReadinessResult]:
    cur = await conn.execute(
        "SELECT DISTINCT ON (item_id) item_id, status, note, evidence_url, recorded_by, recorded_at,"
        " reviewed_at FROM readiness_result ORDER BY item_id, result_id DESC"
    )
    return {
        str(row[0]): ReadinessResult(
            status=row[1],
            note=row[2],
            evidence_url=row[3],
            recorded_by=row[4],
            recorded_at_utc=row[5].astimezone(UTC),
            reviewed_at_utc=row[6].astimezone(UTC),
        )
        for row in await cur.fetchall()
    }


def with_results(items: list[ReadinessItem], results: dict[str, ReadinessResult]) -> list[ReadinessItem]:
    out: list[ReadinessItem] = []
    for item in items:
        result = results.get(item.item_id)
        out.append(
            item
            if result is None
            else item.model_copy(update={"status": RESULT_STATUS[result.status], "result": result})
        )
    return out


async def current(conn: AsyncConnection[Any]) -> list[ReadinessItem]:
    """The checks with the owners' recorded results applied."""
    return with_results(readiness(), await latest_results(conn))


def provenance() -> Provenance:
    return Provenance(
        source=CASES_SOURCE,
        rule_id="rule.readiness.hurricane_season_start",
        as_of=review_time(),
        label=NumberLabel.A,
    )
