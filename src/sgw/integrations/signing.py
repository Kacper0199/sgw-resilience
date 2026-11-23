"""Webhook signing secrets: generation, sealing at rest, and the two-secret rotation window.

A secret is `whsec_<43 url-safe chars>`; its UTF-8 bytes are the HMAC key (the receiver uses the string as
given). Secrets are sealed with AES-256-GCM (key from `keys`, associated data `<subscription_id>:<slot>` so a
ciphertext cannot be moved to another subscription). Rotation adds slot n+1 and sets `retires_at` on slot n
to now + overlap, so for the overlap both secrets sign (`SGW-Signature: t=…,v1=<new>,v1=<old>`) and the
receiver can switch at its own pace. At most two secrets are ever active.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sgw.integrations.keys import IntegrationKeys

SECRET_PREFIX = "whsec_"  # noqa: S105
DEFAULT_OVERLAP = timedelta(hours=24)
MAX_OVERLAP = timedelta(days=7)
MAX_ACTIVE = 2


def new_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def hint(secret: str) -> str:
    return secret[-4:]


def aad(subscription_id: str, slot: int) -> bytes:
    return f"{subscription_id}:{slot}".encode()


@dataclass(frozen=True)
class SealedSecret:
    slot: int
    nonce: bytes
    ciphertext: bytes
    secret_hint: str
    created_at: datetime
    retires_at: datetime | None

    def active(self, now: datetime) -> bool:
        return self.retires_at is None or self.retires_at > now


def seal(keys: IntegrationKeys, subscription_id: str, slot: int, secret: str, now: datetime) -> SealedSecret:
    nonce, ciphertext = keys.seal(secret.encode(), aad(subscription_id, slot))
    return SealedSecret(slot, nonce, ciphertext, hint(secret), now, None)


def unseal(keys: IntegrationKeys, subscription_id: str, sealed: SealedSecret) -> bytes:
    return keys.open(sealed.nonce, sealed.ciphertext, aad(subscription_id, sealed.slot))


def signing_keys(
    keys: IntegrationKeys, subscription_id: str, sealed: list[SealedSecret], now: datetime
) -> list[bytes]:
    """Active secrets, newest first, at most two."""
    active = sorted((s for s in sealed if s.active(now)), key=lambda s: s.slot, reverse=True)[:MAX_ACTIVE]
    return [unseal(keys, subscription_id, s) for s in active]
