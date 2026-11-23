"""K3 `POST /api/admin/tokens`: scoped integration tokens, created by a platform admin.

A stepped-up session of the `platform` function creates, lists and revokes tokens; the token is shown once.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from sgw.api.deps import DbConn, State, SteppedUp, Writer
from sgw.api.errors import Forbidden
from sgw.api.sessions import AuthUser
from sgw.contracts.api_models import ApiTokenCreate, ApiTokenCreated, ApiTokenOut
from sgw.contracts.vocab import ApiScope, ApprovalFunction
from sgw.integrations import repository
from sgw.integrations.auth import Keys

router = APIRouter(tags=["admin"])


def _platform(user: AuthUser) -> AuthUser:
    if user.function is not ApprovalFunction.PLATFORM:
        raise Forbidden("only the platform function manages integration tokens", code="PLATFORM_ONLY")
    return user


def platform_admin(user: SteppedUp) -> AuthUser:
    return _platform(user)


def platform_writer(user: Writer) -> AuthUser:
    return _platform(user)


TokenAdmin = Annotated[AuthUser, Depends(platform_admin)]


@router.post("/api/admin/tokens", status_code=201, response_model=ApiTokenCreated)
async def create_api_token(
    body: ApiTokenCreate, user: TokenAdmin, conn: DbConn, state: State, keys: Keys, response: Response
) -> ApiTokenCreated:
    issued, scopes = await repository.create_token(
        conn,
        keys,
        name=body.name,
        scopes=list(body.scopes),
        expires_at=body.expires_at,
        created_by=user.user_id,
        now=state.clock.wall.now(),
        via="api",
    )
    response.headers["Cache-Control"] = "no-store"
    return ApiTokenCreated(
        token_id=issued.token_id,
        token=issued.token,
        scopes=[ApiScope(s) for s in scopes],
        expires_at=body.expires_at,
    )


@router.get("/api/admin/tokens", response_model=list[ApiTokenOut])
async def list_api_tokens(
    _: Annotated[AuthUser, Depends(platform_writer)], conn: DbConn
) -> list[ApiTokenOut]:
    return [ApiTokenOut.model_validate(vars(t)) for t in await repository.list_tokens(conn)]


@router.delete("/api/admin/tokens/{token_id}", status_code=204)
async def revoke_api_token(token_id: str, user: TokenAdmin, conn: DbConn, state: State) -> Response:
    await repository.revoke_token(
        conn, token_id, actor_id=user.user_id, now=state.clock.wall.now(), via="api"
    )
    return Response(status_code=204)
