"""Security fixes H1/H2 (audit of main aa6fd39): the runtime role cannot rewrite authority rows, and one
burned token spends exactly one effect. Every malicious statement runs as `sgw_app` (the runtime login's
group) and must fail; the legitimate flow runs as the same role through the 4800 definer functions."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from sgw.approval import testkit as tk
from sgw.approval.breakglass import BreakGlassService
from sgw.approval.breakglass_policy import ReferenceGovernance
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService, Revision
from sgw.contracts import golden
from sgw.contracts.api_models import BreakGlassRequest, ProposalCard, WithdrawRequest

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
START = golden.ADVISORY_N.issued + timedelta(minutes=10)
DENIED = (psycopg.errors.InsufficientPrivilege,)


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: security fix needs Postgres
    with tk.seeded_database() as url:
        yield url


@pytest.fixture
def runtime(db_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("SET ROLE sgw_app")
        yield conn


@pytest.fixture
def clock() -> tk.MutableClock:
    return tk.MutableClock(START)


@pytest.fixture
def svc(clock: tk.MutableClock) -> ApprovalService:
    return ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=clock)


def _approved(conn: psycopg.Connection[Any], svc: ApprovalService) -> ProposalCard:
    card = tk.new_crew_proposal(conn, svc)
    for user in ("ic_01", "log_01"):
        svc.decide(conn, user_id=user, proposal_id=card.proposal_id, request=tk.approve_req(card))
    return card


def _burn(conn: psycopg.Connection[Any], svc: ApprovalService, card: ProposalCard) -> str:
    token = tk.repo_token(conn, card.proposal_id)
    assert token is not None
    svc.burn(
        conn,
        token_id=token["token_id"],
        proposal_id=card.proposal_id,
        proposal_version=card.proposal_version,
        action_hash=card.action_hash,
    )
    return str(token["token_id"])


def _refused(conn: psycopg.Connection[Any], sql: str, *args: Any) -> None:
    with pytest.raises(DENIED), conn.transaction():
        conn.execute(sql, args)


# ---- the legitimate flow still works as the runtime role -----------------------------------------------


def test_runtime_role_runs_the_whole_flow(runtime: psycopg.Connection[Any], svc: ApprovalService) -> None:
    card = _approved(runtime, svc)
    _burn(runtime, svc, card)
    assert svc.card(runtime, card.proposal_id).state == "executed"
    other = tk.new_crew_proposal(runtime, svc)
    svc.decide(runtime, user_id="ic_01", proposal_id=other.proposal_id, request=tk.approve_req(other))
    svc.withdraw(
        runtime, user_id="ic_01", proposal_id=other.proposal_id, request=WithdrawRequest(reason="oops")
    )
    params = {k: (int(v) + 1 if isinstance(v, int) else v) for k, v in other.params.items()}
    revised = svc.revise(
        runtime,
        actor="ops_dm_01",
        proposal_id=other.proposal_id,
        change=Revision(params=params),
        reason="N+1",
    ).value
    assert revised.proposal_version == 2 and revised.tier == "T3"
    svc.revise(
        runtime,
        actor="ops_dm_01",
        proposal_id=other.proposal_id,
        change=Revision(rationale="note"),
        reason="n",
    )
    bgs = BreakGlassService(svc, ReferenceGovernance())
    req = BreakGlassRequest(
        proposal_version=2, action_hash=revised.action_hash, reason="lockout imminent now"
    )
    bgs.invoke(runtime, user_id="ic_01", proposal_id=other.proposal_id, request=req)
    assert bgs.cosign(runtime, user_id="log_01", proposal_id=other.proposal_id).value.cosigned_by == "log_01"
    stale = tk.new_crew_proposal(runtime, svc)
    svc.scenario_clock.advance(minutes=61)  # type: ignore[attr-defined]
    assert stale.proposal_id in svc.expire_due(runtime)


# ---- H1: malicious statements as the runtime role --------------------------------------------------------


def test_cannot_lower_tier_and_self_approve_then_mint_a_token(
    runtime: psycopg.Connection[Any], svc: ApprovalService
) -> None:
    card = tk.new_crew_proposal(runtime, svc)
    pid = card.proposal_id
    _refused(
        runtime,
        "UPDATE proposal SET tier = 'T1', required_functions = '{}', state = 'approved'"
        " WHERE proposal_id = %s",
        pid,
    )
    _refused(runtime, "SELECT authority_set_state(%s, 'approved')", pid)
    lowered = {
        "params": card.params,
        "targets": card.target_ids,
        "risk_band": "moderate",
        "preconditions": {},
        "tier": "T1",
        "required_functions": [],
        "escalators": [],
        "state": "draft",
        "proposal_version": 2,
        "action_hash": "a" * 64,
        "policy_version": card.policy_version,
        "evidence_ids": [],
        "rationale": "",
    }
    _refused(runtime, "SELECT authority_revise(%s, 1, %s::jsonb)", pid, psycopg.types.json.Jsonb(lowered))
    _refused(
        runtime,
        "INSERT INTO execution_token (proposal_id, proposal_version, action_hash, expires_at)"
        " VALUES (%s, 1, %s, now() + interval '1 minute')",
        pid,
        card.action_hash,
    )
    assert svc.card(runtime, pid).state == "proposed" and svc.card(runtime, pid).tier == "T3"


def test_cannot_insert_a_pre_approved_or_under_tiered_proposal(runtime: psycopg.Connection[Any]) -> None:
    base = (
        "INSERT INTO proposal (proposal_id, decision_case_id, incident_id, action_type, params, targets,"
        " risk_band, tier, required_functions, state, action_hash, policy_version, initiator_kind,"
        " proposed_by, region_id, domain) VALUES (%s, %s, 'INC-X', 'preposition_crews', '{}', '{}', 'high',"
        " %s, %s::sgw_approval_function[], %s, %s, 'p', 'person', 'ops_dm_01', %s, 'electric')"
    )
    h = "b" * 64
    for pid, tier, fns, state in (
        ("PRP-EVIL-1", "T1", "{}", "proposed"),
        ("PRP-EVIL-2", "T3", "{command,operations}", "proposed"),
        ("PRP-EVIL-3", "T3", "{command,logistics}", "approved"),
    ):
        _refused(runtime, base, pid, golden.CASE_CREWS, tier, fns, state, h, golden.REGION_AIKEN)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE app_user SET can_approve = true, functions = '{command,logistics}'"
        " WHERE user_id = 'ops_dm_02'",
        "UPDATE app_user SET break_glass_eligible = true WHERE user_id = 'ops_dm_02'",
        "INSERT INTO app_user (user_id, display_name, persona, function, functions, can_approve)"
        " VALUES ('evil_01', 'x', 'x', 'command', '{command,logistics}', true)",
        "DELETE FROM app_user WHERE user_id = 'exec_01'",
        "UPDATE authority_rule SET tier = 'T1' WHERE action_type = 'preposition_crews'",
        "DELETE FROM proposal_delta",
        "UPDATE break_glass SET reason = 'rewritten afterwards'",
        "UPDATE envelope SET valid_until = now() + interval '1 year'",
    ],
)
def test_identity_rule_and_evidence_tables_are_read_only(runtime: psycopg.Connection[Any], sql: str) -> None:
    _refused(runtime, sql)


def test_approval_rows_cannot_be_edited_or_deleted(
    runtime: psycopg.Connection[Any], svc: ApprovalService
) -> None:
    card = tk.new_crew_proposal(runtime, svc)
    svc.decide(
        runtime,
        user_id="ic_01",
        proposal_id=card.proposal_id,
        request=tk.approve_req(card, "reject"),
    )
    _refused(runtime, "UPDATE approval SET decision = 'approve' WHERE proposal_id = %s", card.proposal_id)
    _refused(runtime, "DELETE FROM approval WHERE proposal_id = %s", card.proposal_id)
    other = tk.new_crew_proposal(runtime, svc)
    svc.decide(runtime, user_id="ic_01", proposal_id=other.proposal_id, request=tk.approve_req(other))
    aid = runtime.execute(
        "SELECT approval_id FROM approval WHERE proposal_id = %s", (other.proposal_id,)
    ).fetchone()
    assert aid is not None
    _refused(runtime, "SELECT authority_withdraw_approval(%s, 'log_01')", aid[0])


def test_owner_cannot_edit_an_approval_decision_either(db_url: str, svc: ApprovalService) -> None:
    with psycopg.connect(db_url, autocommit=True) as owner:
        card = tk.new_crew_proposal(owner, svc)
        svc.decide(
            owner, user_id="ic_01", proposal_id=card.proposal_id, request=tk.approve_req(card, "reject")
        )
        _refused(owner, "UPDATE approval SET decision = 'approve' WHERE proposal_id = %s", card.proposal_id)
        _refused(
            owner,
            "UPDATE proposal SET tier = 'T1', required_functions = '{}' WHERE proposal_id = %s",
            card.proposal_id,
        )


def test_burned_token_cannot_be_deleted_and_reissued(
    runtime: psycopg.Connection[Any], svc: ApprovalService
) -> None:
    card = _approved(runtime, svc)
    _burn(runtime, svc, card)
    _refused(runtime, "DELETE FROM execution_token WHERE proposal_id = %s", card.proposal_id)
    _refused(runtime, "UPDATE execution_token SET burned_at = NULL WHERE proposal_id = %s", card.proposal_id)
    runtime.execute("SELECT authority_drop_unburned_token(%s)", (card.proposal_id,))
    assert tk.repo_token(runtime, card.proposal_id) is not None
    with pytest.raises(psycopg.Error), runtime.transaction():
        runtime.execute(
            "INSERT INTO execution_token (proposal_id, proposal_version, action_hash, expires_at)"
            " VALUES (%s, %s, %s, now() + interval '1 minute')",
            (card.proposal_id, card.proposal_version, card.action_hash),
        )
    _refused(runtime, "SELECT authority_set_state(%s, 'approved')", card.proposal_id)


# ---- H2: one burned token, one effect --------------------------------------------------------------------


def test_one_burned_token_spends_exactly_one_effect(
    runtime: psycopg.Connection[Any], svc: ApprovalService
) -> None:
    card = _approved(runtime, svc)
    token = _burn(runtime, svc, card)
    with pytest.raises(psycopg.errors.UniqueViolation), runtime.transaction():
        runtime.execute(
            "INSERT INTO effect (effect_id, proposal_id, channel, token_id)"
            " VALUES ('EFF-TWICE', %s, 'x', %s)",
            (card.proposal_id, token),
        )
    _refused(
        runtime,
        "INSERT INTO effect (effect_id, proposal_id, channel) VALUES ('EFF-NOTOKEN', %s, 'x')",
        card.proposal_id,
    )
    other = _approved(runtime, svc)
    _refused(
        runtime,
        "INSERT INTO effect (effect_id, proposal_id, channel, token_id) VALUES ('EFF-FOREIGN', %s, 'x', %s)",
        other.proposal_id,
        token,
    )
    _refused(runtime, "UPDATE effect SET token_id = NULL WHERE proposal_id = %s", card.proposal_id)


def test_authority_rule_is_the_tier_table(runtime: psycopg.Connection[Any]) -> None:
    """One data row per action type: a new action type (e.g. policy_change) needs a row in a migration."""
    from sgw.approval import policy_data

    rows = runtime.execute(
        "SELECT action_type, tier, approver_functions, escalated_functions FROM authority_rule"
    ).fetchall()
    found = {r[0]: (r[1], sorted(r[2]), sorted(r[3])) for r in rows}
    want = {
        k: (v["tier"], sorted(v["approver_functions"]), sorted(v["escalated_functions"]))
        for k, v in policy_data.build()["rules"].items()
    }
    assert found == want, "add an authority_rule row (migration) for every K8 tier table entry"
