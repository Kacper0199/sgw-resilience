"""Database access for tokens, webhook subscriptions and secrets (async psycopg, caller's transaction).

Every change to a token or a subscription writes a hash-chained audit record (`sgw.api.audit_log.append`)
in the same transaction as the change, so a change without its audit record cannot commit. Audit payloads
never hold a token, a secret or a hash of one; they hold ids, scopes, URLs (host only) and the reason.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from sgw.api import audit_log
from sgw.api.errors import AppError
from sgw.contracts.api_models import WebhookDeliveryV1, WebhookSubscriptionV1
from sgw.contracts.vocab import ApiScope, WebhookDeliveryState
from sgw.integrations import signing, tokens
from sgw.integrations.keys import IntegrationKeys

Conn = AsyncConnection[Any]
MAX_SUBSCRIPTIONS_PER_TOKEN = 10
TOUCH_EVERY = timedelta(seconds=60)
SUBSCRIPTION_PREFIX = "whs_"
DELETED = "deleted"
TOKEN_REVOKED = "token_revoked"  # noqa: S105
RECEIVER_GONE = "receiver_gone"


class IntegrationError(AppError):
    status_code = 422
    code = "INVALID_REQUEST"


class NotFoundError(IntegrationError):
    status_code = 404
    code = "NOT_FOUND"


class LimitError(IntegrationError):
    status_code = 409
    code = "SUBSCRIPTION_LIMIT"


@dataclass(frozen=True)
class TokenRow:
    token_id: str
    name: str
    scopes: list[str]
    created_by: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None


async def _audit(
    conn: Conn,
    *,
    kind: str,
    actor_type: audit_log.ActorType,
    actor_id: str,
    subject: str,
    payload: dict[str, Any],
    now: datetime,
) -> None:
    await audit_log.append(
        conn,
        kind=kind,
        actor_type=actor_type,
        actor_id=actor_id,
        subject=subject,
        payload=payload,
        occurred_at=now,
    )


def _host(url: str) -> str:
    return urlsplit(url).netloc


async def ledger_head(conn: Conn) -> int:
    cur = await conn.execute("SELECT coalesce(max(ledger_seq), 0) FROM event")
    row = await cur.fetchone()
    return int(row[0]) if row else 0


async def create_token(
    conn: Conn,
    keys: IntegrationKeys,
    *,
    name: str,
    scopes: list[ApiScope],
    expires_at: datetime,
    created_by: str,
    now: datetime,
    via: str,
) -> tuple[tokens.IssuedToken, list[str]]:
    if expires_at <= now:
        raise IntegrationError("expires_at must be in the future", code="EXPIRY_IN_PAST")
    if expires_at > now + timedelta(days=366):
        raise IntegrationError("tokens live at most one year", code="EXPIRY_TOO_LONG")
    issued = tokens.new_token()
    scope_values = sorted({s.value for s in scopes})
    await conn.execute(
        "INSERT INTO api_token (token_id, name, token_hash, scopes, created_by, created_at, expires_at)"
        " VALUES (%s, %s, %s, %s::sgw_api_scope[], %s, %s, %s)",
        (
            issued.token_id,
            name,
            tokens.hash_token(keys.pepper, issued.token),
            scope_values,
            created_by,
            now,
            expires_at,
        ),
    )
    await _audit(
        conn,
        kind="api_token.created",
        actor_type="user",
        actor_id=created_by,
        subject=f"api_token:{issued.token_id}",
        payload={
            "token_id": issued.token_id,
            "name": name,
            "scopes": scope_values,
            "expires_at": expires_at.isoformat(),
            "via": via,
        },
        now=now,
    )
    return issued, scope_values


async def resolve_token(
    conn: Conn, keys: IntegrationKeys, raw: str, now: datetime
) -> tokens.TokenPrincipal | None:
    token_id = tokens.parse_token(raw)
    if token_id is None:
        return None
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT token_id, name, token_hash, scopes::text[] AS scopes, created_by, expires_at, revoked_at,"
            " last_used_at"
            " FROM api_token WHERE token_id = %s",
            (token_id,),
        )
        row = await cur.fetchone()
    presented = tokens.hash_token(keys.pepper, raw.strip())
    if row is None or not tokens.hashes_match(row["token_hash"], presented):
        return None
    if row["revoked_at"] is not None or row["expires_at"] <= now:
        return None
    last = row["last_used_at"]
    if last is None or last < now - TOUCH_EVERY:
        await conn.execute("UPDATE api_token SET last_used_at = %s WHERE token_id = %s", (now, token_id))
    return tokens.TokenPrincipal(
        token_id=token_id,
        name=row["name"],
        scopes=frozenset(ApiScope(s) for s in row["scopes"]),
        created_by=row["created_by"],
        expires_at=row["expires_at"],
    )


async def token_alive(conn: Conn, token_id: str, now: datetime) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM api_token WHERE token_id = %s AND revoked_at IS NULL AND expires_at > %s",
        (token_id, now),
    )
    return await cur.fetchone() is not None


async def list_tokens(conn: Conn) -> list[TokenRow]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT token_id, name, scopes::text[] AS scopes, created_by, created_at, expires_at, revoked_at,"
            " last_used_at"
            " FROM api_token ORDER BY created_at, token_id"
        )
        return [TokenRow(**{**r, "scopes": list(r["scopes"])}) for r in await cur.fetchall()]


async def _disable_subscriptions(
    conn: Conn, where: str, params: tuple[Any, ...], reason: str, now: datetime
) -> list[str]:
    cur = await conn.execute(
        f"UPDATE webhook_subscription SET active = false, disabled_at = %s, disabled_reason = %s"  # noqa: S608
        f" WHERE active AND {where} RETURNING subscription_id",
        (now, reason, *params),
    )
    ids = sorted(str(r[0]) for r in await cur.fetchall())
    if ids:
        await conn.execute(
            "UPDATE webhook_delivery SET state = 'disabled', next_attempt_at = NULL"
            " WHERE subscription_id = ANY(%s) AND state IN ('pending', 'retrying')",
            (ids,),
        )
    return ids


async def revoke_token(conn: Conn, token_id: str, *, actor_id: str, now: datetime, via: str) -> bool:
    cur = await conn.execute(
        "UPDATE api_token SET revoked_at = %s WHERE token_id = %s AND revoked_at IS NULL RETURNING token_id",
        (now, token_id),
    )
    if await cur.fetchone() is None:
        exists = await (
            await conn.execute("SELECT 1 FROM api_token WHERE token_id = %s", (token_id,))
        ).fetchone()
        if exists is None:
            raise NotFoundError("no such token")
        return False
    disabled = await _disable_subscriptions(conn, "token_id = %s", (token_id,), TOKEN_REVOKED, now)
    await _audit(
        conn,
        kind="api_token.revoked",
        actor_type="user",
        actor_id=actor_id,
        subject=f"api_token:{token_id}",
        payload={"token_id": token_id, "disabled_subscriptions": disabled, "via": via},
        now=now,
    )
    return True


def _subscription(row: dict[str, Any]) -> WebhookSubscriptionV1:
    return WebhookSubscriptionV1(
        subscription_id=row["subscription_id"],
        url=row["url"],
        event_types=list(row["event_types"]),
        created_at=row["created_at"],
        active=row["active"],
        secret_hint=row["secret_hint"],
    )


async def _store_secret(
    conn: Conn, keys: IntegrationKeys, subscription_id: str, slot: int, secret: str, now: datetime
) -> None:
    sealed = signing.seal(keys, subscription_id, slot, secret, now)
    await conn.execute(
        "INSERT INTO webhook_secret (subscription_id, slot, nonce, ciphertext, secret_hint, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (subscription_id, slot, sealed.nonce, sealed.ciphertext, sealed.secret_hint, now),
    )


async def create_subscription(
    conn: Conn,
    keys: IntegrationKeys,
    principal: tokens.TokenPrincipal,
    *,
    url: str,
    event_types: list[str],
    now: datetime,
) -> tuple[WebhookSubscriptionV1, str]:
    """A new subscription receives events committed after it exists (ledger head at creation)."""
    await conn.execute("SELECT 1 FROM api_token WHERE token_id = %s FOR UPDATE", (principal.token_id,))
    cur = await conn.execute(
        "SELECT count(*) FROM webhook_subscription WHERE token_id = %s AND active", (principal.token_id,)
    )
    count_row = await cur.fetchone()
    if count_row and int(count_row[0]) >= MAX_SUBSCRIPTIONS_PER_TOKEN:
        raise LimitError(f"at most {MAX_SUBSCRIPTIONS_PER_TOKEN} active subscriptions per token")
    subscription_id = f"{SUBSCRIPTION_PREFIX}{secrets.token_hex(8)}"
    types = sorted(set(event_types))
    head = await ledger_head(conn)
    secret = signing.new_secret()
    async with conn.cursor(row_factory=dict_row) as dcur:
        await dcur.execute(
            "INSERT INTO webhook_subscription (subscription_id, url, event_types, secret_ref, secret_hint,"
            " token_id, created_at, after_seq) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            " RETURNING subscription_id, url, event_types, created_at, active, secret_hint",
            (
                subscription_id,
                url,
                types,
                f"db:webhook_secret/{subscription_id}",
                signing.hint(secret),
                principal.token_id,
                now,
                head,
            ),
        )
        row = await dcur.fetchone()
    if row is None:
        raise IntegrationError("subscription was not stored", code="NOT_STORED")
    await _store_secret(conn, keys, subscription_id, 1, secret, now)
    await _audit(
        conn,
        kind="webhook_subscription.created",
        actor_type="system",
        actor_id=f"api_token:{principal.token_id}",
        subject=f"webhook_subscription:{subscription_id}",
        payload={
            "subscription_id": subscription_id,
            "host": _host(url),
            "event_types": types,
            "after_seq": head,
            "token_id": principal.token_id,
            "on_behalf_of": principal.created_by,
        },
        now=now,
    )
    return _subscription(row), secret


async def list_subscriptions(conn: Conn, token_id: str) -> list[WebhookSubscriptionV1]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT subscription_id, url, event_types, created_at, active, secret_hint"
            " FROM webhook_subscription WHERE token_id = %s AND disabled_reason IS DISTINCT FROM %s"
            " ORDER BY created_at, subscription_id",
            (token_id, DELETED),
        )
        return [_subscription(r) for r in await cur.fetchall()]


_OWNED = (
    "SELECT subscription_id, url, active, disabled_reason FROM webhook_subscription"
    " WHERE subscription_id = %s AND token_id = %s AND disabled_reason IS DISTINCT FROM %s"
)


async def _owned(conn: Conn, token_id: str, subscription_id: str, *, lock: bool = False) -> dict[str, Any]:
    async with conn.cursor(row_factory=dict_row) as cur:
        query = _OWNED + " FOR UPDATE" if lock else _OWNED
        await cur.execute(query, (subscription_id, token_id, DELETED))
        row = await cur.fetchone()
    if row is None:
        raise NotFoundError("no such subscription for this token")
    return row


async def delete_subscription(
    conn: Conn, principal: tokens.TokenPrincipal, subscription_id: str, now: datetime
) -> None:
    row = await _owned(conn, principal.token_id, subscription_id, lock=True)
    await conn.execute(
        "UPDATE webhook_subscription SET active = false, disabled_at = %s, disabled_reason = %s"
        " WHERE subscription_id = %s",
        (now, DELETED, subscription_id),
    )
    await conn.execute(
        "UPDATE webhook_delivery SET state = 'disabled', next_attempt_at = NULL"
        " WHERE subscription_id = %s AND state IN ('pending', 'retrying')",
        (subscription_id,),
    )
    await _audit(
        conn,
        kind="webhook_subscription.deleted",
        actor_type="system",
        actor_id=f"api_token:{principal.token_id}",
        subject=f"webhook_subscription:{subscription_id}",
        payload={"subscription_id": subscription_id, "host": _host(row["url"]), "was_active": row["active"]},
        now=now,
    )


async def rotate_secret(
    conn: Conn,
    keys: IntegrationKeys,
    principal: tokens.TokenPrincipal,
    subscription_id: str,
    *,
    overlap: timedelta,
    now: datetime,
) -> tuple[str, datetime]:
    """New secret in slot n+1; slot n keeps signing until now + overlap; anything older retires now."""
    if not timedelta(0) <= overlap <= signing.MAX_OVERLAP:
        raise IntegrationError("overlap must be between 0 s and 7 days", code="BAD_OVERLAP")
    await _owned(conn, principal.token_id, subscription_id, lock=True)
    cur = await conn.execute(
        "SELECT max(slot) FROM webhook_secret WHERE subscription_id = %s", (subscription_id,)
    )
    top_row = await cur.fetchone()
    top = int(top_row[0]) if top_row and top_row[0] is not None else 0
    retires = now + overlap
    await conn.execute(
        "UPDATE webhook_secret SET retires_at = %s WHERE subscription_id = %s AND slot < %s"
        " AND (retires_at IS NULL OR retires_at > %s)",
        (now, subscription_id, top, now),
    )
    await conn.execute(
        "UPDATE webhook_secret SET retires_at = %s WHERE subscription_id = %s AND slot = %s",
        (retires, subscription_id, top),
    )
    secret = signing.new_secret()
    await _store_secret(conn, keys, subscription_id, top + 1, secret, now)
    await conn.execute(
        "UPDATE webhook_subscription SET secret_hint = %s WHERE subscription_id = %s",
        (signing.hint(secret), subscription_id),
    )
    await _audit(
        conn,
        kind="webhook_subscription.secret_rotated",
        actor_type="system",
        actor_id=f"api_token:{principal.token_id}",
        subject=f"webhook_subscription:{subscription_id}",
        payload={
            "subscription_id": subscription_id,
            "new_slot": top + 1,
            "previous_retires_at": retires.isoformat(),
        },
        now=now,
    )
    return secret, retires


async def sealed_secrets(conn: Conn, subscription_id: str) -> list[signing.SealedSecret]:
    cur = await conn.execute(
        "SELECT slot, nonce, ciphertext, secret_hint, created_at, retires_at FROM webhook_secret"
        " WHERE subscription_id = %s ORDER BY slot",
        (subscription_id,),
    )
    return [
        signing.SealedSecret(int(r[0]), bytes(r[1]), bytes(r[2]), str(r[3]), r[4], r[5])
        for r in await cur.fetchall()
    ]


async def list_deliveries(
    conn: Conn, principal: tokens.TokenPrincipal, subscription_id: str, limit: int = 100
) -> list[WebhookDeliveryV1]:
    await _owned(conn, principal.token_id, subscription_id)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT delivery_id, subscription_id, event_id::text AS event_id, state, attempts, last_status"
            " FROM webhook_delivery WHERE subscription_id = %s"
            " ORDER BY created_at DESC, delivery_id LIMIT %s",
            (subscription_id, limit),
        )
        return [
            WebhookDeliveryV1(**{**r, "state": WebhookDeliveryState(r["state"])})
            for r in await cur.fetchall()
        ]


async def disable_for_gone(conn: Conn, subscription_id: str, now: datetime) -> None:
    ids = await _disable_subscriptions(conn, "subscription_id = %s", (subscription_id,), RECEIVER_GONE, now)
    if ids:
        await _audit(
            conn,
            kind="webhook_subscription.disabled",
            actor_type="system",
            actor_id="webhook-worker",
            subject=f"webhook_subscription:{subscription_id}",
            payload={"subscription_id": subscription_id, "reason": RECEIVER_GONE},
            now=now,
        )
