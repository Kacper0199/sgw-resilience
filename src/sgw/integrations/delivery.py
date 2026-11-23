"""Webhook delivery worker: claim due deliveries, sign, POST, record the attempt, back off or dead-letter.

Claiming takes due rows with `FOR UPDATE SKIP LOCKED` and pushes `next_attempt_at` forward by a lease in the
same short transaction, so several workers never send one delivery at once and a crashed worker's claims
come back after the lease (at-least-once; receivers de-duplicate on `SGW-Webhook-Id`). The HTTP call runs
outside any transaction. Each attempt signs the same body with a fresh timestamp and every active secret,
re-checks the target and connects to the address it checked, on a fresh client: a pooled connection is
never reused for another hostname that happens to share the address.

Outcomes: 2xx -> `delivered`; 410 -> the subscription is disabled (`receiver_gone`, audited); anything else
(network error, timeout, 3xx since redirects are not followed, 4xx, 5xx) -> `retrying` with backoff, then
`failed` (dead letter) after `RetryPolicy.max_attempts`. A target that no longer passes the URL policy (DNS
now points inward) counts as a failed attempt without a request.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
from opentelemetry import trace
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from sgw.contracts.webhooks import ID_HEADER, SIGNATURE_HEADER, sign_rotating
from sgw.integrations import backoff, repository, signing
from sgw.integrations.keys import IntegrationKeys
from sgw.integrations.payload import body_bytes, event_v1
from sgw.integrations.urls import PinnedTarget, UrlPolicy, UrlRefused

log = logging.getLogger("sgw.integrations.delivery")

ATTEMPT_HEADER = "SGW-Webhook-Attempt"
USER_AGENT = "SGW-Webhooks/1"
LEASE = timedelta(seconds=60)
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
ERROR_MAX = 300


@dataclass(frozen=True)
class Claim:
    delivery_id: str
    subscription_id: str
    url: str
    attempts: int
    event_id: str
    event_type: str
    ledger_seq: int
    event_time: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class AttemptResult:
    status: int | None
    error: str | None
    duration_ms: int
    retry_after_s: float | None = None


async def claim_due(conn: AsyncConnection[Any], now: datetime, limit: int = 20) -> list[Claim]:
    async with conn.transaction():
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT d.delivery_id, d.subscription_id, s.url, d.attempts, e.event_id::text AS event_id,"
                " e.type AS event_type, e.ledger_seq, e.event_time, e.payload"
                " FROM webhook_delivery d JOIN webhook_subscription s USING (subscription_id)"
                " JOIN event e ON e.event_id = d.event_id"
                " WHERE d.state IN ('pending', 'retrying') AND s.active"
                " AND (d.next_attempt_at IS NULL OR d.next_attempt_at <= %s)"
                " ORDER BY d.next_attempt_at NULLS FIRST, e.ledger_seq LIMIT %s FOR UPDATE OF d SKIP LOCKED",
                (now, limit),
            )
            rows = await cur.fetchall()
        if rows:
            await conn.execute(
                "UPDATE webhook_delivery SET next_attempt_at = %s WHERE delivery_id = ANY(%s)",
                (now + LEASE, [r["delivery_id"] for r in rows]),
            )
    return [Claim(**r) for r in rows]


def _clip(text: str) -> str:
    return text if len(text) <= ERROR_MAX else text[: ERROR_MAX - 1] + "…"


ClientFactory = Callable[[], httpx.AsyncClient]


def pinned_request(
    client: httpx.AsyncClient, url: str, target: PinnedTarget, *, content: bytes, headers: dict[str, str]
) -> httpx.Request:
    """A POST that connects to `target.address` while Host, TLS SNI and certificate checks use the hostname.

    httpx takes the TCP destination from the URL and the TLS server name from the `sni_hostname` extension,
    and the Host header is fixed when the request is built, so rewriting only the URL host pins the address
    without weakening certificate verification.
    """
    request = client.build_request("POST", url, content=content, headers=headers)
    request.url = request.url.copy_with(host=target.address)
    request.extensions = {**request.extensions, "sni_hostname": target.host}
    return request


async def send(
    connect: ClientFactory,
    claim: Claim,
    secrets: list[bytes],
    *,
    unix_now: int,
    url_policy: UrlPolicy,
    monotonic: Callable[[], float] = time.monotonic,
) -> AttemptResult:
    started = monotonic()
    try:
        target = url_policy.vet(claim.url)
    except UrlRefused as exc:
        return AttemptResult(None, _clip(f"url refused: {exc}"), 0)
    if not secrets:
        return AttemptResult(None, "no active signing secret", 0)
    event = event_v1(
        event_id=claim.event_id,
        event_type=claim.event_type,
        ledger_seq=claim.ledger_seq,
        event_time=claim.event_time,
        payload=claim.payload,
    )
    body = body_bytes(event)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        ID_HEADER: claim.delivery_id,
        SIGNATURE_HEADER: sign_rotating(
            secrets, timestamp=unix_now, delivery_id=claim.delivery_id, body=body
        ),
        ATTEMPT_HEADER: str(claim.attempts + 1),
    }
    try:
        async with connect() as client:
            request = pinned_request(client, claim.url, target, content=body, headers=headers)
            response = await client.send(request, follow_redirects=False)
    except httpx.HTTPError as exc:
        elapsed = int((monotonic() - started) * 1000)
        return AttemptResult(None, _clip(f"{type(exc).__name__}: {exc}"), elapsed)
    elapsed = int((monotonic() - started) * 1000)
    return AttemptResult(
        response.status_code,
        None if response.is_success else f"HTTP {response.status_code}",
        elapsed,
        backoff.parse_retry_after(response.headers.get("retry-after")),
    )


async def record(
    conn: AsyncConnection[Any],
    claim: Claim,
    result: AttemptResult,
    policy: backoff.RetryPolicy,
    now: datetime,
) -> str:
    attempt = claim.attempts + 1
    verdict = backoff.outcome(result.status) if result.status is not None else "retry"
    async with conn.transaction():
        await conn.execute(
            "INSERT INTO webhook_attempt (delivery_id, attempt, attempted_at, status, error, duration_ms)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (claim.delivery_id, attempt, now, result.status, result.error, result.duration_ms),
        )
        if verdict == "delivered":
            state, next_at = "delivered", None
        elif verdict == "gone":
            state, next_at = "disabled", None
        elif policy.exhausted(attempt):
            state, next_at = "failed", None
        else:
            state = "retrying"
            next_at = now + timedelta(seconds=policy.delay_s(attempt, result.retry_after_s))
        await conn.execute(
            "UPDATE webhook_delivery SET state = %s, attempts = %s, next_attempt_at = %s, last_status = %s,"
            " last_error = %s, signed_at = %s, delivered_at = CASE WHEN %s THEN %s END"
            " WHERE delivery_id = %s",
            (
                state,
                attempt,
                next_at,
                result.status,
                result.error,
                now,
                state == "delivered",
                now,
                claim.delivery_id,
            ),
        )
        if verdict == "gone":
            await repository.disable_for_gone(conn, claim.subscription_id, now)
    if state == "failed":
        log.warning("webhook delivery %s dead-lettered after %d attempts", claim.delivery_id, attempt)
    return state


@dataclass
class DeliveryWorker:
    """`conn` must be in autocommit mode; each step opens its own short transaction."""

    conn: AsyncConnection[Any]
    connect: ClientFactory
    keys: IntegrationKeys
    policy: backoff.RetryPolicy
    url_policy: UrlPolicy
    now: Callable[[], datetime]

    async def run_once(self, limit: int = 20) -> dict[str, int]:
        """Claim and attempt every due delivery once; returns counts per resulting state."""
        tracer = trace.get_tracer("sgw")
        counts: dict[str, int] = {}
        with tracer.start_as_current_span("integrations.webhooks.deliver") as span:
            claims = await claim_due(self.conn, self.now(), limit)
            for claim in claims:
                current = self.now()
                sealed = await repository.sealed_secrets(self.conn, claim.subscription_id)
                keys = signing.signing_keys(self.keys, claim.subscription_id, sealed, current)
                result = await send(
                    self.connect, claim, keys, unix_now=int(current.timestamp()), url_policy=self.url_policy
                )
                state = await record(self.conn, claim, result, self.policy, self.now())
                counts[state] = counts.get(state, 0) + 1
            span.set_attribute("sgw.webhooks.claimed", len(claims))
        return counts


async def replay_dead_letter(
    conn: AsyncConnection[Any], delivery_id: str, *, actor_id: str, now: datetime
) -> bool:
    """Operator action: one more attempt for a dead-lettered delivery (audited); fails again if it fails."""
    async with conn.transaction():
        cur = await conn.execute(
            "UPDATE webhook_delivery d SET state = 'retrying', next_attempt_at = %s"
            " FROM webhook_subscription s WHERE d.delivery_id = %s AND d.state = 'failed'"
            " AND s.subscription_id = d.subscription_id AND s.active RETURNING d.subscription_id",
            (now, delivery_id),
        )
        row = await cur.fetchone()
        if row is None:
            return False
        from sgw.api import audit_log

        await audit_log.append(
            conn,
            kind="webhook_delivery.replayed",
            actor_type="user",
            actor_id=actor_id,
            subject=f"webhook_delivery:{delivery_id}",
            payload={"delivery_id": delivery_id, "subscription_id": str(row[0])},
            occurred_at=now,
        )
    return True
