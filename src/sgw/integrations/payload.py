"""The webhook and SSE payload (`WebhookEventV1`) built from a ledger row, and its exact bytes.

The body is RFC 8785 canonical JSON, so every attempt of a delivery sends the same bytes and the signature
covers exactly what the receiver parses. `id` is the K2 event id (stable across subscriptions); the delivery
id (`SGW-Webhook-Id`) is derived from (subscription, event) and stays the same across retries, so receivers
de-duplicate on it.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, cast

import rfc8785

from sgw.contracts.base import json_ready
from sgw.contracts.webhooks import WebhookEventV1, WebhookType

DELIVERY_PREFIX = "whd_"


def event_v1(
    *, event_id: str, event_type: str, ledger_seq: int, event_time: datetime, payload: dict[str, Any]
) -> WebhookEventV1:
    return WebhookEventV1(
        id=event_id,
        type=cast(WebhookType, event_type),
        created_at=event_time,
        ledger_seq=ledger_seq,
        data=payload,
    )


def body_bytes(event: WebhookEventV1) -> bytes:
    return rfc8785.dumps(json_ready(event))


def delivery_id(subscription_id: str, event_id: str) -> str:
    digest = hashlib.sha256(f"{subscription_id}|{event_id}".encode()).hexdigest()
    return f"{DELIVERY_PREFIX}{digest[:32]}"
