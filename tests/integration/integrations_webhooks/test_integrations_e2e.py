"""End to end on real sockets: the Helene crew proposal is approved in replay mode, `DecisionApproved` goes
through the outbox and relay into the ledger, the webhook worker signs and POSTs it over TLS to the example
consumer (`examples/webhook-consumer/consumer.py`, a separate process), which verifies and records it; the
same event arrives on `GET /v1/events`; replayed, stale, tampered and wrongly signed requests are refused."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import psycopg
import pytest
import uvicorn

from sgw.approval import testkit as approval_tk
from sgw.approval.ledger import OutboxSink
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.contracts import golden, webhooks
from sgw.ingest.testing import server_available
from sgw.integrations.payload import body_bytes, event_v1
from sgw.integrations.testkit import ALLOWED_HOST, KEYS, Db, build_app, seeded_db
from sgw.integrations.urls import UrlPolicy
from sgw.integrations.worker import WebhookRunner, tls_context

from .tls_testkit import Pems, make_pems

REPO = Path(__file__).resolve().parents[3]
CONSUMER = REPO / "examples" / "webhook-consumer" / "consumer.py"
CONSUMER_PORT = int(ALLOWED_HOST.rsplit(":", 1)[1])


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


API_PORT = _free_port()
HOOK = f"https://{ALLOWED_HOST}/hooks/sgw"
START = golden.ADVISORY_N.issued + timedelta(minutes=10)


@pytest.fixture(scope="module")
def db() -> Iterator[Db]:
    reason = server_available()
    if reason:
        pytest.skip(reason)  # sgw-allow-skip: end-to-end test needs Postgres (SGW_TEST_DATABASE_URL)
    with seeded_db("wp37e2e") as found:
        yield found


@pytest.fixture(scope="module")
def api(db: Db) -> Iterator[str]:
    server = uvicorn.Server(
        uvicorn.Config(build_app(db.runtime_url), host="127.0.0.1", port=API_PORT, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{API_PORT}"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base}/healthz", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        raise RuntimeError("API did not start")
    yield base
    server.should_exit = True
    thread.join(10)


@pytest.fixture(scope="module")
def pems(tmp_path_factory: pytest.TempPathFactory) -> Pems:
    return make_pems(tmp_path_factory.mktemp("tls"))


def start_consumer(pems: Pems, secrets: list[str], out: Path) -> subprocess.Popen[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SGW_")}
    env["SGW_WEBHOOK_SECRETS"] = ",".join(secrets)
    proc = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            str(CONSUMER),
            "--cert",
            str(pems.cert),
            "--key",
            str(pems.key),
            "--port",
            str(CONSUMER_PORT),
            "--out",
            str(out),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    context = ssl.create_default_context(cafile=str(pems.ca))
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"https://{ALLOWED_HOST}/healthz", verify=context, timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError(f"consumer did not start: {proc.stdout.read() if proc.stdout else ''}")


def approve_crew_proposal(admin_url: str) -> str:
    clock = approval_tk.MutableClock(START)
    svc = ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=clock, ledger=OutboxSink())
    with psycopg.connect(admin_url, autocommit=True) as conn:
        card = approval_tk.new_crew_proposal(conn, svc)
        for user in ("ic_01", "log_01"):
            svc.decide(
                conn, user_id=user, proposal_id=card.proposal_id, request=approval_tk.approve_req(card)
            )
    return card.proposal_id


def read_frames(base: str, token: str, last_event_id: str, want: str, timeout_s: float = 10) -> list[str]:
    frames: list[str] = []
    headers = {"Authorization": f"Bearer {token}", "Last-Event-ID": last_event_id}
    with httpx.stream("GET", f"{base}/v1/events", headers=headers, timeout=timeout_s) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        block: list[str] = []
        for line in response.iter_lines():
            if line:
                block.append(line)
                continue
            text = "\n".join(block)
            block = []
            if not text.startswith(":"):
                frames.append(text)
            if f"event: {want}" in text:
                return frames
    return frames


def test_example_consumer_receives_and_verifies_decision_approved(
    db: Db, api: str, pems: Pems, tmp_path: Path
) -> None:
    admin = httpx.Client(base_url=api)
    login = admin.post("/api/auth/login", json={"user_id": "admin_01", "password": db.password})
    assert login.status_code == 200, login.text
    csrf = {"X-CSRF-Token": admin.cookies["sgw_csrf"]}
    expires = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    created = admin.post(
        "/api/admin/tokens",
        json={
            "name": "Halvorsen SCADA bridge",
            "scopes": ["decisions:read", "webhooks:manage"],
            "expires_at": expires,
        },
        headers=csrf,
    )
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    bearer = {"Authorization": f"Bearer {token}"}
    sub = httpx.post(
        f"{api}/v1/webhooks", json={"url": HOOK, "event_types": ["DecisionApproved"]}, headers=bearer
    )
    assert sub.status_code == 201, sub.text
    secret = sub.headers["SGW-Webhook-Secret"]
    out = tmp_path / "received.jsonl"
    consumer = start_consumer(pems, [secret], out)
    try:
        with psycopg.connect(db.admin_url) as conn:
            head_before = conn.execute("SELECT coalesce(max(ledger_seq), 0) FROM event").fetchone()[0]  # type: ignore[index]
            epoch = conn.execute(
                "SELECT oid::bigint FROM pg_database WHERE datname = current_database()"
            ).fetchone()[0]  # type: ignore[index]
        proposal_id = approve_crew_proposal(db.admin_url)
        with psycopg.connect(db.admin_url) as conn:
            row = conn.execute(
                "SELECT event_id::text, ledger_seq, event_time, payload, run_mode FROM event"
                " WHERE type = 'DecisionApproved' AND payload->>'proposal_id' = %s",
                (proposal_id,),
            ).fetchone()
        assert row is not None and row[4] == "replay"
        event_id, seq, event_time, payload = row[0], int(row[1]), row[2], dict(row[3])

        runner = WebhookRunner(
            db.runtime_url,
            keys=KEYS,
            url_policy=UrlPolicy(allow_hosts=frozenset({ALLOWED_HOST})),
            tls=tls_context(str(pems.ca)),
        )
        totals = asyncio.run(runner.run(once=True))
        assert totals == {"created": 1, "delivered": 1}

        records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        assert len(records) == 1
        received = records[0]["event"]
        assert received["type"] == "DecisionApproved" and received["id"] == event_id
        assert received["ledger_seq"] == seq and received["data"]["proposal_id"] == proposal_id
        assert received["data"]["approver_ids"] == ["ic_01", "log_01"]
        delivery_id = records[0]["delivery_id"]
        with psycopg.connect(db.admin_url) as conn:
            state = conn.execute(
                "SELECT state, attempts, last_status FROM webhook_delivery WHERE delivery_id = %s",
                (delivery_id,),
            ).fetchone()
        assert state == ("delivered", 1, 200)

        frames = read_frames(api, token, f"v1.{epoch}.{head_before}", "DecisionApproved")
        approved = [f for f in frames if "event: DecisionApproved" in f]
        assert len(approved) == 1 and f"id: v1.{epoch}.{seq}" in approved[0]
        streamed = json.loads(approved[0].split("data: ", 1)[1])
        assert streamed == received

        body = body_bytes(
            event_v1(
                event_id=event_id,
                event_type="DecisionApproved",
                ledger_seq=seq,
                event_time=event_time,
                payload=payload,
            )
        )
        context = ssl.create_default_context(cafile=str(pems.ca))

        def post(raw: bytes, header: str) -> httpx.Response:
            return httpx.post(
                HOOK,
                content=raw,
                headers={
                    "SGW-Signature": header,
                    "SGW-Webhook-Id": delivery_id,
                    "Content-Type": "application/json",
                },
                verify=context,
            )

        now = int(time.time())
        replayed = post(
            body, webhooks.sign(secret.encode(), timestamp=now, delivery_id=delivery_id, body=body)
        )
        assert replayed.status_code == 200 and replayed.json() == {"status": "duplicate"}
        stale = post(
            body, webhooks.sign(secret.encode(), timestamp=now - 301, delivery_id=delivery_id, body=body)
        )
        assert stale.status_code == 401
        tampered = body.replace(b"log_01", b"exec_01")
        forged = post(
            tampered, webhooks.sign(secret.encode(), timestamp=now, delivery_id=delivery_id, body=body)
        )
        assert forged.status_code == 401
        wrong = post(
            body, webhooks.sign(b"whsec_not-the-secret", timestamp=now, delivery_id=delivery_id, body=body)
        )
        assert wrong.status_code == 401
        assert len(out.read_text(encoding="utf-8").splitlines()) == 1
    finally:
        consumer.terminate()
        consumer.wait(10)


def test_read_only_token_gets_nothing_it_is_not_scoped_for(db: Db, api: str) -> None:
    admin = httpx.Client(base_url=api)
    admin.post("/api/auth/login", json={"user_id": "admin_01", "password": db.password})
    created = admin.post(
        "/api/admin/tokens",
        json={
            "name": "Tamsworth outage board",
            "scopes": ["commitments:read"],
            "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        },
        headers={"X-CSRF-Token": admin.cookies["sgw_csrf"]},
    )
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    bearer = {"Authorization": f"Bearer {token}"}
    assert httpx.get(f"{api}/v1/decisions", headers=bearer).status_code == 403
    assert httpx.get(f"{api}/v1/events?types=DecisionApproved", headers=bearer).status_code == 403
    assert (
        httpx.post(
            f"{api}/v1/webhooks", json={"url": HOOK, "event_types": ["CommitmentDrifted"]}, headers=bearer
        ).status_code
        == 403
    )
    approve = httpx.post(
        f"{api}/api/proposals/{golden.PROPOSAL_CREWS}/approvals",
        json={"decision": "approve", "proposal_version": 1, "action_hash": "0" * 64},
        headers=bearer,
    )
    assert approve.status_code == 401
