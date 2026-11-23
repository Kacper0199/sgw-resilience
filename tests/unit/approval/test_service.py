from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from sgw.approval import testkit as tk
from sgw.approval.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    PolicyUnavailableError,
    PreconditionFailedError,
    UnprocessableError,
)
from sgw.approval.policy import OpaPolicy
from sgw.approval.service import ApprovalService, Revision, etag
from sgw.contracts import approval as ap
from sgw.contracts import golden
from sgw.contracts.api_models import WithdrawRequest
from sgw.contracts.vocab import ActionType, ProposalState, RiskBand, Tier

from .conftest import START

Conn = psycopg.Connection[Any]


def _approve_both(conn: Conn, svc: ApprovalService, pid: str) -> None:
    card = svc.card(conn, pid)
    svc.decide(conn, user_id="ic_01", proposal_id=pid, request=tk.approve_req(card))
    svc.decide(conn, user_id="log_01", proposal_id=pid, request=tk.approve_req(card))


def test_create_t3_uses_policy_tier_functions_and_hash(conn: Conn, svc: ApprovalService) -> None:
    out = svc.create(conn, proposed_by="ops_dm_01", request=tk.crew_request(12, 8))
    card = out.value
    assert card.tier is Tier.T3 and card.state is ProposalState.PROPOSED
    assert [f.value for f in card.functions_required] == ["command", "logistics"]
    assert card.proposal_version == 1 and out.etag == etag(1, card.action_hash)
    material = ap.MaterialFields(
        action_type=ActionType.PREPOSITION_CREWS,
        params=card.params,
        target_ids=card.target_ids,
        risk_band=RiskBand.MODERATE,
        preconditions={},
        tier=Tier.T3,
        escalators=["hazard_zone_entry"],
    )
    assert card.escalators == ["hazard_zone_entry"]
    assert card.action_hash == ap.action_hash(material, golden.POLICY_VERSION)
    assert card.expires_at == START + timedelta(minutes=ap.TIER_TTL_MIN[Tier.T3])
    assert [type(e).__name__ for e in out.events] == ["ProposalCreated"]


def test_unlisted_proposer_and_unknown_case_are_refused(conn: Conn, svc: ApprovalService) -> None:
    with pytest.raises(ForbiddenError) as denied:
        svc.create(conn, proposed_by="log_01", request=tk.crew_request())
    assert denied.value.details["deny"] == ["proposer_not_allowed"]
    bad = tk.crew_request().model_copy(update={"decision_case_id": "DC-NOPE"})
    with pytest.raises(NotFoundError):
        svc.create(conn, proposed_by="ops_dm_01", request=bad)


def test_t2_staging_escalates_to_t3_on_customer_count(conn: Conn, svc: ApprovalService) -> None:
    small = svc.create(conn, proposed_by="ops_dm_01", request=tk.staging_request(400)).value
    big = svc.create(conn, proposed_by="ops_dm_01", request=tk.staging_request(1000)).value
    assert small.tier is Tier.T2 and [f.value for f in small.functions_required] == ["operations"]
    assert big.tier is Tier.T3 and [f.value for f in big.functions_required] == ["command", "logistics"]
    assert big.escalators == ["customers_ge_limit"]


def test_unknown_targets_are_refused(conn: Conn, svc: ApprovalService) -> None:
    with pytest.raises(UnprocessableError) as bad:
        svc.create(conn, proposed_by="ops_dm_01", request=tk.staging_request(target="STG-NOWHERE"))
    assert bad.value.code == "UNKNOWN_TARGET" and bad.value.details["target_ids"] == ["STG-NOWHERE"]


@pytest.mark.parametrize(
    ("asset_id", "zone", "customers", "escalator"),
    [
        ("STG-AIK-FOGBOW-YARD", None, 0, "hazard_zone_entry"),
        ("STG-AIK-HOLLOWREED-YARD", True, 0, "hazard_zone_entry"),
        ("STG-AIK-PINEKNOT-YARD", False, None, "customers_unknown"),
    ],
)
def test_missing_or_hazard_facts_escalate_t2_fail_closed(
    conn: Conn, svc: ApprovalService, asset_id: str, zone: bool | None, customers: int | None, escalator: str
) -> None:
    tk.add_asset(conn, asset_id, in_hazard_zone=zone, customers=customers)
    card = svc.create(conn, proposed_by="ops_dm_01", request=tk.staging_request(10, target=asset_id)).value
    assert card.tier is Tier.T3 and card.escalators == [escalator]


def test_seeded_yards_have_no_zone_data_so_staging_there_is_t3(conn: Conn, svc: ApprovalService) -> None:
    card = svc.create(
        conn, proposed_by="ops_dm_01", request=tk.staging_request(10, target=golden.YARD_SANDHILL)
    ).value
    assert card.tier is Tier.T3 and card.escalators == ["hazard_zone_entry"]


def test_crew_targets_count_as_hazard_zone_entry(conn: Conn, svc: ApprovalService) -> None:
    conn.execute(
        "INSERT INTO crew (crew_id, region_id, headcount) VALUES ('CRW-OSPREY-04', %s, 4)"
        " ON CONFLICT DO NOTHING",
        (golden.REGION_AIKEN,),
    )
    card = svc.create(
        conn, proposed_by="ops_dm_01", request=tk.staging_request(10, target="CRW-OSPREY-04")
    ).value
    assert "hazard_zone_entry" in card.escalators and card.tier is Tier.T3


def test_t3_flow_in_review_then_approved_with_token(conn: Conn, svc: ApprovalService) -> None:
    card = tk.new_crew_proposal(conn, svc)
    first = svc.decide(conn, user_id="ic_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    assert first.value.proposal_state is ProposalState.IN_REVIEW
    assert [f.value for f in first.value.remaining_functions] == ["logistics"]
    assert tk.repo_token(conn, card.proposal_id) is None
    second = svc.decide(conn, user_id="log_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    assert second.value.proposal_state is ProposalState.APPROVED and second.value.remaining_functions == []
    assert {type(e).__name__ for e in second.events} == {"ApprovalRecorded", "DecisionApproved"}
    token = tk.repo_token(conn, card.proposal_id)
    assert token is not None and token["action_hash"] == card.action_hash
    approvers = {a.approver_id for a in svc.card(conn, card.proposal_id).approvals}
    assert approvers == {"ic_01", "log_01"}


def test_reject_closes_and_later_decisions_conflict(conn: Conn, svc: ApprovalService) -> None:
    card = tk.new_crew_proposal(conn, svc)
    out = svc.decide(
        conn, user_id="log_01", proposal_id=card.proposal_id, request=tk.approve_req(card, "reject")
    )
    assert out.value.proposal_state is ProposalState.REJECTED
    with pytest.raises(ConflictError) as closed:
        svc.decide(conn, user_id="ic_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    assert closed.value.code == "PROPOSAL_NOT_OPEN"


def test_if_match_star_and_mismatch(conn: Conn, svc: ApprovalService) -> None:
    card = tk.new_crew_proposal(conn, svc)
    with pytest.raises(PreconditionFailedError):
        svc.decide(
            conn,
            user_id="ic_01",
            proposal_id=card.proposal_id,
            request=tk.approve_req(card),
            if_match='"9-x"',
        )
    ok = svc.decide(
        conn, user_id="ic_01", proposal_id=card.proposal_id, request=tk.approve_req(card), if_match="*"
    )
    assert ok.value.proposal_state is ProposalState.IN_REVIEW


def test_expired_proposal_is_marked_and_conflicts(
    conn: Conn, svc: ApprovalService, clock: tk.MutableClock
) -> None:
    card = tk.new_crew_proposal(conn, svc)
    clock.advance(minutes=ap.TIER_TTL_MIN[Tier.T3])
    with pytest.raises(ConflictError) as late:
        svc.decide(conn, user_id="ic_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    assert late.value.code == "PROPOSAL_EXPIRED"
    assert svc.card(conn, card.proposal_id).state is ProposalState.EXPIRED


def test_withdraw_rules(conn: Conn, svc: ApprovalService) -> None:
    card = tk.new_crew_proposal(conn, svc)
    with pytest.raises(ForbiddenError):
        svc.withdraw(
            conn, user_id="exec_01", proposal_id=card.proposal_id, request=WithdrawRequest(reason="not mine")
        )
    out = svc.withdraw(
        conn, user_id="ops_dm_01", proposal_id=card.proposal_id, request=WithdrawRequest(reason="track moved")
    )
    assert out.value.state is ProposalState.WITHDRAWN
    with pytest.raises(ConflictError):
        svc.withdraw(
            conn, user_id="ops_dm_01", proposal_id=card.proposal_id, request=WithdrawRequest(reason="again")
        )
    approved = tk.new_crew_proposal(conn, svc)
    _approve_both(conn, svc, approved.proposal_id)
    for who in ("log_01", "ops_dm_01"):
        with pytest.raises(ConflictError) as rescind:
            svc.withdraw(
                conn, user_id=who, proposal_id=approved.proposal_id, request=WithdrawRequest(reason="hold")
            )
        assert rescind.value.code == "RESCIND_NEEDS_T3"
    assert tk.repo_token(conn, approved.proposal_id) is not None


def test_approver_withdraws_only_their_own_signature_before_approval(
    conn: Conn, svc: ApprovalService
) -> None:
    card = tk.new_crew_proposal(conn, svc)
    with pytest.raises(ForbiddenError):
        svc.withdraw(
            conn, user_id="log_01", proposal_id=card.proposal_id, request=WithdrawRequest(reason="none")
        )
    svc.decide(conn, user_id="ic_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    out = svc.withdraw(
        conn, user_id="ic_01", proposal_id=card.proposal_id, request=WithdrawRequest(reason="new info")
    )
    assert out.value.state is ProposalState.PROPOSED and out.value.approvals == []
    assert out.events[0].changed_fields == ["approvals"]  # type: ignore[attr-defined]
    again = svc.decide(conn, user_id="ic_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    assert again.value.proposal_state is ProposalState.IN_REVIEW


def test_proposer_may_withdraw_an_approved_t2(conn: Conn, svc: ApprovalService) -> None:
    card = svc.create(conn, proposed_by="ops_dm_01", request=tk.staging_request()).value
    svc.decide(conn, user_id="ops_dm_02", proposal_id=card.proposal_id, request=tk.approve_req(card))
    out = svc.withdraw(
        conn, user_id="ops_dm_01", proposal_id=card.proposal_id, request=WithdrawRequest(reason="stand down")
    )
    assert out.value.state is ProposalState.WITHDRAWN and tk.repo_token(conn, card.proposal_id) is None


def test_token_burns_once_and_only_bound_to_version_and_hash(
    conn: Conn, svc: ApprovalService, token_clock: tk.MutableClock
) -> None:
    card = tk.new_crew_proposal(conn, svc)
    _approve_both(conn, svc, card.proposal_id)
    token = tk.repo_token(conn, card.proposal_id)
    assert token is not None
    kw = {"token_id": token["token_id"], "proposal_id": card.proposal_id}
    with pytest.raises(PreconditionFailedError) as stale:
        svc.burn(conn, **kw, proposal_version=2, action_hash=card.action_hash)
    assert stale.value.code == "TOKEN_STALE"
    with pytest.raises(PreconditionFailedError):
        svc.burn(conn, **kw, proposal_version=1, action_hash="0" * 64)
    effect = svc.burn(conn, **kw, proposal_version=1, action_hash=card.action_hash)
    assert effect == f"EFF-{card.proposal_id}"
    assert svc.card(conn, card.proposal_id).state is ProposalState.EXECUTED
    with pytest.raises(ConflictError) as again:
        svc.burn(conn, **kw, proposal_version=1, action_hash=card.action_hash)
    assert again.value.code == "TOKEN_BURNED"


def test_token_expires_after_60_s_and_can_be_reissued(
    conn: Conn, svc: ApprovalService, token_clock: tk.MutableClock
) -> None:
    card = tk.new_crew_proposal(conn, svc)
    _approve_both(conn, svc, card.proposal_id)
    old = tk.repo_token(conn, card.proposal_id)
    assert old is not None
    token_clock.advance(seconds=60)
    with pytest.raises(ConflictError) as expired:
        svc.burn(
            conn,
            token_id=old["token_id"],
            proposal_id=card.proposal_id,
            proposal_version=1,
            action_hash=card.action_hash,
        )
    assert expired.value.code == "TOKEN_EXPIRED"
    fresh = svc.reissue_token(conn, card.proposal_id)
    with pytest.raises(ForbiddenError):
        svc.burn(
            conn,
            token_id=old["token_id"],
            proposal_id=card.proposal_id,
            proposal_version=1,
            action_hash=card.action_hash,
        )
    svc.burn(
        conn, token_id=fresh, proposal_id=card.proposal_id, proposal_version=1, action_hash=card.action_hash
    )


def test_non_material_revision_keeps_version_and_approvals(conn: Conn, svc: ApprovalService) -> None:
    card = tk.new_crew_proposal(conn, svc)
    svc.decide(conn, user_id="ic_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    out = svc.revise(
        conn,
        actor="system:replan",
        proposal_id=card.proposal_id,
        change=Revision(rationale="Wording"),
        reason="text",
    )
    assert out.value.proposal_version == 1 and out.value.action_hash == card.action_hash
    assert out.value.rationale == "Wording" and len(out.value.approvals) == 1
    assert out.events[0].material is False  # type: ignore[attr-defined]


def test_evidence_retraction_is_material_and_persists(conn: Conn, svc: ApprovalService) -> None:
    card = tk.new_crew_proposal(conn, svc)
    out = svc.revise(
        conn,
        actor="system:replan",
        proposal_id=card.proposal_id,
        change=Revision(retracted_evidence_ids=["EV-ADV-HELENE-N"]),
        reason="advisory retracted",
    )
    assert out.value.proposal_version == 2 and out.value.evidence_ids == []
    again = svc.revise(
        conn,
        actor="system:replan",
        proposal_id=card.proposal_id,
        change=Revision(rationale="x"),
        reason="text",
    )
    assert again.value.proposal_version == 2 and again.value.action_hash == out.value.action_hash


def test_list_card_and_clock(conn: Conn, svc: ApprovalService) -> None:
    latest = conn.execute(
        "SELECT proposal_id FROM proposal WHERE decision_case_id = %s AND action_type = 'preposition_crews'"
        " AND state NOT IN ('withdrawn', 'rejected') ORDER BY created_at DESC, proposal_id DESC LIMIT 1",
        (golden.CASE_CREWS,),
    ).fetchone()
    assert latest is not None
    listed = [s.proposal_id for s in svc.summaries(conn) if s.decision_case_id == golden.CASE_CREWS]
    assert latest[0] in listed
    assert (
        sum(s.action_type == "preposition_crews" for s in svc.summaries(conn) if s.proposal_id in listed) == 1
    )
    clock = svc.clock(conn, golden.PROPOSAL_CREWS)
    expected = golden.crews_clock(golden.ADVISORY_N)
    assert clock.decide_by_utc == expected.decide_by_utc
    assert clock.consequence_range_utc == (expected.consequence_p10_utc, expected.consequence_p90_utc)
    with pytest.raises(NotFoundError):
        svc.card(conn, "PRP-NOPE")


def test_policy_outage_fails_closed(conn: Conn, clock: tk.MutableClock) -> None:
    dead = ApprovalService(OpaPolicy("http://127.0.0.1:9", timeout_s=0.2), scenario_clock=clock)
    with pytest.raises(PolicyUnavailableError):
        dead.create(conn, proposed_by="ops_dm_01", request=tk.crew_request())


def test_expire_due_sweeps_open_proposals(conn: Conn, svc: ApprovalService, clock: tk.MutableClock) -> None:
    card = tk.new_crew_proposal(conn, svc)
    clock.advance(hours=3)
    assert card.proposal_id in svc.expire_due(conn)


def test_database_binds_tokens_to_an_approved_version(conn: Conn, svc: ApprovalService) -> None:
    from datetime import UTC, datetime

    from sgw.approval import repository as repo

    later = datetime(2099, 1, 1, tzinfo=UTC)
    pending = tk.new_crew_proposal(conn, svc)
    svc.decide(conn, user_id="ic_01", proposal_id=pending.proposal_id, request=tk.approve_req(pending))
    with conn.transaction():
        conn.execute("SET LOCAL session_replication_role = replica")
        conn.execute("UPDATE proposal SET state = 'approved' WHERE proposal_id = %s", (pending.proposal_id,))
    with pytest.raises(psycopg.Error) as half:
        repo.insert_token(conn, pending.proposal_id, 1, pending.action_hash, later)
    assert half.value.sqlstate == "42501"
    card = tk.new_crew_proposal(conn, svc)
    _approve_both(conn, svc, card.proposal_id)
    repo.drop_unburned_token(conn, card.proposal_id)
    with pytest.raises(psycopg.Error) as stale:
        repo.insert_token(conn, card.proposal_id, 2, card.action_hash, later)
    assert stale.value.sqlstate == "09000"
    token = repo.insert_token(conn, card.proposal_id, 1, card.action_hash, later)
    conn.execute("UPDATE execution_token SET burned_at = now() WHERE token_id = %s::uuid", (token,))
    with pytest.raises(psycopg.Error) as reburn:
        conn.execute(
            "UPDATE execution_token SET burned_at = now() + interval '1 s' WHERE token_id = %s::uuid",
            (token,),
        )
    assert reburn.value.sqlstate == "42501"


def test_db_stale_race_returns_the_k3_stale_body(
    conn: Conn, svc: ApprovalService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sgw.approval import repository as repo
    from sgw.contracts.api_models import StaleProposal

    card = tk.new_crew_proposal(conn, svc)
    seen = repo.lock_proposal(conn, card.proposal_id)
    svc.revise(
        conn,
        actor="ops_dm_01",
        proposal_id=card.proposal_id,
        change=Revision(params={**card.params, f"crews_at_{golden.YARD_SANDHILL}": 15}),
        reason="recount",
    )
    monkeypatch.setattr(repo, "lock_proposal", lambda c, pid: seen)
    with pytest.raises(PreconditionFailedError) as raced:
        svc.decide(conn, user_id="ic_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    body = StaleProposal.model_validate(raced.value.body())
    assert body.current_version == 2 and body.changed_fields == ["params"]


def test_unique_violations_map_by_constraint() -> None:
    from types import SimpleNamespace

    from sgw.approval.errors import ConflictError, UnprocessableError, from_db_error

    def Err(sqlstate: str, constraint: str | None) -> Any:  # noqa: N802
        diag = SimpleNamespace(constraint_name=constraint, message_primary="x")
        return SimpleNamespace(sqlstate=sqlstate, diag=diag)

    signed = from_db_error(Err("23505", "approval_proposal_id_proposal_version_function_key"))
    other = from_db_error(Err("23505", "proposal_pkey"))
    missing = from_db_error(Err("23503", None))
    assert isinstance(signed, ConflictError) and signed.code == "ALREADY_SIGNED"
    assert isinstance(other, ConflictError) and other.code == "DUPLICATE"
    assert isinstance(missing, UnprocessableError) and missing.status_code == 422


def test_revise_checks_actor_if_match_and_policy(conn: Conn, svc: ApprovalService) -> None:
    card = tk.new_crew_proposal(conn, svc)
    note = Revision(rationale="x")
    with pytest.raises(ForbiddenError):
        svc.revise(conn, actor="log_01", proposal_id=card.proposal_id, change=note, reason="r")
    with pytest.raises(PreconditionFailedError):
        svc.revise(
            conn, actor="ops_dm_01", proposal_id=card.proposal_id, change=note, reason="r", if_match='"9-x"'
        )
    unknown = Revision(target_ids=["STG-NOT-A-REAL-YARD"])
    with pytest.raises(UnprocessableError):
        svc.revise(conn, actor="ops_dm_01", proposal_id=card.proposal_id, change=unknown, reason="r")
    ok = svc.revise(
        conn,
        actor="ops_dm_01",
        proposal_id=card.proposal_id,
        change=note,
        reason="r",
        if_match=etag(card.proposal_version, card.action_hash),
    )
    assert ok.value.rationale == "x"


def test_database_refuses_an_effect_without_a_burned_token(conn: Conn, svc: ApprovalService) -> None:
    from sgw.approval import repository as repo

    card = tk.new_crew_proposal(conn, svc)
    _approve_both(conn, svc, card.proposal_id)
    token = tk.repo_token(conn, card.proposal_id)
    assert token is not None
    with pytest.raises(psycopg.Error) as early:
        repo.insert_effect(
            conn, f"EFF-{card.proposal_id}", card.proposal_id, "work_management", token["token_id"]
        )
    assert early.value.sqlstate == "42501"
    effect = svc.burn(
        conn,
        token_id=token["token_id"],
        proposal_id=card.proposal_id,
        proposal_version=1,
        action_hash=card.action_hash,
    )
    assert conn.execute("SELECT count(*) FROM effect WHERE effect_id = %s", (effect,)).fetchone() == (1,)
