"""Fan-out and delivery against a real database with a mock receiver: idempotent fan-out, retries with
backoff, dead letter, 410 handling, signatures with a rotating secret."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg
import pytest
from psycopg import AsyncConnection

from sgw.api.ledger import append_platform_event
from sgw.contracts import webhooks
from sgw.contracts.vocab import ApiScope, RunMode
from sgw.integrations import backoff, repository
from sgw.integrations.delivery import ATTEMPT_HEADER, DeliveryWorker, replay_dead_letter
from sgw.integrations.dispatch import dispatch_all
from sgw.integrations.testkit import ALLOWED_HOST, KEYS, Db
from sgw.integrations.tokens import TokenPrincipal
from sgw.integrations.urls import UrlPolicy

T0 = datetime(2026, 11, 20, 2, 0, tzinfo=UTC)
HOOK = f"https://{ALLOWED_HOST}/hooks/sgw"
SCENARIO_T = datetime(2024, 9, 26, 18, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def __call__(self) -> datetime:
        return self.at

    def advance(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)


@pytest.fixture
async def conn(db: Db) -> AsyncIterator[AsyncConnection[Any]]:
    async with await AsyncConnection.connect(db.runtime_url, autocommit=True) as c:
        await c.execute("UPDATE webhook_subscription SET active = false WHERE active")
        yield c


async def principal(conn: AsyncConnection[Any], *scopes: ApiScope) -> TokenPrincipal:
    async with conn.transaction():
        issued, _ = await repository.create_token(
            conn,
            KEYS,
            name="Tamsworth outage board",
            scopes=list(scopes),
            expires_at=T0 + timedelta(days=30),
            created_by="admin_01",
            now=T0,
            via="test",
        )
        found = await repository.resolve_token(conn, KEYS, issued.token, T0)
    assert found is not None
    return found


async def subscribe(conn: AsyncConnection[Any], who: TokenPrincipal, types: list[str]) -> tuple[str, str]:
    async with conn.transaction():
        sub, secret = await repository.create_subscription(
            conn, KEYS, who, url=HOOK, event_types=types, now=T0
        )
    return sub.subscription_id, secret


async def approved(conn: AsyncConnection[Any], n: int) -> int:
    async with conn.transaction():
        return await append_platform_event(
            conn,
            type_name="DecisionApproved",
            payload={
                "decision_case_id": "DC-D2-CREWS-AIK",
                "proposal_id": f"PRP-T37-{n:04d}",
                "proposal_version": 1,
                "action_hash": f"{n:064x}",
                "tier": "T2",
                "approver_ids": ["ic_01"],
            },
            scenario_time=SCENARIO_T,
            wall_now=T0,
            run_mode=RunMode.REPLAY,
        )


class Receiver:
    def __init__(self, secrets: list[str], statuses: Callable[[int], int]) -> None:
        self.secrets = secrets
        self.statuses = statuses
        self.calls: list[httpx.Request] = []
        self.clock: Clock | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert self.clock is not None
        for secret in self.secrets:
            webhooks.verify(
                secret.encode(),
                header=request.headers[webhooks.SIGNATURE_HEADER],
                delivery_id=request.headers[webhooks.ID_HEADER],
                body=request.content,
                now=int(self.clock().timestamp()),
            )
        return httpx.Response(self.statuses(len(self.calls)))


def worker(
    conn: AsyncConnection[Any], receiver: Receiver, clock: Clock, max_attempts: int = 4
) -> DeliveryWorker:
    receiver.clock = clock
    return DeliveryWorker(
        conn=conn,
        connect=lambda: httpx.AsyncClient(transport=httpx.MockTransport(receiver)),
        keys=KEYS,
        policy=backoff.RetryPolicy(base_s=10, cap_s=60, max_attempts=max_attempts, jitter=lambda: 1.0),
        url_policy=UrlPolicy(allow_hosts=frozenset({ALLOWED_HOST})),
        now=clock,
    )


async def delivery(conn: AsyncConnection[Any], subscription_id: str) -> tuple[Any, ...]:
    cur = await conn.execute(
        "SELECT state, attempts, next_attempt_at, last_status FROM webhook_delivery"
        " WHERE subscription_id = %s",
        (subscription_id,),
    )
    rows = await cur.fetchall()
    assert len(rows) == 1
    return tuple(rows[0])


async def test_fan_out_starts_after_subscription_respects_scope_and_is_idempotent(
    conn: AsyncConnection[Any],
) -> None:
    await approved(conn, 1)
    who = await principal(conn, ApiScope.DECISIONS_READ, ApiScope.WEBHOOKS_MANAGE)
    await dispatch_all(conn, T0)
    sid, _ = await subscribe(conn, who, ["DecisionApproved"])
    other, _ = await subscribe(conn, who, ["DecisionApproved"])
    await approved(conn, 2)
    assert await dispatch_all(conn, T0) == 2
    assert await dispatch_all(conn, T0) == 0
    await conn.execute("UPDATE integration_cursor SET last_seq = 0 WHERE name = 'webhooks'")
    assert await dispatch_all(conn, T0) == 0
    cur = await conn.execute(
        "SELECT count(*) FROM webhook_delivery WHERE subscription_id = ANY(%s)", ([sid, other],)
    )
    assert await cur.fetchone() == (2,)


async def test_retries_back_off_then_deliver_with_identical_body_and_id(conn: AsyncConnection[Any]) -> None:
    who = await principal(conn, ApiScope.DECISIONS_READ, ApiScope.WEBHOOKS_MANAGE)
    await dispatch_all(conn, T0)
    sid, secret = await subscribe(conn, who, ["DecisionApproved"])
    seq = await approved(conn, 3)
    clock = Clock()
    await dispatch_all(conn, clock())
    receiver = Receiver([secret], lambda n: 503 if n <= 2 else 200)
    w = worker(conn, receiver, clock)
    assert await w.run_once() == {"retrying": 1}
    state, attempts, next_at, status = await delivery(conn, sid)
    assert (state, attempts, status) == ("retrying", 1, 503) and next_at == clock() + timedelta(seconds=10)
    assert await w.run_once() == {}
    clock.advance(10)
    assert await w.run_once() == {"retrying": 1}
    state, attempts, next_at, _ = await delivery(conn, sid)
    assert attempts == 2 and next_at == clock() + timedelta(seconds=20)
    clock.advance(20)
    assert await w.run_once() == {"delivered": 1}
    assert (await delivery(conn, sid))[:2] == ("delivered", 3)
    bodies = {r.content for r in receiver.calls}
    ids = {r.headers[webhooks.ID_HEADER] for r in receiver.calls}
    assert len(bodies) == 1 and len(ids) == 1
    assert [r.headers[ATTEMPT_HEADER] for r in receiver.calls] == ["1", "2", "3"]
    sent = json.loads(receiver.calls[0].content)
    assert sent["type"] == "DecisionApproved" and sent["ledger_seq"] == seq and sent["schema_version"] == 1
    assert sent["data"]["proposal_id"] == "PRP-T37-0003"
    cur = await conn.execute(
        "SELECT attempt, status FROM webhook_attempt a JOIN webhook_delivery d USING (delivery_id)"
        " WHERE d.subscription_id = %s ORDER BY attempt",
        (sid,),
    )
    assert await cur.fetchall() == [(1, 503), (2, 503), (3, 200)]


async def test_exhausted_retries_dead_letter_and_replay_gives_one_more_attempt(
    conn: AsyncConnection[Any],
) -> None:
    who = await principal(conn, ApiScope.DECISIONS_READ, ApiScope.WEBHOOKS_MANAGE)
    await dispatch_all(conn, T0)
    sid, secret = await subscribe(conn, who, ["DecisionApproved"])
    await approved(conn, 4)
    clock = Clock()
    await dispatch_all(conn, clock())
    receiver = Receiver([secret], lambda n: 500 if n <= 3 else 204)
    w = worker(conn, receiver, clock, max_attempts=3)
    for _ in range(3):
        await w.run_once()
        clock.advance(3600)
    state, attempts, next_at, status = await delivery(conn, sid)
    assert (state, attempts, next_at, status) == ("failed", 3, None, 500)
    assert await w.run_once() == {}
    cur = await conn.execute("SELECT delivery_id FROM webhook_delivery WHERE subscription_id = %s", (sid,))
    row = await cur.fetchone()
    assert row is not None
    assert await replay_dead_letter(conn, row[0], actor_id="admin_01", now=clock())
    assert await w.run_once() == {"delivered": 1}
    cur = await conn.execute(
        "SELECT kind FROM audit_event WHERE subject = %s ORDER BY seq", (f"webhook_delivery:{row[0]}",)
    )
    assert [r[0] for r in await cur.fetchall()] == ["webhook_delivery.replayed"]


async def test_gone_disables_the_subscription_and_is_audited(conn: AsyncConnection[Any]) -> None:
    who = await principal(conn, ApiScope.DECISIONS_READ, ApiScope.WEBHOOKS_MANAGE)
    await dispatch_all(conn, T0)
    sid, secret = await subscribe(conn, who, ["DecisionApproved"])
    await approved(conn, 5)
    await approved(conn, 6)
    clock = Clock()
    await dispatch_all(conn, clock())
    w = worker(conn, Receiver([secret], lambda n: 410), clock)
    assert await w.run_once(limit=1) == {"disabled": 1}
    cur = await conn.execute(
        "SELECT state FROM webhook_delivery WHERE subscription_id = %s ORDER BY state", (sid,)
    )
    assert [r[0] for r in await cur.fetchall()] == ["disabled", "disabled"]
    cur = await conn.execute(
        "SELECT active, disabled_reason FROM webhook_subscription WHERE subscription_id = %s", (sid,)
    )
    assert await cur.fetchone() == (False, "receiver_gone")
    cur = await conn.execute(
        "SELECT kind FROM audit_event WHERE subject = %s ORDER BY seq", (f"webhook_subscription:{sid}",)
    )
    assert [r[0] for r in await cur.fetchall()] == [
        "webhook_subscription.created",
        "webhook_subscription.disabled",
    ]


async def test_rotation_signs_with_both_secrets_during_overlap_then_only_the_new(
    conn: AsyncConnection[Any],
) -> None:
    who = await principal(conn, ApiScope.DECISIONS_READ, ApiScope.WEBHOOKS_MANAGE)
    await dispatch_all(conn, T0)
    sid, old = await subscribe(conn, who, ["DecisionApproved"])
    async with conn.transaction():
        new, retires = await repository.rotate_secret(
            conn, KEYS, who, sid, overlap=timedelta(hours=1), now=T0
        )
    assert retires == T0 + timedelta(hours=1)
    await approved(conn, 7)
    clock = Clock()
    await dispatch_all(conn, clock())
    both = Receiver([old, new], lambda n: 200)
    assert await worker(conn, both, clock).run_once() == {"delivered": 1}
    assert both.calls[0].headers[webhooks.SIGNATURE_HEADER].count("v1=") == 2
    clock.advance(3601)
    await approved(conn, 8)
    await dispatch_all(conn, clock())
    only_new = Receiver([new], lambda n: 200)
    assert await worker(conn, only_new, clock).run_once() == {"delivered": 1}
    header = only_new.calls[0].headers[webhooks.SIGNATURE_HEADER]
    assert header.count("v1=") == 1
    with pytest.raises(webhooks.SignatureError):
        webhooks.verify(
            old.encode(),
            header=header,
            delivery_id=only_new.calls[0].headers[webhooks.ID_HEADER],
            body=only_new.calls[0].content,
            now=int(clock().timestamp()),
        )


async def test_revoked_token_stops_fan_out(conn: AsyncConnection[Any], db: Db) -> None:
    who = await principal(conn, ApiScope.DECISIONS_READ, ApiScope.WEBHOOKS_MANAGE)
    await dispatch_all(conn, T0)
    sid, _ = await subscribe(conn, who, ["DecisionApproved"])
    async with conn.transaction():
        assert await repository.revoke_token(conn, who.token_id, actor_id="admin_01", now=T0, via="test")
    await approved(conn, 9)
    assert await dispatch_all(conn, T0) == 0
    with psycopg.connect(db.admin_url) as sync:
        assert sync.execute(
            "SELECT count(*) FROM webhook_delivery WHERE subscription_id = %s", (sid,)
        ).fetchone() == (0,)
