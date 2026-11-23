"""The webhook process: fan out new ledger rows to deliveries, then attempt every due delivery; repeat.

Run with `uv run sgw integrations worker` (one process is enough; several are safe: fan-out takes an advisory
lock and claims use SKIP LOCKED). `SGW_WEBHOOK_CA_FILE` adds a CA bundle the TLS client trusts (a consumer
with a private CA); `SGW_WEBHOOK_ALLOW_HOSTS` admits named internal targets (see `urls`).
"""

from __future__ import annotations

import asyncio
import logging
import os
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from psycopg import AsyncConnection

from sgw.integrations import backoff
from sgw.integrations.delivery import TIMEOUT, DeliveryWorker
from sgw.integrations.dispatch import dispatch_all
from sgw.integrations.keys import IntegrationKeys, load_keys
from sgw.integrations.urls import UrlPolicy

log = logging.getLogger("sgw.integrations.worker")
CA_ENV = "SGW_WEBHOOK_CA_FILE"


def tls_context(ca_file: str | None = None) -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if ca_file:
        context.load_verify_locations(cafile=ca_file)
    return context


def webhook_client(tls: ssl.SSLContext) -> httpx.AsyncClient:
    """One client per delivery attempt (no pooled connection is shared across hostnames); no proxy env."""
    transport = httpx.AsyncHTTPTransport(verify=tls, retries=0)
    return httpx.AsyncClient(transport=transport, timeout=TIMEOUT, trust_env=False)


def wall_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class WebhookRunner:
    dsn: str
    keys: IntegrationKeys = field(default_factory=load_keys)
    policy: backoff.RetryPolicy = field(default_factory=backoff.RetryPolicy)
    url_policy: UrlPolicy = field(default_factory=UrlPolicy.from_env)
    tls: ssl.SSLContext = field(default_factory=lambda: tls_context(os.environ.get(CA_ENV) or None))
    now: Callable[[], datetime] = wall_now
    interval_s: float = 1.0

    def client(self) -> httpx.AsyncClient:
        return webhook_client(self.tls)

    async def cycle(self, conn: AsyncConnection[Any], worker: DeliveryWorker) -> dict[str, int]:
        created = await dispatch_all(conn, self.now())
        totals: dict[str, int] = {"created": created}
        while True:
            counts = await worker.run_once()
            if not counts:
                return totals
            for state, n in counts.items():
                totals[state] = totals.get(state, 0) + n

    async def run(self, *, once: bool = False) -> dict[str, int]:
        async with await AsyncConnection.connect(self.dsn, autocommit=True) as conn:
            worker = DeliveryWorker(conn, self.client, self.keys, self.policy, self.url_policy, self.now)
            while True:
                totals = await self.cycle(conn, worker)
                if once:
                    return totals
                if len(totals) > 1 or totals["created"]:
                    log.info("webhooks: %s", totals)
                await asyncio.sleep(self.interval_s)
