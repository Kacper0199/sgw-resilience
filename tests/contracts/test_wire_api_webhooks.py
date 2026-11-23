from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from sgw.contracts import webhooks
from sgw.contracts.api_models import ENDPOINTS, SCHEMA_MODELS, openapi_document
from sgw.contracts.eventlog import EventLogLine, read_eventlog, write_eventlog
from sgw.contracts.wire import SseId, WireEvent, WireFrame, decode_stream

REPO_ROOT = Path(__file__).resolve().parents[2]
STREAMS = sorted((REPO_ROOT / "contracts" / "golden" / "streams").glob("*.sse"))


@pytest.mark.parametrize("path", STREAMS, ids=lambda p: p.name)
def test_golden_streams_decode_and_ids_are_ordered(path: Path) -> None:
    frames = decode_stream(path.read_text(encoding="utf-8"))
    assert frames
    last: dict[tuple[str, int], int] = {}
    for sse_id, frame in frames:
        key = (sse_id.stream, sse_id.epoch)
        assert sse_id.seq >= last.get(key, -1)
        last[key] = sse_id.seq
        if frame.type is WireEvent.LEDGER:
            assert frame.ledger_seq == sse_id.seq


def test_ops_stream_carries_the_hinge() -> None:
    frames = decode_stream((REPO_ROOT / "contracts/golden/streams/ops_ps17_hinge.sse").read_text())
    kinds = [f.payload.get("event_type") for _, f in frames if f.type is WireEvent.LEDGER]
    assert "ProposalUpdated" in kinds and "DecisionClockUpdated" in kinds
    assert any(f.type is WireEvent.RESYNC for _, f in frames)
    assert frames[0][1].type is WireEvent.HEARTBEAT


def test_run_stream_has_lifecycle_and_pauses_for_approval() -> None:
    frames = [
        f
        for _, f in decode_stream(
            (REPO_ROOT / "contracts/golden/streams/run_ps17_water_continuity.sse").read_text()
        )
    ]
    assert frames[0].type is WireEvent.RUN_START and frames[-1].type is WireEvent.RUN_END
    assert WireEvent.RUN_PAUSED in {f.type for f in frames}
    approval = next(f for f in frames if f.type is WireEvent.APPROVAL_REQUIRED)
    assert re.fullmatch(r"[0-9a-f]{64}", approval.payload["action_hash"])
    text = "".join(f.payload["text"] for f in frames if f.type is WireEvent.TEXT_DELTA)
    from sgw.agent.render.verify import asset_registry
    from sgw.contracts.evidence import verify_text

    registry = asset_registry()
    text = " ".join(" " if token.strip(".,;:") in registry else token for token in text.split(" "))
    assert verify_text(text, {"E1", "E2"}) == []


def test_sse_id_round_trip_and_rejects_garbage() -> None:
    assert SseId.parse("run:abc_1.3.17").render() == "run:abc_1.3.17"
    for bad in ("ops.1", "ops.x.1", "foo.1.1", "run:.1.1"):
        with pytest.raises(ValueError):
            SseId.parse(bad)


def test_ledger_frame_without_ledger_seq_rejected() -> None:
    with pytest.raises(ValidationError):
        WireFrame(
            type=WireEvent.LEDGER, seq=1, ts="2026-11-20T00:00:00Z", run_mode="replay", classification="C1"
        )


def test_openapi_is_complete_and_unique() -> None:
    doc = openapi_document()
    ops = [ep.operation_id for ep in ENDPOINTS]
    assert len(ops) == len(set(ops))
    pairs = [(ep.method, ep.path) for ep in ENDPOINTS]
    assert len(pairs) == len(set(pairs))
    schemas = doc["components"]["schemas"]
    for ep in ENDPOINTS:
        for name in (ep.request, ep.response):
            if name:
                assert name in schemas, name
    required = {
        ("POST", "/api/proposals/{proposal_id}/break-glass"),
        ("GET", "/api/proposals/{proposal_id}/clock"),
        ("GET", "/api/policies"),
        ("GET", "/api/readiness"),
        ("POST", "/api/proposals/{proposal_id}/approvals"),
    }
    assert required <= set(pairs)
    approvals = doc["paths"]["/api/proposals/{proposal_id}/approvals"]["post"]["responses"]
    assert {"409", "412"} <= set(approvals)
    assert all(ep.auth == "api_token" for ep in ENDPOINTS if ep.path.startswith("/v1/"))
    assert {m.__name__ for m in SCHEMA_MODELS} <= set(schemas)


def test_committed_openapi_matches() -> None:
    committed = json.loads((REPO_ROOT / "contracts" / "openapi.json").read_text())
    assert committed == json.loads(json.dumps(openapi_document()))


def test_webhook_signature_vector_and_tamper() -> None:
    v = json.loads((REPO_ROOT / "contracts" / "vectors" / "webhook_signature.json").read_text())
    secret, body = v["secret_utf8"].encode(), v["body_utf8"].encode()
    assert (
        webhooks.sign(secret, timestamp=v["timestamp"], delivery_id=v["delivery_id"], body=body)
        == v["header"]
    )
    webhooks.verify(
        secret, header=v["header"], delivery_id=v["delivery_id"], body=body, now=v["timestamp"] + 10
    )
    with pytest.raises(webhooks.SignatureError, match="mismatch"):
        webhooks.verify(
            secret, header=v["header"], delivery_id=v["delivery_id"], body=body + b" ", now=v["timestamp"]
        )
    with pytest.raises(webhooks.SignatureError, match="mismatch"):
        webhooks.verify(secret, header=v["header"], delivery_id="whd_02", body=body, now=v["timestamp"])
    with pytest.raises(webhooks.SignatureError, match="tolerance"):
        webhooks.verify(
            secret, header=v["header"], delivery_id=v["delivery_id"], body=body, now=v["timestamp"] + 301
        )
    with pytest.raises(webhooks.SignatureError, match="malformed"):
        webhooks.verify(secret, header="v1=abc", delivery_id="x", body=body, now=0)


def test_webhook_rotation_accepts_any_listed_secret() -> None:
    old, new, body = b"old-test-key", b"new-test-key", b"{}"
    header = webhooks.sign_rotating([old, new], timestamp=100, delivery_id="d1", body=body)
    assert header.count("v1=") == 2
    webhooks.verify(old, header=header, delivery_id="d1", body=body, now=100)
    webhooks.verify(new, header=header, delivery_id="d1", body=body, now=100)
    with pytest.raises(webhooks.SignatureError, match="mismatch"):
        webhooks.verify(b"other-test-key", header=header, delivery_id="d1", body=body, now=100)
    with pytest.raises(webhooks.SignatureError, match="malformed"):
        webhooks.verify(old, header="t=1,t=2,v1=ab", delivery_id="d1", body=body, now=1)


def test_approval_required_payload_uses_enums() -> None:
    from sgw.contracts.wire import ApprovalRequiredPayload

    with pytest.raises(ValidationError):
        ApprovalRequiredPayload(
            proposal_id="p",
            proposal_version=1,
            action_hash="0" * 64,
            tier="T9",
            functions_required=["command"],
        )
    with pytest.raises(ValidationError):
        ApprovalRequiredPayload(
            proposal_id="p",
            proposal_version=1,
            action_hash="0" * 64,
            tier="T3",
            functions_required=["janitor"],
        )


def test_eventlog_round_trip(tmp_path: Path) -> None:
    frames = decode_stream((REPO_ROOT / "contracts/golden/streams/run_ps17_water_continuity.sse").read_text())
    lines = [EventLogLine(id=i.render(), delay_ms=40, frame=f) for i, f in frames]
    path = tmp_path / "bookmark.jsonl"
    write_eventlog(
        path,
        {
            "eventlog": "ps17",
            "schema_version": 1,
            "bookmark": "H0-24",
            "graph": "water_continuity",
            "graph_version": "0.1",
            "captured_at": "2026-11-20T00:00:00Z",
            "source_run_id": "run_ps17_water_continuity_01",
            "licence": "Apache-2.0",
        },
        lines,
    )
    header, back = read_eventlog(path)
    assert back == lines and header.bookmark == "H0-24"
    path.write_text(path.read_text().replace('"delay_ms":40', '"delay_ms":41', 1))
    with pytest.raises(ValueError, match="sha256"):
        read_eventlog(path)


def test_route_exists_helper_against_a_fastapi_app() -> None:
    from fastapi import FastAPI

    from sgw.contracts.api_models import missing_routes

    app = FastAPI()

    @app.get("/api/proposals/{proposal_id}/clock")
    def clock(proposal_id: str) -> dict[str, str]:
        return {"id": proposal_id}

    served = {(m, r.path) for r in app.routes for m in getattr(r, "methods", set())}
    missing = missing_routes(served, prefixes=("/api/proposals",))
    assert "GET /api/proposals/{proposal_id}/clock" not in missing
    assert "POST /api/proposals/{proposal_id}/break-glass" in missing
