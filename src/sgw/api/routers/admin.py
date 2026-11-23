"""K3 admin read routes: users and roles, what each may approve, and the AI configuration.
Admin role only (the platform function or the `platform_admin` role); read-only, no step-up needed."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from sgw.api.deps import CurrentUser, DbConn, State
from sgw.api.errors import Forbidden
from sgw.api.readmodels import admin
from sgw.api.readmodels.http import cached_json, read_span
from sgw.api.sessions import AuthUser
from sgw.contracts.api_models import AiConfig, Me, UserApprovalRights
from sgw.contracts.vocab import ApprovalFunction, Classification

router = APIRouter(tags=["admin"])

ADMIN_ROLES = frozenset({"platform_admin"})


def admin_reader(user: CurrentUser) -> AuthUser:
    if user.function is ApprovalFunction.PLATFORM or ADMIN_ROLES.intersection(user.roles):
        return user
    raise Forbidden("only the platform admin reads the admin views", code="ADMIN_ONLY")


Admin = Annotated[AuthUser, Depends(admin_reader)]


@router.get("/api/admin/users", response_model=list[Me])
async def list_users(request: Request, user: Admin, conn: DbConn, state: State) -> Response:
    with read_span("admin.users", user):
        items = await admin.users(conn, state.settings.demo_mode)
    return cached_json(request, items)


@router.get("/api/admin/approval-rights", response_model=list[UserApprovalRights])
async def list_approval_rights(request: Request, user: Admin, conn: DbConn) -> Response:
    with read_span("admin.approval_rights", user):
        items = await admin.approval_rights(conn)
    return cached_json(request, items)


@router.get("/api/admin/ai-config", response_model=AiConfig)
async def get_ai_config(request: Request, user: Admin) -> Response:
    with read_span("admin.ai_config", user, Classification.C0):
        config = admin.ai_config()
    return cached_json(request, config, max_age_s=300)
