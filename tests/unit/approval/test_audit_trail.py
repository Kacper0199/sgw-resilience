"""Every approval state change lands in the hash chain in its own transaction."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from sgw.approval import audit, errors
from sgw.approval import testkit as tk
from sgw.approval.service import ApprovalService, Revision
from sgw.contracts.api_models import WithdrawRequest


def _trail(conn: psycopg.Connection[Any], proposal_id: str) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT kind, actor_id FROM audit_event WHERE subject = %s ORDER BY seq", (proposal_id,)
    ).fetchall()
    return [(str(k), str(a)) for k, a in rows]


def test_create_approve_issue_and_burn_are_audited(
    conn: psycopg.Connection[Any], svc: ApprovalService
) -> None:
    card = tk.new_crew_proposal(conn, svc)
    svc.decide(conn, user_id="ic_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    svc.decide(conn, user_id="log_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    token = tk.repo_token(conn, card.proposal_id)
    assert token is not None
    svc.burn(
        conn,
        token_id=token["token_id"],
        proposal_id=card.proposal_id,
        proposal_version=card.proposal_version,
        action_hash=card.action_hash,
    )
    assert _trail(conn, card.proposal_id) == [
        ("proposal_created", "ops_dm_01"),
        ("approval_recorded", "ic_01"),
        ("approval_recorded", "log_01"),
        ("execution_token_issued", "system:approval"),
        ("execution_token_burned", "system:approval"),
    ]
    payload = conn.execute(
        "SELECT payload FROM audit_event WHERE subject = %s AND kind = 'execution_token_burned'",
        (card.proposal_id,),
    ).fetchone()
    assert payload is not None and payload[0]["token_id"] == token["token_id"]
    assert audit.verify(conn).first_bad_seq is None


def test_revise_and_withdrawals_are_audited(conn: psycopg.Connection[Any], svc: ApprovalService) -> None:
    card = tk.new_crew_proposal(conn, svc)
    svc.decide(conn, user_id="ic_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    svc.withdraw(
        conn, user_id="ic_01", proposal_id=card.proposal_id, request=WithdrawRequest(reason="wrong yard")
    )
    params = dict(card.params)
    first = next(iter(params))
    params[first] = int(params[first]) + 2
    svc.revise(
        conn,
        actor="ops_dm_01",
        proposal_id=card.proposal_id,
        change=Revision(params=params),
        reason="advisory N+1",
    )
    svc.withdraw(
        conn, user_id="ops_dm_01", proposal_id=card.proposal_id, request=WithdrawRequest(reason="superseded")
    )
    kinds = [k for k, _ in _trail(conn, card.proposal_id)]
    assert kinds == [
        "proposal_created",
        "approval_recorded",
        "approval_withdrawn",
        "proposal_revised",
        "proposal_withdrawn",
    ]
    revised = conn.execute(
        "SELECT payload FROM audit_event WHERE subject = %s AND kind = 'proposal_revised'",
        (card.proposal_id,),
    ).fetchone()
    assert revised is not None and revised[0]["material"] is True and revised[0]["proposal_version"] == 2


def test_a_refused_decision_leaves_no_audit_row(conn: psycopg.Connection[Any], svc: ApprovalService) -> None:
    card = tk.new_crew_proposal(conn, svc)
    with pytest.raises(errors.ForbiddenError):
        svc.decide(conn, user_id="ops_dm_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    assert [k for k, _ in _trail(conn, card.proposal_id)] == ["proposal_created"]
