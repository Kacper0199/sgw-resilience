"""Scoped API tokens: format, hashing and scope rules (pure; storage is in `repository`).

Format: `sgwi_<token_id>_<64 hex>`, e.g. `sgwi_itk3f9c0a1b2d4e_…`. The fixed `sgwi_` prefix lets secret
scanners recognise a leaked token, and the embedded token id lets the server find the row and the operator
name the token without the secret. Only HMAC-SHA256(pepper, token) is stored (`api_token.token_hash`).

Scopes are least privilege. There is no write scope for decisions: a token can read decisions, clocks and
commitments and manage its own webhook subscriptions, never approve (approval needs a stepped-up session).
Each webhook event type needs the read scope of its domain, for webhooks and for the SSE subscription.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime

from sgw.contracts.vocab import ApiScope
from sgw.contracts.webhooks import WebhookType

PREFIX = "sgwi"
_ID_HEX = 12
_SECRET_HEX = 64
TOKEN_RE = re.compile(rf"^{PREFIX}_(itk[0-9a-f]{{{_ID_HEX}}})_([0-9a-f]{{{_SECRET_HEX}}})$")

EVENT_SCOPE: dict[str, ApiScope] = {
    "DecisionApproved": ApiScope.DECISIONS_READ,
    "ClockBreached": ApiScope.CLOCKS_READ,
    "CommitmentCreated": ApiScope.COMMITMENTS_READ,
    "CommitmentDrifted": ApiScope.COMMITMENTS_READ,
}


@dataclass(frozen=True)
class IssuedToken:
    token_id: str
    token: str


def new_token() -> IssuedToken:
    token_id = f"itk{secrets.token_hex(_ID_HEX // 2)}"
    return IssuedToken(token_id=token_id, token=f"{PREFIX}_{token_id}_{secrets.token_hex(_SECRET_HEX // 2)}")


def parse_token(raw: str) -> str | None:
    """The token id when `raw` is well formed, else None (never raises on attacker input)."""
    match = TOKEN_RE.match(raw.strip()) if len(raw) <= 128 else None
    return match.group(1) if match else None


def hash_token(pepper: bytes, token: str) -> str:
    return hmac.new(pepper, token.encode(), hashlib.sha256).hexdigest()


def hashes_match(stored: str, presented: str) -> bool:
    return hmac.compare_digest(stored, presented)


@dataclass(frozen=True)
class TokenPrincipal:
    token_id: str
    name: str
    scopes: frozenset[ApiScope]
    created_by: str
    expires_at: datetime

    def has(self, scope: ApiScope) -> bool:
        return scope in self.scopes

    def readable_events(self) -> frozenset[str]:
        return frozenset(t for t, scope in EVENT_SCOPE.items() if scope in self.scopes)

    def missing_for_events(self, event_types: list[WebhookType] | list[str]) -> list[str]:
        """Read scopes this token lacks for the given event types (empty when all are covered)."""
        return sorted({EVENT_SCOPE[t].value for t in event_types if EVENT_SCOPE[t] not in self.scopes})
