"""Spike S11: four producers write 1,000 events each through the outbox while four relays drain concurrently;
one relay batch is rolled back on purpose. The ledger must be 1..4000, gapless, with each producer's order
kept and every duplicate acknowledged without a number. Prints the measured numbers."""

from __future__ import annotations

import threading
import time
from collections import defaultdict

import psycopg
import pytest

from sgw.ingest import outbox, relay
from sgw.ingest.synthetic import meter_events
from sgw.ingest.testing import ScratchDb

pytestmark = pytest.mark.slow

PRODUCERS = 4
EVENTS_EACH = 1000
TX_SIZE = 50
DUPLICATE_EVERY = 10


def _produce(url: str, name: str, errors: list[BaseException]) -> None:
    try:
        events = meter_events(name, EVENTS_EACH)
        with psycopg.connect(url, autocommit=True) as conn:
            for start in range(0, EVENTS_EACH, TX_SIZE):
                chunk = events[start : start + TX_SIZE]
                resend = [e for i, e in enumerate(events[:start]) if i % DUPLICATE_EVERY == 0][-2:]
                with conn.transaction():
                    outbox.enqueue(conn, chunk + resend, origin=f"s11-{name}")
    except BaseException as error:  # noqa: BLE001
        errors.append(error)


def _relay(url: str, stop: threading.Event, stats: dict[str, int], errors: list[BaseException]) -> None:
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            while True:
                batch = relay.relay_batch(conn, limit=200)
                stats["batches"] += 1 if batch.claimed else 0
                stats["duplicates"] += batch.duplicates
                if batch.claimed == 0:
                    if stop.is_set():
                        return
                    time.sleep(0.005)
    except BaseException as error:  # noqa: BLE001
        errors.append(error)


def _crash(conn: psycopg.Connection, target: int) -> None:
    raise RuntimeError("relay crashed after numbering")


def test_s11_four_by_thousand_gapless(scratch_db: ScratchDb, monkeypatch: pytest.MonkeyPatch) -> None:
    url = scratch_db.runtime_url
    errors: list[BaseException] = []
    stats: dict[str, int] = defaultdict(int)
    with psycopg.connect(url, autocommit=True) as conn:
        outbox.enqueue(conn, meter_events("warmup", 20), origin="s11-warmup")
        with monkeypatch.context() as patch:
            patch.setattr(relay, "_advance_identity", _crash)
            with pytest.raises(RuntimeError):
                relay.relay_batch(conn, limit=20)
    started = time.perf_counter()
    stop = threading.Event()
    relays = [threading.Thread(target=_relay, args=(url, stop, stats, errors)) for _ in range(4)]
    producers = [threading.Thread(target=_produce, args=(url, f"p{i}", errors)) for i in range(PRODUCERS)]
    for t in relays + producers:
        t.start()
    for t in producers:
        t.join(timeout=120)
    stop.set()
    for t in relays:
        t.join(timeout=120)
    elapsed = time.perf_counter() - started
    assert not errors, errors

    expected = PRODUCERS * EVENTS_EACH + 20
    with psycopg.connect(url, autocommit=True) as conn:
        relay.drain(conn)
        report = relay.verify_ledger(conn)
        order = conn.execute(
            "SELECT source_id, array_agg(dedup_key ORDER BY ledger_seq) FROM event GROUP BY source_id"
        ).fetchall()
        dup_keys = conn.execute(
            "SELECT count(*) FROM (SELECT dedup_key FROM event GROUP BY dedup_key HAVING count(*) > 1) d"
        ).fetchone()
        left = outbox.pending(conn)
    assert report.gapless, report
    assert report.count == expected and report.max_seq == expected
    assert dup_keys is not None and dup_keys[0] == 0
    assert left == 0
    for source_id, keys in order:
        assert keys == sorted(keys), f"{source_id}: producer order not kept"
    print(
        f"\nS11: producers={PRODUCERS} x {EVENTS_EACH} (+20 warm-up after a rolled-back batch), relays=4,"
        f" ledger 1..{report.max_seq} count={report.count} gaps={len(report.gaps)},"
        f" duplicates acked={stats['duplicates']}, relay batches={stats['batches']},"
        f" wall={elapsed:.2f}s, throughput={report.count / elapsed:.0f} events/s"
    )
