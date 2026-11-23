"""K3 `auth`: public login-page config, login (also the demo persona switch), logout, step-up."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from sgw.api import demo_hint, sessions
from sgw.api.deps import DbConn, SessionWrite, State, optional_user, rate_limit_login, reject_cross_site
from sgw.api.errors import Unauthenticated
from sgw.api.security import CSRF_COOKIE, SESSION_COOKIE, csrf_token
from sgw.api.sessions import AuthUser
from sgw.api.settings import ApiSettings
from sgw.contracts.api_models import AuthConfig, LoginRequest, Me, StepUpRequest

router = APIRouter(tags=["auth"])

CONFIG_CACHE_CONTROL = "public, max-age=60"


def set_session_cookies(response: Response, token: str, settings: ApiSettings) -> None:
    common = {
        "max_age": settings.session_ttl_s,
        "path": "/",
        "secure": settings.cookie_secure,
        "samesite": "strict",
    }
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)  # type: ignore[arg-type]
    response.set_cookie(CSRF_COOKIE, csrf_token(token), httponly=False, **common)  # type: ignore[arg-type]


def clear_session_cookies(response: Response, settings: ApiSettings) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=settings.cookie_secure, samesite="strict")


@router.get("/api/auth/config", response_model=AuthConfig, response_model_exclude_none=True)
async def auth_config(response: Response, state: State) -> AuthConfig:
    """No session needed: the login page asks whether to offer the demo persona picker, and in DEMO_MODE
    whether the public demo password is the real one (`demo_hint`). Outside DEMO_MODE only the flag."""
    response.headers["Cache-Control"] = CONFIG_CACHE_CONTROL
    if not state.settings.demo_mode:
        return AuthConfig(demo_mode=False)
    async with state.pool.connection() as conn:
        hint = await demo_hint.public_demo_password(conn)
    return AuthConfig(demo_mode=True, demo_password=hint)


@router.post("/api/auth/login", response_model=Me)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    state: State,
    conn: DbConn,
    current: Annotated[AuthUser | None, Depends(optional_user)],
) -> Me:
    reject_cross_site(request)
    rate_limit_login(state, request, body.user_id)
    now = state.clock.wall.now()
    try:
        result = await sessions.login(
            conn, state.settings, user_id=body.user_id, password=body.password, current=current, now=now
        )
    except Unauthenticated:
        await conn.commit()
        raise
    await conn.commit()
    set_session_cookies(response, result.token, state.settings)
    if result.switched_from:
        response.headers["X-SGW-Persona-Switched-From"] = result.switched_from
    return result.user.me(state.settings, now)


@router.post("/api/auth/logout", status_code=204)
async def logout(user: SessionWrite, state: State, conn: DbConn) -> Response:
    await sessions.logout(conn, user, state.clock.wall.now())
    await conn.commit()
    response = Response(status_code=204)
    clear_session_cookies(response, state.settings)
    return response


@router.post("/api/auth/step-up", response_model=Me)
async def step_up(
    body: StepUpRequest, request: Request, user: SessionWrite, state: State, conn: DbConn
) -> Me:
    rate_limit_login(state, request, user.user_id)
    now = state.clock.wall.now()
    try:
        refreshed = await sessions.step_up(conn, user, body.password, now)
    except Unauthenticated:
        await conn.commit()
        raise
    await conn.commit()
    return refreshed.me(state.settings, now)
