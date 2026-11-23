"""FastAPI dependencies shared by every router (public surface for WP-09a/09b/28a/37 routers).

- `DbConn`: one pooled connection per request, committed when the handler returns, rolled back on error.
- `CurrentUser`: the session user (401 without a valid `sgw_session` cookie).
- `Writer`: `CurrentUser` plus CSRF on unsafe methods and no read-only role (403).
- `SteppedUp`: `Writer` plus a password re-entry within the last 5 minutes on this session (403
  `STEP_UP_REQUIRED`).
- `ClockOperator`: `Writer` limited to command, operations or the presenter role (scenario commands);
  `ReleasedClockOperator` the same without holding a connection through the request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from opentelemetry import trace
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from sgw.api.clock import ScenarioClock
from sgw.api.errors import Forbidden, TooManyRequests, Unauthenticated
from sgw.api.ratelimit import LoginLimiter
from sgw.api.security import CSRF_HEADER, SAFE_METHODS, SESSION_COOKIE, csrf_matches
from sgw.api.sessions import AuthUser, resolve
from sgw.api.settings import ApiSettings
from sgw.api.stream import LedgerBroadcaster
from sgw.contracts.vocab import ApprovalFunction


@dataclass
class ApiState:
    settings: ApiSettings
    pool: AsyncConnectionPool[Any]
    clock: ScenarioClock
    broadcaster: LedgerBroadcaster
    limiter: LoginLimiter


def api_state(request: Request) -> ApiState:
    state: ApiState = request.app.state.sgw
    return state


State = Annotated[ApiState, Depends(api_state)]


async def db_conn(state: State) -> AsyncIterator[AsyncConnection[Any]]:
    async with state.pool.connection() as conn:
        yield conn


DbConn = Annotated[AsyncConnection[Any], Depends(db_conn)]


def reject_cross_site(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise Forbidden("cross-site request refused", code="CROSS_SITE")


async def optional_user(request: Request, state: State, conn: DbConn) -> AuthUser | None:
    return await resolve(conn, request.cookies.get(SESSION_COOKIE), state.clock.wall.now())


async def current_user(user: Annotated[AuthUser | None, Depends(optional_user)]) -> AuthUser:
    if user is None:
        raise Unauthenticated("sign in first")
    trace.get_current_span().set_attribute("sgw.user_role", user.role)
    return user


CurrentUser = Annotated[AuthUser, Depends(current_user)]


def csrf_protect(request: Request, user: CurrentUser) -> AuthUser:
    reject_cross_site(request)
    if request.method not in SAFE_METHODS:
        token = request.cookies.get(SESSION_COOKIE, "")
        if not csrf_matches(token, request.headers.get(CSRF_HEADER)):
            raise Forbidden("missing or wrong CSRF token", code="CSRF_FAILED")
    return user


SessionWrite = Annotated[AuthUser, Depends(csrf_protect)]


def writer(user: SessionWrite) -> AuthUser:
    if user.read_only:
        raise Forbidden("this role is read-only", code="READ_ONLY_ROLE")
    return user


Writer = Annotated[AuthUser, Depends(writer)]


def stepped_up(user: Writer, state: State) -> AuthUser:
    if user.step_up_valid_until(state.clock.wall.now(), state.settings.step_up_ttl_s) is None:
        raise Forbidden("re-enter your password to continue", code="STEP_UP_REQUIRED")
    return user


SteppedUp = Annotated[AuthUser, Depends(stepped_up)]

CLOCK_FUNCTIONS = frozenset({ApprovalFunction.COMMAND, ApprovalFunction.OPERATIONS})
CLOCK_ROLES = frozenset({"presenter"})


def clock_operator(user: Writer) -> AuthUser:
    """Only command, operations and the presenter role move the scenario clock."""
    if user.function in CLOCK_FUNCTIONS or CLOCK_ROLES.intersection(user.roles):
        return user
    raise Forbidden("this role can read the scenario clock but not move it", code="SCENARIO_CONTROL_DENIED")


ClockOperator = Annotated[AuthUser, Depends(clock_operator)]


async def released_clock_operator(request: Request, state: State) -> AuthUser:
    """`ClockOperator` whose session lookup returns its connection before the handler runs, for a handler that
    replaces the database under the pool (R29 demo goto)."""
    async with state.pool.connection() as conn:
        found = await optional_user(request, state, conn)
    return clock_operator(writer(csrf_protect(request, await current_user(found))))


ReleasedClockOperator = Annotated[AuthUser, Depends(released_clock_operator)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit_login(state: ApiState, request: Request, user_id: str) -> None:
    wait = state.limiter.check(client_ip(request), user_id)
    if wait > 0:
        retry = max(1, int(wait + 0.999))
        raise TooManyRequests(
            "too many attempts; try again later",
            details={"retry_after_s": retry},
            headers={"Retry-After": str(retry)},
        )
