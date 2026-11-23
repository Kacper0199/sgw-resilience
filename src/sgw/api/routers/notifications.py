"""K3 notification routes: the signed-in person's feed (`sgw.api.readmodels.notifications`) and their read
marks. Marking items read needs a session and CSRF but no write role: read marks are the person's own state,
so the read-only auditor may clear their feed too."""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends

from sgw.api.deps import CurrentUser, SessionWrite, State
from sgw.api.readmodels import notifications as feed
from sgw.api.readmodels.http import read_span
from sgw.api.routers._scenario import scenario_name
from sgw.api.sessions import AuthUser
from sgw.approval.deps import approval_service, db_conn
from sgw.approval.service import ApprovalService
from sgw.contracts.api_models import Notification, NotificationFeed, NotificationRead, SurgeReport
from sgw.models.surge.read import SurgeUnavailable, list_outage_surges
from sgw.scenarios import packs

router = APIRouter(tags=["auth"])

Conn = Annotated[psycopg.Connection[Any], Depends(db_conn)]
Service = Annotated[ApprovalService, Depends(approval_service)]


def _surges(state: State) -> SurgeReport | None:
    if packs.is_pack(scenario_name(state)):
        return None
    try:
        return list_outage_surges(state.clock.now(), scenario=scenario_name(state))
    except SurgeUnavailable:
        return None


def _items(user: AuthUser, state: State, conn: Conn, service: Service) -> list[Notification]:
    scenario = scenario_name(state)
    summaries = packs.visible(scenario, service.summaries(conn), lambda p: p.proposal_id)
    audit = feed.audit_rows(conn)
    pack = packs.get(scenario)
    if pack is not None:
        audit = [r for r in audit if pack.owns_audit(r.subject, r.payload)]
    return feed.build(
        user,
        summaries,
        audit,
        _surges(state),
        state.clock.now(),
        state.clock.wall.now(),
        water_cases=feed.water_case_ids(conn),
    )


@router.get("/api/notifications", operation_id="listNotifications", response_model=NotificationFeed)
def list_notifications(user: CurrentUser, state: State, conn: Conn, service: Service) -> NotificationFeed:
    with read_span("notifications", user):
        return feed.with_read_marks(conn, user.user_id, _items(user, state, conn, service))


@router.post("/api/notifications/read", operation_id="markNotificationsRead", response_model=NotificationFeed)
def mark_notifications_read(
    body: NotificationRead, user: SessionWrite, state: State, conn: Conn, service: Service
) -> NotificationFeed:
    items = _items(user, state, conn, service)
    known = {i.notification_id for i in items}
    feed.mark_read(conn, user.user_id, known if body.all else known.intersection(body.ids))
    return feed.with_read_marks(conn, user.user_id, items)
