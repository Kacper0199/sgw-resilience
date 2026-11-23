from __future__ import annotations

import json
from typing import Any

import argon2
import psycopg
import pytest

from sgw.approval import testkit as tk
from sgw.approval.seed import REPO_ROOT, run_seed
from sgw.approval.service import ApprovalService
from sgw.contracts import golden
from sgw.contracts.api_models import ENDPOINTS, ProposalCard, StaleProposal, missing_routes


def _h(user: str, **extra: str) -> dict[str, str]:
    return {tk.TEST_USER_HEADER: user, **extra}


def test_router_serves_every_proposal_route_but_break_glass() -> None:
    from fastapi import FastAPI

    from sgw.api.routers.evidence import router as evidence
    from sgw.api.routers.proposals import router

    app = FastAPI()
    app.include_router(router)
    app.include_router(evidence)
    paths = app.openapi()["paths"]
    served = {(method.upper(), path) for path, item in paths.items() for method in item}
    assert missing_routes(served, prefixes=("/api/proposals",)) == [
        "POST /api/proposals/{proposal_id}/break-glass",
        "POST /api/proposals/{proposal_id}/cosign",
    ]
    from sgw.api.routers.audit import router as governance

    gov = FastAPI()
    gov.include_router(governance)
    gov_paths = gov.openapi()["paths"]
    assert {"/api/proposals/{proposal_id}/break-glass", "/api/proposals/{proposal_id}/cosign"} <= set(
        gov_paths
    )
    ops = {ep.operation_id for ep in ENDPOINTS if ep.path.startswith("/api/proposals")}
    assert {op["operationId"] for item in paths.values() for op in item.values()} <= ops


def test_http_flow_status_codes_etags_and_events(db_url: str, svc: ApprovalService) -> None:
    with tk.api_client(db_url, svc) as (client, published):
        assert client.get("/api/proposals").status_code == 401
        created = client.post(
            "/api/proposals", json=tk.crew_request().model_dump(mode="json"), headers=_h("ops_dm_01")
        )
        assert created.status_code == 201, created.text
        card = ProposalCard.model_validate(created.json())
        tag = created.headers["ETag"]
        assert tag == f'"1-{card.action_hash}"'
        assert created.headers["Location"] == f"/api/proposals/{card.proposal_id}"
        got = client.get(f"/api/proposals/{card.proposal_id}", headers=_h("audit_01"))
        assert got.status_code == 200 and got.headers["ETag"] == tag
        body = tk.approve_req(card).model_dump(mode="json")
        stale = client.post(
            f"/api/proposals/{card.proposal_id}/approvals",
            json=body,
            headers=_h("ic_01", **{"If-Match": '"0-x"'}),
        )
        assert stale.status_code == 412
        assert StaleProposal.model_validate(stale.json()) == StaleProposal(
            current_version=1, current_action_hash=card.action_hash, changed_fields=[]
        )
        first = client.post(
            f"/api/proposals/{card.proposal_id}/approvals",
            json=body,
            headers=_h("ic_01", **{"If-Match": tag}),
        )
        assert first.status_code == 200 and first.json()["proposal_state"] == "in_review"
        second = client.post(f"/api/proposals/{card.proposal_id}/approvals", json=body, headers=_h("log_01"))
        assert second.json()["proposal_state"] == "approved"
        closed = client.post(
            f"/api/proposals/{card.proposal_id}/approvals", json=body, headers=_h("wtr_lead_01")
        )
        assert closed.status_code == 409 and closed.json()["error"]["code"] == "PROPOSAL_NOT_OPEN"
        listed = client.get("/api/proposals", params={"state": "approved"}, headers=_h("exec_01")).json()
        assert card.proposal_id in {p["proposal_id"] for p in listed}
        clock = client.get(f"/api/proposals/{card.proposal_id}/clock", headers=_h("exec_01"))
        assert clock.status_code == 200 and clock.json()["decision_case_id"] == golden.CASE_CREWS
        assert client.get("/api/proposals/PRP-NOPE", headers=_h("exec_01")).status_code == 404
        assert client.get("/api/proposals/PRP-NOPE/clock", headers=_h("exec_01")).status_code == 404
        kinds = [type(e).__name__ for e in published]
        assert kinds == ["ProposalCreated", "ApprovalRecorded", "ApprovalRecorded", "DecisionApproved"]


def test_http_withdraw_and_policy_denial(db_url: str, svc: ApprovalService) -> None:
    with tk.api_client(db_url, svc) as (client, _):
        denied = client.post(
            "/api/proposals", json=tk.crew_request().model_dump(mode="json"), headers=_h("exec_01")
        )
        assert denied.status_code == 403 and denied.json()["error"]["details"]["deny"] == [
            "proposer_not_allowed"
        ]
        card = client.post(
            "/api/proposals", json=tk.crew_request().model_dump(mode="json"), headers=_h("ops_dm_01")
        ).json()
        out = client.post(
            f"/api/proposals/{card['proposal_id']}/withdraw",
            json={"reason": "advisory moved the track"},
            headers=_h("ops_dm_01"),
        )
        assert out.status_code == 200 and out.json()["state"] == "withdrawn"
        assert out.headers["ETag"] == f'"1-{card["action_hash"]}"'


def test_seed_is_idempotent_and_hashes_the_password(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_PASSWORD", "synthetic-demo-pass")
    report = run_seed(db_url)
    assert report.users == 11 and report.proposal_created is False
    with psycopg.connect(db_url) as conn:
        row: Any = conn.execute("SELECT password_hash FROM app_user WHERE user_id = 'ic_01'").fetchone()
        prop: Any = conn.execute(
            "SELECT action_hash, state, required_functions::text[], proposed_by FROM proposal"
            " WHERE proposal_id = %s",
            (golden.PROPOSAL_CREWS,),
        ).fetchone()
    assert argon2.PasswordHasher().verify(row[0], "synthetic-demo-pass")
    vectors = json.loads((REPO_ROOT / "contracts" / "vectors" / "action_hash.json").read_text())["vectors"]
    crews_v1 = next(v["sha256"] for v in vectors if v["name"] == "crews_v1")
    assert prop == (crews_v1, "proposed", ["command", "logistics"], "ops_dm_01")
    assert report.etag == f'"1-{prop[0]}"'
