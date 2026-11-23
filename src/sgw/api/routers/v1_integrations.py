"""K3 `/v1` integration namespace: decisions, commitments, webhook subscriptions, secret rotation,
delivery log and the `GET /v1/events` SSE subscription; bearer tokens only."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.responses import StreamingResponse

from sgw.api.deps import DbConn, State
from sgw.api.errors import Forbidden, NotFound, Unavailable, Unprocessable
from sgw.api.routers.stream import SSE_HEADERS, CountedStream
from sgw.contracts.api_models import (
    CommitmentV1,
    DecisionV1,
    WebhookDeliveryV1,
    WebhookSecretRotated,
    WebhookSubscriptionCreate,
    WebhookSubscriptionV1,
)
from sgw.contracts.vocab import ApiScope
from sgw.contracts.webhooks import WebhookType
from sgw.integrations import queries, repository
from sgw.integrations.auth import Keys, Principal, Urls, require
from sgw.integrations.keys import load_keys
from sgw.integrations.stream import IntegrationStream
from sgw.integrations.tokens import EVENT_SCOPE, TokenPrincipal
from sgw.integrations.urls import UrlRefused

SECRET_HEADER = "SGW-Webhook-Secret"  # noqa: S105
NO_STORE = {"Cache-Control": "no-store"}


@asynccontextmanager
async def integrations_lifespan(app: FastAPI) -> AsyncIterator[dict[str, Any]]:
    """Load the integration keys at start-up, so a missing or blank key stops the process before it serves."""
    if getattr(app.state, "integration_keys", None) is None:
        app.state.integration_keys = load_keys()
    yield {}


router = APIRouter(tags=["integration"], lifespan=integrations_lifespan)

DecisionsReader = Annotated[TokenPrincipal, Depends(require(ApiScope.DECISIONS_READ))]
CommitmentsReader = Annotated[TokenPrincipal, Depends(require(ApiScope.COMMITMENTS_READ))]
WebhookManager = Annotated[TokenPrincipal, Depends(require(ApiScope.WEBHOOKS_MANAGE))]


@router.get("/v1/decisions", response_model=list[DecisionV1])
async def v1_list_decisions(_: DecisionsReader, conn: DbConn) -> list[DecisionV1]:
    return await queries.list_decisions(conn)


@router.get("/v1/decisions/{decision_case_id}", response_model=DecisionV1)
async def v1_get_decision(decision_case_id: str, _: DecisionsReader, conn: DbConn) -> DecisionV1:
    found = await queries.get_decision(conn, decision_case_id)
    if found is None:
        raise NotFound("no such decision")
    return found


@router.get("/v1/commitments", response_model=list[CommitmentV1])
async def v1_list_commitments(_: CommitmentsReader, conn: DbConn) -> list[CommitmentV1]:
    return await queries.list_commitments(conn)


def _check_event_scopes(principal: TokenPrincipal, event_types: list[WebhookType] | list[str]) -> None:
    missing = principal.missing_for_events(event_types)
    if missing:
        raise Forbidden(
            "this token cannot subscribe to events outside its read scopes",
            code="SCOPE_EXCEEDED",
            details={"missing_scopes": missing},
        )


@router.post("/v1/webhooks", status_code=201, response_model=WebhookSubscriptionV1)
async def v1_create_webhook(
    body: WebhookSubscriptionCreate,
    principal: WebhookManager,
    conn: DbConn,
    state: State,
    keys: Keys,
    urls: Urls,
    response: Response,
) -> WebhookSubscriptionV1:
    _check_event_scopes(principal, body.event_types)
    try:
        urls.check(body.url)
    except UrlRefused as exc:
        raise Unprocessable(str(exc), code="URL_NOT_ALLOWED") from exc
    created, secret = await repository.create_subscription(
        conn, keys, principal, url=body.url, event_types=list(body.event_types), now=state.clock.wall.now()
    )
    response.headers[SECRET_HEADER] = secret
    response.headers.update(NO_STORE)
    return created


@router.get("/v1/webhooks", response_model=list[WebhookSubscriptionV1])
async def v1_list_webhooks(principal: WebhookManager, conn: DbConn) -> list[WebhookSubscriptionV1]:
    return await repository.list_subscriptions(conn, principal.token_id)


@router.delete("/v1/webhooks/{subscription_id}", status_code=204)
async def v1_delete_webhook(
    subscription_id: str, principal: WebhookManager, conn: DbConn, state: State
) -> Response:
    await repository.delete_subscription(conn, principal, subscription_id, state.clock.wall.now())
    return Response(status_code=204)


@router.post("/v1/webhooks/{subscription_id}/rotate-secret", response_model=WebhookSecretRotated)
async def v1_rotate_webhook_secret(
    subscription_id: str,
    principal: WebhookManager,
    conn: DbConn,
    state: State,
    keys: Keys,
    response: Response,
    overlap_s: Annotated[int, Query(ge=0, le=7 * 86_400)] = 86_400,
) -> WebhookSecretRotated:
    secret, retires = await repository.rotate_secret(
        conn,
        keys,
        principal,
        subscription_id,
        overlap=timedelta(seconds=overlap_s),
        now=state.clock.wall.now(),
    )
    response.headers.update(NO_STORE)
    return WebhookSecretRotated(
        subscription_id=subscription_id,
        secret=secret,
        secret_hint=secret[-4:],
        previous_retires_at=retires,
    )


@router.get("/v1/webhooks/{subscription_id}/deliveries", response_model=list[WebhookDeliveryV1])
async def v1_list_webhook_deliveries(
    subscription_id: str,
    principal: WebhookManager,
    conn: DbConn,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[WebhookDeliveryV1]:
    return await repository.list_deliveries(conn, principal, subscription_id, limit)


@router.get("/v1/events")
async def v1_events(
    request: Request,
    principal: Principal,
    state: State,
    types: Annotated[
        str | None, Query(description="comma-separated event types; default: all readable")
    ] = None,
) -> StreamingResponse:
    readable = principal.readable_events()
    if not readable:
        raise Forbidden("this token has no read scope for any event type", code="SCOPE_REQUIRED")
    if types:
        wanted = [t.strip() for t in types.split(",") if t.strip()]
        unknown = sorted(set(wanted) - set(EVENT_SCOPE))
        if unknown:
            raise Unprocessable(
                "unknown event types", code="UNKNOWN_EVENT_TYPE", details={"unknown": unknown}
            )
        _check_event_scopes(principal, wanted)
        selected = frozenset(wanted)
    else:
        selected = readable
    broadcaster = state.broadcaster
    if not broadcaster.try_open_stream(state.settings.max_stream_clients):
        raise Unavailable("too many open streams", code="STREAM_LIMIT")

    async def still_valid() -> bool:
        async with state.pool.connection() as conn:
            return await repository.token_alive(conn, principal.token_id, state.clock.wall.now())

    try:
        stream = IntegrationStream(
            broadcaster=broadcaster,
            event_types=selected,
            still_valid=still_valid,
            heartbeat_s=state.settings.heartbeat_s,
        )
        return CountedStream(
            broadcaster,
            stream.frames(request.headers.get("last-event-id")),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )
    except BaseException:
        broadcaster.close_stream()
        raise
