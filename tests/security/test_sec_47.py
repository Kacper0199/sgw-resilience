"""SEC-47 (STM 6.4.4, PA DC-17): a material edit after approval (here: the target set) changes the action
hash and the version, voids every approval and the execution token, and an approval sent for the old
version gets 412 with the changed fields. The database refuses a stale row on its own (SQLSTATE 09000)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from sgw.approval import repository as repo
from sgw.approval import testkit as tk
from sgw.approval.errors import ForbiddenError, PreconditionFailedError, from_db_error
from sgw.approval.service import ApprovalService, Revision
from sgw.contracts import approval as ap
from sgw.contracts import golden
from sgw.contracts.api_models import StaleProposal

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
NO_OPA = "no OPA: set SGW_TEST_OPA_URL or start docker"
START = golden.ADVISORY_N.issued + timedelta(minutes=10)
NEW_YARD = "STG-AIK-WHITEOAK-SIDING"


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with tk.seeded_database() as url:
        with psycopg.connect(url, autocommit=True) as conn:
            tk.add_asset(conn, NEW_YARD)
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


def _h(user: str, **extra: str) -> dict[str, str]:
    return {tk.TEST_USER_HEADER: user, **extra}


def _retarget(conn: psycopg.Connection[Any], svc: ApprovalService, pid: str) -> Any:
    return svc.revise(
        conn,
        actor="system:replan",
        proposal_id=pid,
        change=Revision(target_ids=[golden.YARD_SANDHILL, NEW_YARD]),
        reason="advisory N+1 moved the staging yard",
    )


def test_target_edit_after_first_approval_voids_it_and_412s_the_old_version(
    db_url: str, svc: ApprovalService
) -> None:
    with tk.api_client(db_url, svc) as (client, _), psycopg.connect(db_url, autocommit=True) as conn:
        created = client.post(
            "/api/proposals", json=tk.crew_request().model_dump(mode="json"), headers=_h("ops_dm_01")
        )
        card, v1_tag = created.json(), created.headers["ETag"]
        url = f"/api/proposals/{card['proposal_id']}"
        v1 = {"decision": "approve", "proposal_version": 1, "action_hash": card["action_hash"]}
        assert client.post(f"{url}/approvals", json=v1, headers=_h("ic_01")).status_code == 200
        out = _retarget(conn, svc, card["proposal_id"])
        assert out.value.proposal_version == 2 and out.value.action_hash != card["action_hash"]
        assert out.events[0].material and len(out.events[0].voided_approval_ids) == 1
        voided = conn.execute(
            "SELECT voided_at IS NOT NULL, voided_by_version FROM approval WHERE proposal_id = %s",
            (card["proposal_id"],),
        ).fetchall()
        assert voided == [(True, 2)]
        now = client.get(url, headers=_h("log_01"))
        assert now.json()["state"] == "proposed" and now.json()["approvals"] == []
        assert now.headers["ETag"] == f'"2-{out.value.action_hash}"'
        stale = client.post(f"{url}/approvals", json=v1, headers=_h("log_01"))
        assert stale.status_code == 412
        details = StaleProposal.model_validate(stale.json())
        assert details.current_version == 2 and details.current_action_hash == out.value.action_hash
        assert "target_ids" in details.changed_fields
        v2 = {"decision": "approve", "proposal_version": 2, "action_hash": out.value.action_hash}
        by_tag = client.post(f"{url}/approvals", json=v2, headers=_h("log_01", **{"If-Match": v1_tag}))
        assert by_tag.status_code == 412
        fresh = client.post(f"{url}/approvals", json=v2, headers=_h("log_01"))
        assert fresh.json()["proposal_state"] == "in_review"


def test_edit_after_full_approval_revokes_the_execution_token(db_url: str, svc: ApprovalService) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        card = tk.new_crew_proposal(conn, svc)
        for user in ("ic_01", "log_01"):
            svc.decide(conn, user_id=user, proposal_id=card.proposal_id, request=tk.approve_req(card))
        token = tk.repo_token(conn, card.proposal_id)
        assert token is not None
        out = _retarget(conn, svc, card.proposal_id)
        assert out.value.state.value == "proposed" and tk.repo_token(conn, card.proposal_id) is None
        with pytest.raises(ForbiddenError):
            svc.burn(
                conn,
                token_id=token["token_id"],
                proposal_id=card.proposal_id,
                proposal_version=1,
                action_hash=card.action_hash,
            )
        with pytest.raises(PreconditionFailedError):
            svc.decide(conn, user_id="log_01", proposal_id=card.proposal_id, request=tk.approve_req(card))


def test_hash_covers_the_target_set_and_crew_counts() -> None:
    base = golden.crew_material(14, 9)
    moved = base.model_copy(update={"target_ids": [golden.YARD_SANDHILL, NEW_YARD]})
    recounted = golden.crew_material(18, 9)
    hashes = {ap.action_hash(m, golden.POLICY_VERSION) for m in (base, moved, recounted)}
    assert len(hashes) == 3
    assert ap.material_diff(base, recounted) == ["params"]


def test_database_rejects_a_stale_approval_row(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        svc = tk.service_for("reference", None, tk.MutableClock(START))
        assert svc is not None
        card = tk.new_crew_proposal(conn, svc)
        _retarget(conn, svc, card.proposal_id)
        row = {
            "approval_id": "APR-SEC47-STALE",
            "proposal_id": card.proposal_id,
            "proposal_version": 1,
            "action_hash": card.action_hash,
            "approver_id": "ic_01",
            "function": "command",
            "decision": "approve",
            "reason_code": None,
            "note": None,
            "snapshot_id_seen": None,
            "evidence_oldest_age_s": None,
        }
        with pytest.raises(psycopg.Error) as raised:
            repo.insert_approval(conn, row)
        mapped = from_db_error(raised.value)
        assert raised.value.sqlstate == "09000"
        assert isinstance(mapped, PreconditionFailedError) and mapped.status_code == 412
