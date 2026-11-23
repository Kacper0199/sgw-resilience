"""SEC-16 (STM 6.4.1, NFR-SE-04): the initiator cannot approve their own action. Checked through the HTTP
route with the Python reference policy and with OPA, and once with the policy switched off to prove the
database trigger refuses on its own (SQLSTATE 42501 -> 403)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest

from sgw.approval import testkit as tk
from sgw.approval.policy import OpaPolicy, ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.contracts import golden

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
NO_OPA = "no OPA: set SGW_TEST_OPA_URL or start docker"
START = golden.ADVISORY_N.issued + timedelta(minutes=10)


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with tk.seeded_database() as url:
        yield url


@pytest.fixture(scope="module")
def opa_url() -> Iterator[str | None]:
    with tk.opa_server() as url:
        yield url


@pytest.fixture(params=["reference", "opa"])
def svc(request: pytest.FixtureRequest, opa_url: str | None) -> ApprovalService:
    service = tk.service_for(request.param, opa_url, tk.MutableClock(START))
    if service is None:
        pytest.skip(NO_OPA)  # sgw-allow-skip: needs docker
    return service


def _h(user: str) -> dict[str, str]:
    return {tk.TEST_USER_HEADER: user}


def test_proposer_cannot_approve_own_t3_proposal(db_url: str, svc: ApprovalService) -> None:
    with tk.api_client(db_url, svc) as (client, _):
        card = client.post(
            "/api/proposals", json=tk.crew_request().model_dump(mode="json"), headers=_h("ops_dm_01")
        ).json()
        body = {"decision": "approve", "proposal_version": 1, "action_hash": card["action_hash"]}
        own = client.post(
            f"/api/proposals/{card['proposal_id']}/approvals", json=body, headers=_h("ops_dm_01")
        )
        assert own.status_code == 403
        assert "self_approval" in own.json()["error"]["details"]["deny"]
        after = client.get(f"/api/proposals/{card['proposal_id']}", headers=_h("ops_dm_01")).json()
        assert after["state"] == "proposed" and after["approvals"] == []


def test_seeded_helene_proposal_refuses_its_proposer(db_url: str, svc: ApprovalService) -> None:
    with tk.api_client(db_url, svc) as (client, _):
        card = client.get(f"/api/proposals/{golden.PROPOSAL_CREWS}", headers=_h("ops_dm_01")).json()
        body = {"decision": "approve", "proposal_version": 1, "action_hash": card["action_hash"]}
        own = client.post(
            f"/api/proposals/{golden.PROPOSAL_CREWS}/approvals", json=body, headers=_h("ops_dm_01")
        )
        assert own.status_code == 403


def test_t2_proposer_is_not_the_single_approver(db_url: str, svc: ApprovalService) -> None:
    with tk.api_client(db_url, svc) as (client, _):
        card = client.post(
            "/api/proposals", json=tk.staging_request().model_dump(mode="json"), headers=_h("ops_dm_01")
        ).json()
        assert card["tier"] == "T2" and card["functions_required"] == ["operations"]
        body = {"decision": "approve", "proposal_version": 1, "action_hash": card["action_hash"]}
        url = f"/api/proposals/{card['proposal_id']}/approvals"
        assert client.post(url, json=body, headers=_h("ops_dm_01")).status_code == 403
        other = client.post(url, json=body, headers=_h("ops_dm_02"))
        assert other.status_code == 200 and other.json()["proposal_state"] == "approved"


def test_database_refuses_self_approval_when_policy_is_bypassed(db_url: str) -> None:
    bypass = tk.service_for("permissive", None, tk.MutableClock(START))
    assert bypass is not None
    with tk.api_client(db_url, bypass) as (client, _):
        card = client.post(
            "/api/proposals", json=tk.crew_request().model_dump(mode="json"), headers=_h("ops_dm_01")
        ).json()
        body = {"decision": "approve", "proposal_version": 1, "action_hash": card["action_hash"]}
        own = client.post(
            f"/api/proposals/{card['proposal_id']}/approvals", json=body, headers=_h("ops_dm_01")
        )
        assert own.status_code == 403
        assert own.json()["error"]["code"] == "DB_AUTHORITY_DENIED"
        assert own.json()["error"]["details"]["sqlstate"] == "42501"


def test_agent_counts_as_initiator_for_the_requesting_user(opa_url: str | None) -> None:
    payload = {
        "action": "approve",
        "subject": {"user_id": "ic_01", "functions": ["command"], "can_approve": True, "on_shift": True},
        "proposal": {
            "action_type": "preposition_crews",
            "proposed_by": "ic_01",
            "requested_by": "ic_01",
            "initiator_kind": "agent",
            "target_ids": list(tk.YARDS),
            "tier": "T3",
            "required_functions": ["command", "logistics"],
            "state": "proposed",
            "expires_at_ns": None,
        },
        "context": {"degraded_mode": "M0", "now_ns": 0},
        "approval": {"decision": "approve", "function": "command", "evidence_oldest_age_s": None},
        "approvals": [],
    }
    engines = [ReferencePolicy()] + ([OpaPolicy(opa_url, allow_load=True)] if opa_url else [])
    for engine in engines:
        if isinstance(engine, OpaPolicy):
            engine.load()
        decision = engine.approve(payload)
        assert not decision.allow and "initiator_approval" in decision.deny
