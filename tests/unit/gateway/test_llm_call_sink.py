from __future__ import annotations

import secrets
import time
from collections.abc import Iterator
from typing import Any

import httpx
import psycopg
import pytest
from psycopg import sql
from services.llm_gateway.calls import COLUMNS, LlmCallRecord, MemorySink, PostgresSink
from services.llm_gateway.config import Mode

from sgw.approval import testkit as tk

from .gateway_testkit import BASE_HEADERS, FakeUpstream, base_body, message_json

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
DEV = {**BASE_HEADERS, "x-sgw-purpose": "dev"}


def _record(**kw: Any) -> LlmCallRecord:
    base: dict[str, Any] = {
        "call_id": secrets.token_hex(16),
        "ts": "2026-11-19T23:30:00Z",
        "mode": "live",
        "billed": True,
        "purpose": "dev",
        "wave": "W2",
        "run_id": "run-0001",
        "node": "narrate_brief",
        "prompt_version": "v1",
        "model": "claude-sonnet-5-5",
        "effort": "medium",
        "route": "R1",
        "classes": ("C1",),
        "decision": "allow",
        "request_hash": "a" * 64,
        "payload_hash": "b" * 64,
        "input_tokens": 1200,
        "cache_read_input_tokens": 800,
        "output_tokens": 90,
        "stop_reason": "end_turn",
        "latency_ms": 840,
        "cost_usd": 0.003412,
    }
    base.update(kw)
    return LlmCallRecord(**base)


def test_db_values_map_to_k1_columns():
    values = dict(zip(COLUMNS, _record(effort="", classes=("C1", "C9"), wave="").db_values(), strict=True))
    assert values["effort"] is None and values["wave"] is None
    assert values["classes"] == ["C1", "CX"]
    assert dict(zip(COLUMNS, _record().db_values(), strict=True))["cost_usd_micros"] == 3412


async def test_one_row_per_decision(client_factory):
    sink = MemorySink()
    upstream = FakeUpstream([httpx.Response(200, json=message_json(input_tokens=1000, output_tokens=50))])
    client, _ = client_factory(upstream=upstream, sink=sink, mode=Mode.LIVE)
    r_live = await client.post("/v1/messages", json=base_body(), headers=DEV)
    r_bad = await client.post("/v1/messages", json=base_body(temperature=0.2), headers=DEV)
    r_deny = await client.post("/v1/messages", json=base_body(), headers={**DEV, "x-sgw-classes": "C3"})
    live, bad, deny = sink.records
    assert live.call_id == r_live.headers["x-sgw-call-id"] and live.decision == "allow" and live.billed
    assert (live.input_tokens, live.output_tokens, live.route, live.mode) == (1000, 50, "R1", "live")
    assert live.cost_usd > 0 and len(live.request_hash) == 64 and len(live.payload_hash) == 64
    assert (bad.decision, bad.stop_reason, bad.billed) == ("deny", "sgw_sampling_param", False)
    assert r_bad.status_code == 400
    assert (deny.decision, deny.stop_reason) == ("deny", "sgw_class_denied") and r_deny.status_code == 403


async def test_replay_hit_and_miss_rows(client_factory, settings_factory):
    sink = MemorySink()
    record_client, _ = client_factory(sink=MemorySink())
    await record_client.post("/v1/messages", json=base_body(), headers=DEV)
    replay, _ = client_factory(sink=sink, mode=Mode.REPLAY, api_key=None)
    hit = await replay.post("/v1/messages", json=base_body(), headers=DEV)
    miss = await replay.post("/v1/messages", json=base_body(max_tokens=77), headers=DEV)
    assert (hit.status_code, miss.status_code) == (200, 424)
    h, m = sink.records
    assert (h.mode, h.billed, h.decision, h.cost_usd, h.input_tokens) == ("replay", False, "allow", 0.0, 100)
    assert (m.stop_reason, m.billed) == ("sgw_replay_miss", False)


def test_sink_never_raises_when_the_database_is_down():
    sink = PostgresSink("postgresql://nobody:x@127.0.0.1:9/none", retry_s=0.05)
    sink.submit(_record())
    deadline = time.monotonic() + 5
    while sink.snapshot()["errors"] == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    snap = sink.snapshot()
    assert snap["errors"] >= 1 and snap["last_error"] and snap["written"] == 0
    sink.submit(_record(purpose="unknown"))
    assert sink.snapshot()["skipped_unknown_purpose"] == 1
    sink.close(timeout_s=0.2)
    assert sink.snapshot()["dropped_on_close"] >= 1


@pytest.fixture(scope="module")
def writer_dsn() -> Iterator[tuple[str, str]]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: least-privilege writer test needs Postgres
    role = f"sgw_wp14a_gw_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(24)
    with psycopg.connect(tk.admin_dsn() or "", autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'sgw_llm_writer'").fetchone():
            conn.execute("CREATE ROLE sgw_llm_writer NOLOGIN")
    with tk.scratch_database(prefix="sgw_wp14a_t") as url:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE sgw_llm_writer").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
        scheme, rest = url.split("://", 1)
        hostpart = rest.split("@", 1)[1]
        try:
            yield url, f"{scheme}://{role}:{password}@{hostpart}"
        finally:
            with psycopg.connect(url, autocommit=True) as conn:
                conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


def test_least_privilege_writer_inserts_rows_and_nothing_else(writer_dsn):
    admin, dsn = writer_dsn
    sink = PostgresSink(dsn)
    allow, deny = (
        _record(),
        _record(decision="deny", billed=False, cost_usd=0.0, stop_reason="sgw_class_denied"),
    )
    sink.submit(allow)
    sink.submit(deny)
    sink.submit(allow)
    assert sink.flush(10)
    sink.close()
    snap = sink.snapshot()
    assert (snap["written"], snap["duplicates"], snap["rejected"]) == (2, 1, 0)
    with psycopg.connect(admin, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT decision, cost_usd_micros, classes::text[], route FROM llm_call ORDER BY decision"
        ).fetchall()
        assert rows == [("allow", 3412, ["C1"], "R1"), ("deny", 0, ["C1"], "R1")]
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
            conn.execute("UPDATE llm_call SET cost_usd_micros = 0")
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
            conn.execute("DELETE FROM llm_call")
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
            conn.execute("TRUNCATE llm_call")
    with psycopg.connect(dsn, autocommit=True) as conn:
        for sql in (
            "SELECT count(*) FROM llm_call",
            "UPDATE llm_call SET billed = false",
            "SELECT count(*) FROM audit_event",
            "TRUNCATE llm_call",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(sql)
