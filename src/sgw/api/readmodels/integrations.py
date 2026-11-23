"""Admin integrations view (D-087, WP-37 tables): API tokens as metadata, webhook subscriptions with
their delivery tallies, and the latest deliveries. Read-only. Never read: `token_hash`, `secret_ref`,
`webhook_secret`, the endpoint path or query (only host[:port] is shown)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from sgw.contracts.api_models import (
    AdminIntegrations,
    ApiTokenOut,
    DeliveryCounts,
    IntegrationDelivery,
    IntegrationSubscription,
)

LATEST_DELIVERIES = 50
STATUS = {"delivered": "delivered", "pending": "pending", "retrying": "pending", "failed": "failed"}
STATUS["disabled"] = "failed"

_TOKENS = """
SELECT token_id, name, scopes::text[] AS scopes, created_by, created_at, expires_at, revoked_at, last_used_at
FROM api_token ORDER BY created_at DESC, token_id
"""

_SUBSCRIPTIONS = """
SELECT s.subscription_id, s.token_id, s.url, s.event_types, s.active, s.disabled_at, s.disabled_reason,
       s.created_at,
       max(d.delivered_at) AS last_delivery_at,
       count(*) FILTER (WHERE d.state = 'delivered') AS delivered,
       count(*) FILTER (WHERE d.state IN ('pending', 'retrying')) AS pending,
       count(*) FILTER (WHERE d.state IN ('failed', 'disabled')) AS failed
FROM webhook_subscription s LEFT JOIN webhook_delivery d ON d.subscription_id = s.subscription_id
GROUP BY s.subscription_id
ORDER BY s.created_at DESC, s.subscription_id
"""

_DELIVERIES = """
SELECT d.delivery_id, d.subscription_id, e.type AS event_type, d.state::text AS state, d.attempts,
       d.last_status, d.last_error, d.created_at, d.delivered_at
FROM webhook_delivery d JOIN event e ON e.event_id = d.event_id
ORDER BY d.created_at DESC, d.delivery_id
LIMIT %s
"""


URL_PATTERN = re.compile(r"\w+://\S+")


def host_only(url: str) -> str:
    """host[:port] of a URL, never its credentials, path or query; `[url]` when nothing parses."""
    parts = urlsplit(url.lower())
    host = parts.hostname or ""
    try:
        port = parts.port
    except ValueError:
        port = None
    if not host:
        return "[url]"
    return f"{host}:{port}" if port else host


def scrub(text: str | None) -> str | None:
    """Every URL in free text (also clipped or normalised ones) reduced to its host[:port]."""
    return None if text is None else URL_PATTERN.sub(lambda m: host_only(m.group(0)), text)


async def _rows(conn: AsyncConnection[Any], sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, args)
        return list(await cur.fetchall())


async def integrations(conn: AsyncConnection[Any]) -> AdminIntegrations:
    tokens = [ApiTokenOut.model_validate(r) for r in await _rows(conn, _TOKENS)]
    subs = await _rows(conn, _SUBSCRIPTIONS)
    subscriptions = [
        IntegrationSubscription(
            subscription_id=s["subscription_id"],
            token_id=s["token_id"],
            host=host_only(str(s["url"])),
            event_types=list(s["event_types"]),
            state="active" if s["active"] and s["disabled_at"] is None else "disabled",
            disabled_reason=scrub(s["disabled_reason"]),
            created_at=s["created_at"],
            last_delivery_at=s["last_delivery_at"],
            counts=DeliveryCounts(delivered=s["delivered"], pending=s["pending"], failed=s["failed"]),
        )
        for s in subs
    ]
    deliveries = [
        IntegrationDelivery(
            delivery_id=d["delivery_id"],
            subscription_id=d["subscription_id"],
            event_type=d["event_type"],
            status=STATUS[d["state"]],  # type: ignore[arg-type]
            attempts=d["attempts"],
            last_status=d["last_status"],
            last_error=scrub(d["last_error"]),
            created_at=d["created_at"],
            delivered_at=d["delivered_at"],
        )
        for d in await _rows(conn, _DELIVERIES, (LATEST_DELIVERIES,))
    ]
    return AdminIntegrations(tokens=tokens, subscriptions=subscriptions, deliveries=deliveries)
