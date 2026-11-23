"""Bearer-token authentication and scope checks for `/v1` (FastAPI dependencies).

`Authorization: Bearer sgwi_…` only; session cookies do not authenticate `/v1`, and tokens do not
authenticate `/api` (so no token can reach approval routes). Unknown, malformed, revoked and expired tokens
all answer the same 401 with `WWW-Authenticate: Bearer`. Each token has a request budget (token bucket,
429 with `Retry-After`).
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request
from opentelemetry import trace

from sgw.api.deps import DbConn, State
from sgw.api.errors import Forbidden, TooManyRequests, Unauthenticated
from sgw.api.ratelimit import TokenBuckets
from sgw.contracts.vocab import ApiScope
from sgw.integrations import repository
from sgw.integrations.keys import IntegrationKeys, load_keys
from sgw.integrations.tokens import TokenPrincipal
from sgw.integrations.urls import UrlPolicy

BURST = 120
PER_S = 10.0
_CHALLENGE = {"WWW-Authenticate": 'Bearer realm="sgw-v1"'}


def integration_keys(request: Request) -> IntegrationKeys:
    keys = getattr(request.app.state, "integration_keys", None)
    if keys is None:
        keys = load_keys()
        request.app.state.integration_keys = keys
    return keys


def url_policy(request: Request) -> UrlPolicy:
    policy = getattr(request.app.state, "integration_url_policy", None)
    if policy is None:
        policy = UrlPolicy.from_env()
        request.app.state.integration_url_policy = policy
    return policy


def _limiter(request: Request) -> TokenBuckets:
    limiter = getattr(request.app.state, "integration_limiter", None)
    if limiter is None:
        limiter = TokenBuckets(BURST, PER_S)
        request.app.state.integration_limiter = limiter
    return limiter


Keys = Annotated[IntegrationKeys, Depends(integration_keys)]
Urls = Annotated[UrlPolicy, Depends(url_policy)]


def bearer(request: Request) -> str:
    raw = request.headers.get("authorization", "")
    scheme, _, value = raw.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise Unauthenticated("an API token is required", code="TOKEN_REQUIRED", headers=_CHALLENGE)
    return value.strip()


async def token_principal(request: Request, state: State, conn: DbConn, keys: Keys) -> TokenPrincipal:
    raw = bearer(request)
    principal = await repository.resolve_token(conn, keys, raw, state.clock.wall.now())
    if principal is None:
        await conn.commit()
        raise Unauthenticated(
            "invalid, expired or revoked API token", code="TOKEN_INVALID", headers=_CHALLENGE
        )
    wait = _limiter(request).take(principal.token_id)
    if wait > 0:
        retry = max(1, int(wait + 0.999))
        raise TooManyRequests(
            "token request budget spent",
            details={"retry_after_s": retry},
            headers={"Retry-After": str(retry)},
        )
    span = trace.get_current_span()
    span.set_attribute("sgw.user_role", "api_token")
    span.set_attribute("sgw.api_token_id", principal.token_id)
    return principal


Principal = Annotated[TokenPrincipal, Depends(token_principal)]


def require(scope: ApiScope) -> Callable[[TokenPrincipal], Coroutine[Any, Any, TokenPrincipal]]:
    async def check(principal: Principal) -> TokenPrincipal:
        if not principal.has(scope):
            raise Forbidden(f"this token lacks the {scope.value} scope", code="SCOPE_REQUIRED")
        return principal

    return check
