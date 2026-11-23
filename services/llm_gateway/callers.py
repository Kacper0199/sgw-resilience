"""Caller authentication and node binding (security audit M4).

Every `/v1/messages` request names its caller with a per-service bearer token (`Authorization: Bearer <t>`,
or the SDK's `x-api-key: <t>`). The gateway holds only SHA-256 digests of the tokens
(`LLM_CALLER_TOKEN_SHA256=api:<hex>,worker:<hex>,cli:<hex>`), compares them in constant time, and binds each
service to the nodes it may call (`callers.yaml`). Missing or unknown token: 401. Node outside the service's
set: 403. The public test tokens below are accepted only with `accept_test_tokens`, which `Settings` refuses
for live or record runs against the real API.
"""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from .policy import PolicyViolation

CALLERS_FILE = Path(__file__).with_name("callers.yaml")
SERVICES = ("api", "worker", "cli")
TEST_TOKENS: dict[str, str] = {service: f"sgw-test-caller-{service}" for service in SERVICES}


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Caller:
    service: str
    nodes: tuple[str, ...]
    may_send_c2: bool = False

    def may_call(self, node: str) -> bool:
        return any(node == p or fnmatch.fnmatchcase(node, p) for p in self.nodes)


def load_callers(path: Path = CALLERS_FILE) -> dict[str, Caller]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, Caller] = {}
    for name, cfg in (raw.get("services") or {}).items():
        if not isinstance(cfg, Mapping):
            continue
        out[str(name)] = Caller(
            service=str(name),
            nodes=tuple(str(n) for n in cfg.get("nodes") or ()),
            may_send_c2=cfg.get("may_send_c2") is True,
        )
    return out


def parse_token_digests(raw: str) -> tuple[tuple[str, str], ...]:
    """`api:<hex>,worker:<hex>` -> ((service, hex), ...); malformed entries are refused, not skipped."""
    pairs: list[tuple[str, str]] = []
    for item in (p.strip() for p in raw.split(",") if p.strip()):
        service, _, digest = item.partition(":")
        digest = digest.strip().lower()
        if not service or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("LLM_CALLER_TOKEN_SHA256 entries must be <service>:<64 hex sha256>")
        pairs.append((service.strip(), digest))
    return tuple(pairs)


def _presented_token(headers: Mapping[str, str]) -> str | None:
    auth = headers.get("authorization", "")
    bearer = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    api_key = headers.get("x-api-key", "").strip()
    if bearer and api_key and not hmac.compare_digest(bearer, api_key):
        return None
    return bearer or api_key or None


class CallerRegistry:
    def __init__(
        self,
        digests: tuple[tuple[str, str], ...],
        callers: Mapping[str, Caller],
        *,
        accept_test_tokens: bool = False,
    ) -> None:
        entries = list(digests)
        if accept_test_tokens:
            entries += [(service, token_sha256(token)) for service, token in TEST_TOKENS.items()]
        self._entries = tuple((s, d) for s, d in entries if s in callers)
        self._callers = dict(callers)
        self.test_tokens = accept_test_tokens

    @property
    def services(self) -> list[str]:
        return sorted({s for s, _ in self._entries})

    def authenticate(self, headers: Mapping[str, str]) -> Caller:
        token = _presented_token(headers)
        if token is None:
            raise PolicyViolation(
                "sgw_unauthenticated", "a caller token is required (Authorization: Bearer)", 401
            )
        digest = token_sha256(token)
        match: str | None = None
        for service, known in self._entries:
            if hmac.compare_digest(digest, known):
                match = service
        if match is None:
            raise PolicyViolation("sgw_unauthenticated", "unknown caller token", 401)
        return self._callers[match]

    @staticmethod
    def authorize(caller: Caller, node: str) -> None:
        if not caller.may_call(node):
            raise PolicyViolation(
                "sgw_node_not_allowed_for_caller",
                f"service {caller.service!r} may not call node {node!r}",
                403,
            )
