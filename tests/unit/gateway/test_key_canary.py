from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
from services.llm_gateway.config import Mode
from services.llm_gateway.recording import Recording, RecordingStore
from services.llm_gateway.redact import KeyLeakError, redact_for_log

from .gateway_testkit import BASE_HEADERS, FAKE_KEY, KEY_PREFIX, FakeUpstream, base_body, message_json

REPO = Path(__file__).resolve().parents[3]


def _all_text(root: Path) -> str:
    return "\n".join(p.read_text(errors="ignore") for p in root.rglob("*") if p.is_file())


async def test_fake_key_never_lands_in_fixture_ledger_or_logs(client_factory, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="sgw.llm_gateway")
    upstream = FakeUpstream()
    client, _ = client_factory(upstream=upstream, mode=Mode.RECORD)
    for i in range(3):
        r = await client.post(
            "/v1/messages",
            json=base_body(messages=[{"role": "user", "content": f"turn {i}"}]),
            headers=BASE_HEADERS,
        )
        assert r.status_code == 200
        assert FAKE_KEY not in r.text and FAKE_KEY not in str(r.headers)
    assert upstream.requests[0].headers["x-api-key"] == FAKE_KEY
    persisted = _all_text(tmp_path)
    assert persisted, "record mode must have written fixtures and the ledger"
    assert KEY_PREFIX not in persisted
    assert KEY_PREFIX not in caplog.text


async def test_upstream_echoing_a_key_is_refused_not_recorded(client_factory, tmp_path):
    echo = message_json(f"leak {FAKE_KEY}")
    client, _ = client_factory(upstream=FakeUpstream([httpx.Response(200, json=echo)]), mode=Mode.RECORD)
    r = await client.post("/v1/messages", json=base_body(), headers=BASE_HEADERS)
    assert r.status_code == 502 and r.json()["error"]["type"] == "sgw_key_leak_blocked"
    assert KEY_PREFIX not in r.text
    assert not list((tmp_path / "fixtures").rglob("*.json"))


def test_store_refuses_key_shaped_content(tmp_path):
    store = RecordingStore(tmp_path)
    rec = Recording(
        node="test.narrate",
        request_sha256="0" * 64,
        prompt_version=None,
        model="claude-sonnet-5-5",
        data_classes=["C1"],
        request={"system": KEY_PREFIX + "api03-xyz"},
        request_headers={},
        response=message_json(),
        cost_usd_at_record=0.0,
        latency_ms=1,
        recorded_at="2026-11-19T00:00:00Z",
    )
    with pytest.raises(KeyLeakError):
        store.save(rec)


def test_log_redaction_drops_content_and_scrubs_keys():
    event = redact_for_log(
        {"messages": ["secret plan"], "note": f"key={FAKE_KEY}", "nested": {"system": "x"}}
    )
    assert event["messages"] == "<omitted>" and event["nested"]["system"] == "<omitted>"
    assert FAKE_KEY not in event["note"]


def test_committed_fixtures_contain_no_key():
    root = REPO / "data" / "fixtures" / "llm"
    if root.is_dir():
        assert KEY_PREFIX not in _all_text(root)
