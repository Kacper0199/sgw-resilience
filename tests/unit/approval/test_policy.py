from __future__ import annotations

import itertools
import re
from typing import Any

import httpx
import pytest

from sgw.approval import policy_data
from sgw.approval.errors import PolicyUnavailableError
from sgw.approval.policy import OpaPolicy, ReferencePolicy
from sgw.contracts import approval as ap
from sgw.contracts.identities import load_users
from sgw.contracts.vocab import ApprovalFunction, Tier

REF = ReferencePolicy()
USERS = load_users(policy_data.REPO_ROOT / "data" / "seed" / "users.yaml")


def propose_input(action: str, proposer: str, **facts: Any) -> dict[str, Any]:
    kind = "system_rule" if proposer.startswith("system:") else "agent" if proposer == "agent" else "person"
    return {
        "action": "propose",
        "subject": {"user_id": proposer},
        "proposal": {
            "action_type": action,
            "proposed_by": proposer,
            "requested_by": None,
            "initiator_kind": kind,
            "target_ids": facts.pop("targets", ["T-1"]),
        },
        "facts": {"customers_affected": 0, **facts},
        "context": {"degraded_mode": "M0", "now_ns": 0},
    }


def approve_input(
    subject: str,
    functions: list[str],
    function: str,
    approvals: list[dict[str, str]] | None = None,
    **over: Any,
) -> dict[str, Any]:
    proposal = {
        "action_type": "preposition_crews",
        "proposed_by": "ops_dm_01",
        "requested_by": None,
        "initiator_kind": "person",
        "target_ids": ["A", "B"],
        "tier": "T3",
        "required_functions": ["command", "logistics"],
        "state": "proposed",
        "expires_at_ns": 2_000,
    }
    proposal.update(over.pop("proposal", {}))
    return {
        "action": "approve",
        "subject": {
            "user_id": subject,
            "functions": functions,
            "can_approve": True,
            "on_shift": True,
            **over,
        },
        "proposal": proposal,
        "context": {"degraded_mode": "M0", "now_ns": 1_000},
        "approval": {"decision": "approve", "function": function, "evidence_oldest_age_s": None},
        "approvals": approvals or [],
    }


def test_committed_tier_data_is_generated_from_the_contract_table() -> None:
    assert policy_data.is_current(), "run `uv run sgw policy-data`"
    rules = policy_data.build()["rules"]
    assert set(rules) == {r.action_type.value for r in ap.TIER_TABLE}


def test_rego_holds_no_table_literal() -> None:
    rego = policy_data.REGO_PATH.read_text(encoding="utf-8")
    code = "\n".join(line for line in rego.splitlines() if not line.lstrip().startswith("#"))
    for fn in ApprovalFunction:
        assert f'"{fn.value}"' not in code
    for user in USERS.users:
        assert user.user_id not in code
    assert not re.search(r"\b(1000|10|60|900|1800|3600)\b", code)


def test_every_t2_row_has_an_escalation_pair() -> None:
    for rule in ap.TIER_TABLE:
        pair = policy_data.ESCALATED_FUNCTIONS.get(rule.action_type)
        assert (pair is not None) == (rule.tier is Tier.T2)
        if pair:
            assert len(set(pair)) == 2 and ApprovalFunction.COMMAND in pair


def test_k18_has_a_distinct_non_proposer_pair_for_every_approval_row() -> None:
    for rule in ap.TIER_TABLE:
        if rule.tier is Tier.T1:
            continue
        functions = policy_data.ESCALATED_FUNCTIONS.get(rule.action_type, rule.approver_functions)
        for proposer in rule.proposer:
            pools = [[u.user_id for u in USERS.by_function(fn) if u.user_id != proposer] for fn in functions]
            pairs = [combo for combo in itertools.product(*pools) if len(set(combo)) == len(combo)]
            assert pairs, (rule.action_type, proposer)


@pytest.mark.parametrize("rule", ap.TIER_TABLE, ids=lambda r: r.action_type.value)
def test_reference_classifies_every_row_as_the_table(rule: ap.TierRule) -> None:
    decision = REF.propose(propose_input(rule.action_type.value, rule.proposer[0]))
    assert decision.allow
    assert decision.classification.tier == rule.tier.value
    assert decision.classification.required_functions == tuple(f.value for f in rule.approver_functions)


def test_reference_escalation_and_t4() -> None:
    c = REF.classify(propose_input("set_event_type", "ops_dm_01", critical_facility=True))
    assert (c.tier, c.required_functions, c.escalators) == (
        "T3",
        ("command", "operations"),
        ("critical_facility",),
    )
    many = REF.classify(propose_input("stage_crews_small", "ops_dm_01", targets=[f"T{i}" for i in range(11)]))
    assert many.tier == "T3" and many.escalators == ("targets_gt_limit",)
    assert REF.classify(propose_input("preposition_crews", "ops_dm_01", irreversible=True)).tier == "T3"
    t4 = REF.propose(propose_input("open_breaker", "ops_dm_01"))
    assert t4.classification.tier == "T4" and set(t4.deny) == {"tier_t4_prohibited", "unknown_action_type"}


def test_reference_approval_rules() -> None:
    own = REF.approve(approve_input("ops_dm_01", ["operations"], "operations"))
    assert set(own.deny) == {"function_not_required", "self_approval"}
    first = REF.approve(approve_input("ic_01", ["command"], "command"))
    assert first.allow and not first.complete and first.remaining_functions == ("logistics",)
    signed = [{"approver_id": "ic_01", "function": "command", "decision": "approve"}]
    pair = REF.approve(approve_input("log_01", ["logistics"], "logistics", signed))
    assert pair.allow and pair.complete
    twice = REF.approve(approve_input("ic_01", ["command", "logistics"], "logistics", signed))
    assert "approver_already_signed" in twice.deny and not twice.complete
    same_fn = REF.approve(approve_input("ic_02", ["command"], "command", signed))
    assert "function_already_signed" in same_fn.deny


def _propose_cases() -> list[dict[str, Any]]:
    cases = []
    actions = [r.action_type.value for r in ap.TIER_TABLE] + ["open_breaker"]
    proposers = ["ops_dm_01", "agent", "system:rule:bwa_pressure_loss", "plan_etr_01", "exec_01"]
    facts = [
        {},
        {"customers_affected": 1000},
        {"telemetry_unverified": True},
        {"targets": [f"T{i}" for i in range(11)]},
    ]
    for action, who, extra in itertools.product(actions, proposers, facts):
        inp = propose_input(action, who, **dict(extra))
        cases.append(inp)
    degraded = propose_input("set_event_type", "ops_dm_01")
    degraded["context"]["degraded_mode"] = "M3"
    impostor = propose_input("preposition_crews", "ops_dm_01")
    impostor["subject"]["user_id"] = "ops_dm_02"
    return [*cases, degraded, impostor]


def _approve_cases() -> list[dict[str, Any]]:
    signed = [{"approver_id": "ic_01", "function": "command", "decision": "approve"}]
    rejected = [{"approver_id": "ic_01", "function": "command", "decision": "reject"}]
    subjects = [
        ("ic_01", ["command"]),
        ("log_01", ["logistics"]),
        ("ops_dm_01", ["operations"]),
        ("dual_01", ["command", "logistics"]),
    ]
    cases = []
    for (user, fns), function, prior in itertools.product(
        subjects, ["command", "logistics"], [[], signed, rejected]
    ):
        cases.append(approve_input(user, fns, function, prior))
    variants: list[dict[str, Any]] = [
        {"proposal": {"state": "approved"}},
        {"proposal": {"tier": "T1"}},
        {"proposal": {"required_functions": ["command", "command"]}},
        {"proposal": {"expires_at_ns": 1_000}},
        {"proposal": {"expires_at_ns": None}},
        {"proposal": {"initiator_kind": "agent", "requested_by": "log_01"}},
        {"can_approve": False},
        {"on_shift": False},
    ]
    for v in variants:
        cases.append(approve_input("log_01", ["logistics"], "logistics", signed, **v))
    old = approve_input("ic_01", ["command"], "command")
    old["approval"]["evidence_oldest_age_s"] = 901
    reject = approve_input("log_01", ["logistics"], "logistics", signed)
    reject["approval"]["decision"] = "reject"
    bogus = approve_input("log_01", ["logistics"], "logistics", signed)
    bogus["approval"]["decision"] = "maybe"
    return [*cases, old, reject, bogus]


@pytest.mark.slow
def test_opa_and_reference_agree_on_every_case(opa_url: str) -> None:
    opa = OpaPolicy(opa_url, allow_load=True)
    opa.load()
    try:
        for case in _propose_cases():
            assert opa.propose(case) == REF.propose(case), case
        for case in _approve_cases():
            assert opa.approve(case) == REF.approve(case), case
    finally:
        opa.close()


@pytest.mark.slow
def test_opa_without_policy_fails_closed_or_reloads_once(opa_url: str) -> None:
    client = httpx.Client(base_url=opa_url, timeout=2.0)
    probe = approve_input("ic_01", ["command"], "command")
    try:
        client.delete(f"/v1/policies/{policy_data.POLICY_ID}")
        with pytest.raises(PolicyUnavailableError):
            OpaPolicy(opa_url, client=client).approve(probe)
        healing = OpaPolicy(opa_url, reload_on_missing=True, allow_load=True)
        assert healing.approve(probe) == REF.approve(probe)
        healing.close()
    finally:
        OpaPolicy(opa_url, allow_load=True).load()
        client.close()


def test_unreachable_opa_fails_closed() -> None:
    with pytest.raises(PolicyUnavailableError):
        OpaPolicy("http://127.0.0.1:9", timeout_s=0.2).propose(
            propose_input("preposition_crews", "ops_dm_01")
        )
