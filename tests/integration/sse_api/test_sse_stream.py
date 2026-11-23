"""S4: K4 `stream/ops` through Caddy on a real uvicorn socket: unbuffered delivery, reconnect replay, p95.

Run: `SGW_TEST_DATABASE_URL=<admin url> uv run pytest tests/integration/sse_api -m slow -q -s`.
"""

from __future__ import annotations

import asyncio
import statistics
import time

import httpx
import psycopg
import pytest

from sgw.contracts.wire import WireEvent

from .sse_testkit import CaddyPorts, Received, ScratchDb, SseReader, expect, insert_events

pytestmark = pytest.mark.slow
P95_LIMIT_S = 2.0
PROXIES = ("relay-8000", "site-8080")


async def _client(port: int, db: ScratchDb, user: str = "ops_dm_01") -> httpx.AsyncClient:
    client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}")
    expect(await client.post("/api/auth/login", json={"user_id": user, "password": db.password}), 200)
    return client


async def _wait_for(pred, timeout: float) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met")
        await asyncio.sleep(0.02)


def _ledger(frames: list[Received]) -> list[Received]:
    return [f for f in frames if f.frame.type is WireEvent.LEDGER]


@pytest.mark.parametrize("proxy", PROXIES)
async def test_first_heartbeat_arrives_unbuffered(
    scratch_db: ScratchDb, caddy: CaddyPorts, proxy: str
) -> None:
    client = await _client(caddy.port(proxy), scratch_db)
    reader, stop = SseReader(), asyncio.Event()
    started = time.time()
    task = asyncio.create_task(reader.read(client, "/api/stream/ops", last_event_id=None, stop=stop))
    try:
        await _wait_for(lambda: len(reader.frames) >= 2, timeout=5)
    finally:
        stop.set()
        task.cancel()
        await client.aclose()
    first, second = reader.frames[0], reader.frames[1]
    assert first.frame.type is WireEvent.HEARTBEAT
    assert first.at - started < 1.0, "the opening heartbeat must not sit in a proxy buffer"
    assert 0.5 < second.at - first.at < 2.0, "heartbeats arrive one by one (SGW_SSE_HEARTBEAT_S=1)"
    assert reader.headers["content-type"].startswith("text/event-stream")
    print(
        f"\n[S4] {proxy}: first heartbeat after {first.at - started:.3f}s, "
        f"content-encoding={reader.headers.get('content-encoding', 'identity')}"
    )


async def test_reconnect_replays_exactly_the_missed_ledger_rows(
    scratch_db: ScratchDb, caddy: CaddyPorts
) -> None:
    client = await _client(caddy.site, scratch_db)
    reader, stop = SseReader(), asyncio.Event()
    task = asyncio.create_task(reader.read(client, "/api/stream/ops", last_event_id=None, stop=stop))
    await _wait_for(lambda: len(reader.frames) >= 1, timeout=5)
    head = reader.frames[0].frame.payload["head_ledger_seq"]
    first_batch = await asyncio.to_thread(insert_events, scratch_db.admin_url, 50)
    await _wait_for(lambda: len(_ledger(reader.frames)) >= 20, timeout=10)
    stop.set()
    task.cancel()
    received = _ledger(reader.frames)
    cut = next(r for r in received if r.frame.ledger_seq == head + 20)
    second_batch = await asyncio.to_thread(insert_events, scratch_db.admin_url, 30)

    reader2, stop2 = SseReader(), asyncio.Event()
    expected = [s for s, _ in first_batch if s > head + 20] + [s for s, _ in second_batch]
    task2 = asyncio.create_task(
        reader2.read(client, "/api/stream/ops", last_event_id=cut.sse_id.render(), stop=stop2)
    )
    try:
        await _wait_for(lambda: len(_ledger(reader2.frames)) >= len(expected), timeout=15)
    finally:
        stop2.set()
        task2.cancel()
        await client.aclose()
    replayed = [r.frame.ledger_seq for r in _ledger(reader2.frames)]
    assert replayed == expected, "no gap, no duplicate, in ledger order"
    assert reader2.frames[0].frame.type is WireEvent.HEARTBEAT
    print(
        f"\n[S4] reconnect after seq {cut.frame.ledger_seq}: replayed {len(replayed)} rows "
        f"({replayed[0]}..{replayed[-1]}) from the ledger"
    )


@pytest.mark.parametrize("proxy", PROXIES)
async def test_event_to_client_p95_under_two_seconds(
    scratch_db: ScratchDb, caddy: CaddyPorts, proxy: str
) -> None:
    client = await _client(caddy.port(proxy), scratch_db)
    reader, stop = SseReader(), asyncio.Event()
    task = asyncio.create_task(reader.read(client, "/api/stream/ops", last_event_id=None, stop=stop))
    await _wait_for(lambda: len(reader.frames) >= 1, timeout=5)
    written = await asyncio.to_thread(insert_events, scratch_db.admin_url, 300, pace_s=0.02)
    try:
        await _wait_for(
            lambda: {r.frame.ledger_seq for r in _ledger(reader.frames)} >= {s for s, _ in written},
            timeout=20,
        )
    finally:
        stop.set()
        task.cancel()
        await client.aclose()
    got = {r.frame.ledger_seq: r.at for r in _ledger(reader.frames)}
    lat = sorted(got[s] - t for s, t in written)
    p50, p95 = statistics.median(lat), lat[int(0.95 * (len(lat) - 1))]
    print(
        f"\n[S4] {proxy}: n={len(lat)} paced 50/s, latency p50={p50 * 1000:.0f} ms "
        f"p95={p95 * 1000:.0f} ms max={lat[-1] * 1000:.0f} ms (limit {P95_LIMIT_S * 1000:.0f} ms)"
    )
    assert p95 < P95_LIMIT_S


async def test_burst_of_two_thousand_reaches_every_client_in_order(
    scratch_db: ScratchDb, caddy: CaddyPorts
) -> None:
    clients = [await _client(caddy.site, scratch_db) for _ in range(3)]
    readers = [SseReader() for _ in clients]
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(r.read(c, "/api/stream/ops", last_event_id=None, stop=stop))
        for r, c in zip(readers, clients, strict=True)
    ]
    await _wait_for(lambda: all(len(r.frames) >= 1 for r in readers), timeout=5)
    written = await asyncio.to_thread(insert_events, scratch_db.admin_url, 2000)
    want = [s for s, _ in written]
    try:
        await _wait_for(lambda: all(len(_ledger(r.frames)) >= len(want) for r in readers), timeout=60)
    finally:
        stop.set()
        for t in tasks:
            t.cancel()
        for c in clients:
            await c.aclose()
    for r in readers:
        assert [f.frame.ledger_seq for f in _ledger(r.frames)] == want


async def test_scenario_command_reaches_the_stream(scratch_db: ScratchDb, caddy: CaddyPorts) -> None:
    client = await _client(caddy.site, scratch_db, user="ic_01")
    reader, stop = SseReader(), asyncio.Event()
    task = asyncio.create_task(reader.read(client, "/api/stream/ops", last_event_id=None, stop=stop))
    await _wait_for(lambda: len(reader.frames) >= 1, timeout=5)
    sent = time.time()
    r = await client.post(
        "/api/scenario",
        json={"action": "bookmark", "bookmark": "landfall"},
        headers={"X-CSRF-Token": client.cookies["sgw_csrf"]},
    )
    assert r.status_code == 200, r.text

    def seen() -> bool:
        return any(
            f.frame.payload.get("event_type") == "ScenarioClockChanged" for f in _ledger(reader.frames)
        )

    try:
        await _wait_for(seen, timeout=5)
    finally:
        stop.set()
        task.cancel()
        await client.aclose()
    frame = next(
        f for f in _ledger(reader.frames) if f.frame.payload.get("event_type") == "ScenarioClockChanged"
    )
    assert frame.frame.payload["payload"]["bookmark"] == "landfall"
    assert frame.at - sent < 2.0
    with psycopg.connect(scratch_db.admin_url) as conn:
        kind = conn.execute(
            "SELECT kind FROM audit_event WHERE kind = 'scenario_clock_changed' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
    assert kind == ("scenario_clock_changed",)
    await asyncio.to_thread(insert_events, scratch_db.admin_url, 3)
    with psycopg.connect(scratch_db.admin_url) as conn:
        count, top = conn.execute("SELECT count(*), max(ledger_seq) FROM event").fetchone() or (0, 0)
    assert count == top, "platform appends and default inserts interleave without a hole"


async def test_stream_requires_a_session(scratch_db: ScratchDb, caddy: CaddyPorts) -> None:
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{caddy.site}") as c:
        r = await c.get("/api/stream/ops")
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_logout_closes_the_open_stream(scratch_db: ScratchDb, caddy: CaddyPorts) -> None:
    client = await _client(caddy.site, scratch_db, user="log_01")
    reader, stop = SseReader(), asyncio.Event()
    task = asyncio.create_task(reader.read(client, "/api/stream/ops", last_event_id=None, stop=stop))
    await _wait_for(lambda: len(reader.frames) >= 1, timeout=5)
    r = await client.post("/api/auth/logout", headers={"X-CSRF-Token": client.cookies["sgw_csrf"]})
    assert r.status_code == 204
    try:
        await asyncio.wait_for(task, timeout=5)
    finally:
        stop.set()
        await client.aclose()
    assert task.exception() is None, "the server ended the stream cleanly after the session was gone"


async def test_foreign_last_event_id_gets_resync(scratch_db: ScratchDb, caddy: CaddyPorts) -> None:
    client = await _client(caddy.site, scratch_db)
    reader, stop = SseReader(), asyncio.Event()
    task = asyncio.create_task(reader.read(client, "/api/stream/ops", last_event_id="run:x.1.5", stop=stop))
    try:
        await _wait_for(lambda: len(reader.frames) >= 2, timeout=5)
    finally:
        stop.set()
        task.cancel()
        await client.aclose()
    assert [f.frame.type for f in reader.frames[:2]] == [WireEvent.RESYNC, WireEvent.HEARTBEAT]
