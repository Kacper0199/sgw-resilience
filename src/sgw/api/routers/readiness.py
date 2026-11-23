"""K3 `/api/readiness`: the pre-season readiness items with their status at the pre-season
review and the effective decide-by as due date (`sgw.api.readmodels.readiness`). C1.

`POST /api/readiness/{item_id}` lets the check's owner function record its result (ready, not ready
or waived, with a note and an optional evidence link). The result stands at the pre-season review the checks
are judged at, not at the replay clock, and is recorded in the audit chain (`readiness_recorded`)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from sgw.api import audit_log
from sgw.api.deps import CurrentUser, DbConn, Writer
from sgw.api.errors import Forbidden, NotFound
from sgw.api.readmodels import readiness
from sgw.api.readmodels.http import cached_json, provenance_header, read_span
from sgw.contracts.api_models import ReadinessItem, ReadinessRecord

router = APIRouter(tags=["decisions"])


@router.get("/api/readiness", response_model=list[ReadinessItem])
async def list_readiness(request: Request, user: CurrentUser, conn: DbConn) -> Response:
    with read_span("readiness", user):
        items = await readiness.current(conn)
    return cached_json(request, items, max_age_s=0, headers=provenance_header(readiness.provenance()))


@router.post("/api/readiness/{item_id}", operation_id="recordReadiness", response_model=ReadinessItem)
async def record_readiness(item_id: str, body: ReadinessRecord, user: Writer, conn: DbConn) -> ReadinessItem:
    item = next((i for i in await readiness.current(conn) if i.item_id == item_id), None)
    if item is None:
        raise NotFound("readiness check not found", code="READINESS_NOT_FOUND")
    if user.function is not item.owner_function:
        raise Forbidden(f"only {item.owner_function.value} records this check", code="READINESS_NOT_OWNER")
    reviewed = readiness.review_time()
    await conn.execute(
        "INSERT INTO readiness_result (item_id, status, note, evidence_url, owner_function, recorded_by,"
        " reviewed_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            item_id,
            body.status,
            body.note,
            body.evidence_url,
            item.owner_function.value,
            user.user_id,
            reviewed,
        ),
    )
    await audit_log.append(
        conn,
        kind="readiness_recorded",
        actor_type="user",
        actor_id=user.user_id,
        subject=f"readiness:{item_id}",
        payload={
            "item_id": item_id,
            "status": body.status,
            "note": body.note,
            "evidence_url": body.evidence_url,
            "function": user.function.value,
            "from": item.status,
        },
        occurred_at=reviewed,
    )
    return next(i for i in await readiness.current(conn) if i.item_id == item_id)
