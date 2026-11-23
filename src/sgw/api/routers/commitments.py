"""K3 `/api/commitments`: approved decisions as commitments, their milestones and drift log.

Read-only for any signed-in user; the commitment watch writes them (`sgw.models.commitments.service`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from sgw.api.deps import CurrentUser, DbConn
from sgw.api.errors import NotFound
from sgw.contracts.api_models import CommitmentDetail, CommitmentMilestone, CommitmentSummary
from sgw.contracts.vocab import CommitmentState
from sgw.models.commitments import read

router = APIRouter(tags=["decisions"])


@router.get("/api/commitments", response_model=list[CommitmentSummary])
async def list_commitments(
    _: CurrentUser, conn: DbConn, state: Annotated[CommitmentState | None, Query()] = None
) -> list[CommitmentSummary]:
    return await read.list_commitments(conn, state.value if state else None)


@router.get("/api/commitments/{commitment_id}", response_model=CommitmentDetail)
async def get_commitment(commitment_id: str, _: CurrentUser, conn: DbConn) -> CommitmentDetail:
    found = await read.detail(conn, commitment_id)
    if found is None:
        raise NotFound("no such commitment")
    return found


@router.get("/api/commitments/{commitment_id}/milestones", response_model=list[CommitmentMilestone])
async def list_commitment_milestones(
    commitment_id: str, _: CurrentUser, conn: DbConn
) -> list[CommitmentMilestone]:
    found = await read.milestones(conn, commitment_id)
    if found is None:
        raise NotFound("no such commitment")
    return found
