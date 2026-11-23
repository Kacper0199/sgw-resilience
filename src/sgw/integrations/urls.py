"""Webhook target policy (SSRF guard).

Targets are `https://` only (K1 and K3 enforce it too), without credentials or fragments, at most 2048
characters. A host that is, or resolves to, a loopback, private, link-local, multicast, reserved or
unspecified address is refused, so a token holder cannot make the platform call its own network (metadata
endpoints, the database, the gateway). `SGW_WEBHOOK_ALLOW_HOSTS` (comma-separated `host:port`) admits named
exceptions, such as a consumer on the same machine in a demo or test. The check runs at subscription time and
before every delivery attempt; the attempt then connects to exactly the address that was checked (`vet`
returns it and `delivery.pinned_request` targets it), so a DNS answer that changes between check and
connect (rebinding) cannot redirect the request inward.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOW_ENV = "SGW_WEBHOOK_ALLOW_HOSTS"
MAX_URL = 2048

Resolver = Callable[[str, int], list[str]]


class UrlRefused(ValueError):
    pass


@dataclass(frozen=True)
class PinnedTarget:
    """The vetted address a delivery connects to; `host` stays Host header, TLS SNI and certificate name."""

    host: str
    port: int
    address: str


def system_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def allowlist_from_env(env: dict[str, str] | None = None) -> frozenset[str]:
    raw = (os.environ if env is None else env).get(ALLOW_ENV, "")
    return frozenset(item.strip().lower() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class UrlPolicy:
    allow_hosts: frozenset[str] = frozenset()
    resolver: Resolver = system_resolver

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> UrlPolicy:
        return cls(allow_hosts=allowlist_from_env(env))

    def check(self, url: str) -> None:
        self.vet(url)

    def vet(self, url: str) -> PinnedTarget:
        """Resolve once and return the address to connect to; refuses when any address is not public."""
        if len(url) > MAX_URL:
            raise UrlRefused("URL too long")
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise UrlRefused("webhook URLs must use https")
        if parts.username or parts.password:
            raise UrlRefused("credentials in the URL are not allowed")
        if parts.fragment:
            raise UrlRefused("fragments are not allowed")
        host = (parts.hostname or "").lower()
        if not host:
            raise UrlRefused("URL has no host")
        try:
            port = parts.port or 443
        except ValueError as exc:
            raise UrlRefused("invalid port") from exc
        try:
            found = [str(ipaddress.ip_address(host))]
        except ValueError:
            try:
                found = list(self.resolver(host, port))
            except OSError as exc:
                raise UrlRefused("host does not resolve") from exc
        if not found:
            raise UrlRefused("host does not resolve")
        allowed = f"{host}:{port}" in self.allow_hosts
        if not allowed and not all(_public(a) for a in found):
            raise UrlRefused("host resolves to a non-public address")
        ordered = sorted(found, key=lambda a: (ipaddress.ip_address(a.split("%", 1)[0]).version, a))
        return PinnedTarget(host=host, port=port, address=ordered[0])
