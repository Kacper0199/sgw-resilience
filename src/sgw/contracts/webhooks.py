"""Webhook payloads and signing for the `/v1` integration namespace (WP-37 builds delivery).

Signature header: `SGW-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, f"{t}.{id}.{body}")>`,
with the delivery id in `SGW-Webhook-Id`. Receivers reject timestamps outside the tolerance window and
de-duplicate on the id, which defeats replay.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Literal

from pydantic import Field

from sgw.contracts.base import Contract, Identifier, UtcDatetime

SIGNATURE_HEADER = "SGW-Signature"
ID_HEADER = "SGW-Webhook-Id"
TOLERANCE_S = 300

WebhookType = Literal["ClockBreached", "CommitmentCreated", "CommitmentDrifted", "DecisionApproved"]


class WebhookEventV1(Contract):
    id: Identifier
    type: WebhookType
    schema_version: int = Field(default=1, ge=1)
    created_at: UtcDatetime
    ledger_seq: int = Field(ge=1)
    data: dict[str, Any]


def _mac(secret: bytes, timestamp: int, delivery_id: str, body: bytes) -> str:
    message = f"{timestamp}.{delivery_id}.".encode() + body
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def sign(secret: bytes, *, timestamp: int, delivery_id: str, body: bytes) -> str:
    return f"t={timestamp},v1={_mac(secret, timestamp, delivery_id, body)}"


def sign_rotating(secrets: list[bytes], *, timestamp: int, delivery_id: str, body: bytes) -> str:
    """During secret rotation the header carries one `v1` per active secret; receivers accept any match."""
    if not secrets:
        raise ValueError("at least one secret")
    macs = ",".join(f"v1={_mac(s, timestamp, delivery_id, body)}" for s in secrets)
    return f"t={timestamp},{macs}"


class SignatureError(ValueError):
    pass


def verify(
    secret: bytes, *, header: str, delivery_id: str, body: bytes, now: int, tolerance_s: int = TOLERANCE_S
) -> None:
    pairs = [item.strip().split("=", 1) for item in header.split(",") if "=" in item]
    stamps = [v for k, v in pairs if k == "t"]
    candidates = [v for k, v in pairs if k == "v1"]
    try:
        (raw_t,) = stamps
        timestamp = int(raw_t)
    except ValueError as exc:
        raise SignatureError("malformed signature header") from exc
    if not candidates:
        raise SignatureError("malformed signature header")
    if abs(now - timestamp) > tolerance_s:
        raise SignatureError("timestamp outside tolerance")
    expected = _mac(secret, timestamp, delivery_id, body)
    if not any(hmac.compare_digest(c, expected) for c in candidates):
        raise SignatureError("signature mismatch")
