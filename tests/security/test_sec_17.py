"""SEC-17 (STM 6.4.1-2, NFR-SE-04): one person cannot approve twice, and two people from the same function
do not make a T3 pair; the proposal stays pending. Checked with the reference policy and OPA, and with the
policy switched off to prove the database uniqueness rules hold on their own."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from sgw.approval import testkit as tk
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
        with psycopg.connect(url, autocommit=True) as conn:
            tk.add_user(conn, "ic_02", ["command"])
            tk.add_user(conn, "dual_01", ["command", "logistics"])
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


def _new(client: Any) -> tuple[str, dict[str, Any]]:
    card = client.post(
        "/api/proposals", json=tk.crew_request().model_dump(mode="json"), headers=_h("ops_dm_01")
    ).json()
    body = {"decision": "approve", "proposal_version": 1, "action_hash": card["action_hash"]}
    return f"/api/proposals/{card['proposal_id']}", body


def _state(client: Any, url: str) -> tuple[str, list[str]]:
    card = client.get(url, headers=_h("audit_01")).json()
    return card["state"], sorted(a["approver_id"] for a in card["approvals"])


def test_same_person_cannot_approve_twice(db_url: str, svc: ApprovalService) -> None:
    with tk.api_client(db_url, svc) as (client, _):
        url, body = _new(client)
        assert client.post(f"{url}/approvals", json=body, headers=_h("ic_01")).status_code == 200
        again = client.post(f"{url}/approvals", json=body, headers=_h("ic_01"))
        assert again.status_code == 403
        assert _state(client, url) == ("in_review", ["ic_01"])


def test_one_person_holding_both_functions_cannot_complete_t3(db_url: str, svc: ApprovalService) -> None:
    with tk.api_client(db_url, svc) as (client, _):
        url, body = _new(client)
        first = client.post(f"{url}/approvals", json=body, headers=_h("dual_01"))
        assert first.json()["proposal_state"] == "in_review"
        second = client.post(f"{url}/approvals", json=body, headers=_h("dual_01"))
        assert second.status_code == 403
        assert "approver_already_signed" in second.json()["error"]["details"]["deny"]
        assert _state(client, url) == ("in_review", ["dual_01"])


def test_two_people_from_the_same_function_stay_pending(db_url: str, svc: ApprovalService) -> None:
    with tk.api_client(db_url, svc) as (client, _):
        url, body = _new(client)
        client.post(f"{url}/approvals", json=body, headers=_h("ic_01"))
        same = client.post(f"{url}/approvals", json=body, headers=_h("ic_02"))
        assert same.status_code == 403
        assert set(same.json()["error"]["details"]["deny"]) >= {"function_already_signed"}
        assert _state(client, url) == ("in_review", ["ic_01"])
        pair = client.post(f"{url}/approvals", json=body, headers=_h("log_01"))
        assert pair.json() | {"approval_id": None} == {
            "approval_id": None,
            "proposal_state": "approved",
            "remaining_functions": [],
        }


def test_database_uniqueness_holds_when_policy_is_bypassed(db_url: str) -> None:
    bypass = tk.service_for("permissive", None, tk.MutableClock(START))
    assert bypass is not None
    with tk.api_client(db_url, bypass) as (client, _):
        url, body = _new(client)
        assert client.post(f"{url}/approvals", json=body, headers=_h("ic_01")).status_code == 200
        twice = client.post(f"{url}/approvals", json=body, headers=_h("ic_01"))
        same_fn = client.post(f"{url}/approvals", json=body, headers=_h("ic_02"))
        assert (twice.status_code, same_fn.status_code) == (409, 409)
        assert twice.json()["error"]["details"]["sqlstate"] == "23505"
        assert _state(client, url) == ("in_review", ["ic_01"])
        with psycopg.connect(db_url) as conn:
            token = tk.repo_token(conn, url.rsplit("/", 1)[1])
        assert token is None
