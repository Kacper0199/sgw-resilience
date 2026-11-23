"""K3 `getMe`: the signed-in user, step-up window and the demo-mode flag the UI banners; `getMyPermissions`:
what that user may do, from the rules the write routes enforce (`sgw.api.permissions`)."""

from __future__ import annotations

from fastapi import APIRouter

from sgw.api.deps import CurrentUser, DbConn, State
from sgw.api.permissions import permissions
from sgw.contracts.api_models import Me, Permissions

router = APIRouter(tags=["auth"])


@router.get("/api/me", response_model=Me)
async def get_me(user: CurrentUser, state: State) -> Me:
    return user.me(state.settings, state.clock.wall.now())


@router.get("/api/me/permissions", operation_id="getMyPermissions", response_model=Permissions)
async def get_my_permissions(user: CurrentUser, conn: DbConn) -> Permissions:
    return await permissions(conn, user)
