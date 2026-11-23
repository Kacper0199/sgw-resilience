from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sgw.common import numbers
from sgw.contracts import approval as ap
from sgw.contracts import golden
from sgw.contracts.identities import load_users
from sgw.contracts.vocab import ApprovalFunction, Tier

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2024, 9, 26, 16, 0, tzinfo=UTC)
USERS = load_users(REPO_ROOT / "data" / "seed" / "users.yaml")


def test_action_hash_golden_vectors() -> None:
    vectors = json.loads((REPO_ROOT / "contracts" / "vectors" / "action_hash.json").read_text())["vectors"]
    for v in vectors:
        assert ap.canonical_json(v["input"]).decode() == v["canonical"]
        assert hashlib.sha256(v["canonical"].encode()).hexdigest() == v["sha256"]
    by_name = {v["name"]: v["sha256"] for v in vectors}
    assert by_name["crews_v1"] == ap.action_hash(golden.crew_material(14, 9), golden.POLICY_VERSION)
    assert by_name["crews_v1"] != by_name["crews_v2"]


def test_hash_covers_exactly_material_fields() -> None:
    assert set(ap.MaterialFields.model_fields) == set(ap.MATERIAL_FIELDS)
    base = golden.crew_material(14, 9)
    assert ap.action_hash(base, "p1") != ap.action_hash(base, "p2")
    reordered = base.model_copy(update={"target_ids": list(reversed(base.target_ids))})
    assert ap.action_hash(ap.MaterialFields.model_validate(reordered.model_dump()), "p1") == ap.action_hash(
        base, "p1"
    )
    assert ap.material_diff(base, golden.crew_material(18, 9)) == ["params"]


@pytest.mark.parametrize("bad", [0.5, float("nan"), float("inf"), 2**53])
def test_canonical_rejects_floats_and_unsafe_ints(bad: object) -> None:
    with pytest.raises(ValueError):
        ap.canonical_json({"p": bad})


@settings(max_examples=200, deadline=None)
@given(
    st.recursive(
        st.none() | st.booleans() | st.integers(-(2**53) + 1, 2**53 - 1) | st.text(max_size=8),
        lambda c: st.lists(c, max_size=4) | st.dictionaries(st.text(max_size=6), c, max_size=4),
        max_leaves=20,
    )
)
def test_canonical_is_deterministic_and_parses_back(value: object) -> None:
    out = ap.canonical_json(value)
    assert json.loads(out) == value
    assert ap.canonical_json(json.loads(out)) == out


def test_ttl_rule_takes_the_minimum() -> None:
    assert ap.expires_at(
        now=NOW,
        tier=Tier.T3,
        earliest_evidence_expiry=None,
        next_forecast_issue=None,
        approver_shift_end=None,
    ) == NOW + timedelta(minutes=60)
    nxt = NOW + timedelta(minutes=20)
    assert (
        ap.expires_at(
            now=NOW,
            tier=Tier.T3,
            earliest_evidence_expiry=NOW + timedelta(minutes=40),
            next_forecast_issue=nxt,
            approver_shift_end=None,
        )
        == nxt
    )
    with pytest.raises(ValueError):
        ap.expires_at(
            now=NOW,
            tier=Tier.T0,
            earliest_evidence_expiry=None,
            next_forecast_issue=None,
            approver_shift_end=None,
        )


def test_policy_numbers_mirror_contract_constants() -> None:
    for tier, minutes in ap.TIER_TTL_MIN.items():
        assert numbers.value(f"policy_approval_ttl_{tier.value.lower()}_min") == minutes
    for tier, minutes in ap.EVIDENCE_AGE_LIMIT_MIN.items():
        assert numbers.value(f"policy_evidence_age_{tier.value.lower()}_min") == minutes
    assert numbers.value("policy_break_glass_cosign_hours") == ap.BREAK_GLASS_COSIGN_HOURS
    assert numbers.value("policy_no_regret_act_now_ppm") == golden.NO_REGRET_THRESHOLD_PPM


def test_envelope_rule() -> None:
    bounds = ap.envelope_from_plan({"a": 18, "b": 9}, pct=20)
    assert bounds == {"a": ap.EnvelopeBound(min=15, max=21), "b": ap.EnvelopeBound(min=8, max=10)}
    env = ap.Envelope(
        envelope_id="ENV-1", proposal_id="P", bounds=bounds, valid_until_utc=NOW + timedelta(hours=6)
    )
    assert ap.tier_for_reoptimisation(env, {"a": 21, "b": 8}, at=NOW) is Tier.T1
    assert ap.tier_for_reoptimisation(env, {"a": 22, "b": 9}, at=NOW) is Tier.T3
    assert ap.tier_for_reoptimisation(env, {"a": 18, "c": 1}, at=NOW) is Tier.T3
    assert ap.tier_for_reoptimisation(env, {"a": 18}, at=NOW + timedelta(hours=7)) is Tier.T3


def test_break_glass_rule() -> None:
    bg = ap.break_glass(
        proposal_id="P",
        ic_id="ic_01",
        reason="Pressure falling, wlead unreachable",
        used_at=NOW,
        tier=Tier.T3,
    )
    assert bg.cosign_due_utc == NOW + timedelta(hours=24) and bg.flagged_for_after_action
    assert ap.cosign_overdue(bg, now=NOW + timedelta(hours=25))
    assert not ap.cosign_overdue(bg, now=NOW + timedelta(hours=23))
    with pytest.raises(ValueError):
        ap.break_glass(proposal_id="P", ic_id="ic_01", reason="short", used_at=NOW, tier=Tier.T3)
    with pytest.raises(ValueError):
        ap.break_glass(proposal_id="P", ic_id="ic_01", reason="long enough reason", used_at=NOW, tier=Tier.T2)


def test_seed_users_match_x01() -> None:
    assert len(USERS.users) == 11
    assert {u.user_id for u in USERS.users} == {
        "ic_01",
        "ops_dm_01",
        "ops_dm_02",
        "plan_etr_01",
        "log_01",
        "wtr_lead_01",
        "wtr_comp_01",
        "exec_01",
        "audit_01",
        "admin_01",
        "ml_01",
    }
    assert ApprovalFunction.COMMUNICATIONS not in {u.function for u in USERS.users}
    assert all(" " in u.display_name or u.display_name.istitle() for u in USERS.users)


APPROVED_RULES = [r for r in ap.TIER_TABLE if r.approver_functions]
CASES = [(r, p) for r in APPROVED_RULES for p in r.proposer]


@pytest.mark.parametrize(("rule", "proposer"), CASES, ids=[f"{r.action_type.value}-{p}" for r, p in CASES])
def test_every_t2_t3_rule_has_distinct_eligible_non_proposer_approvers(
    rule: ap.TierRule, proposer: str
) -> None:
    if rule.tier is Tier.T3:
        assert len(rule.approver_functions) == 2 and len(set(rule.approver_functions)) == 2
    chosen: set[str] = set()
    for fn in rule.approver_functions:
        eligible = [
            u.user_id for u in USERS.by_function(fn) if u.user_id != proposer and u.user_id not in chosen
        ]
        assert eligible, f"{rule.action_type}: no eligible {fn} approver when {proposer} proposes"
        chosen.add(eligible[0])
    assert len(chosen) == len(rule.approver_functions)


def test_proposers_are_seeded_users_or_system_initiators() -> None:
    ids = {u.user_id for u in USERS.users}
    for rule in ap.TIER_TABLE:
        for p in rule.proposer:
            assert p in ids or p.startswith(("system:", "agent")), (rule.action_type, p)


def test_small_staging_has_a_relief_duty_manager() -> None:
    rule = ap.tier_rule(ap.ActionType.STAGE_CREWS_SMALL)
    others = [u.user_id for u in USERS.by_function(ApprovalFunction.OPERATIONS) if u.user_id != "ops_dm_01"]
    assert others == ["ops_dm_02"] and "ops_dm_01" in rule.proposer


def test_ic_is_break_glass_eligible_and_only_ic() -> None:
    eligible = [u.user_id for u in USERS.users if u.break_glass_eligible]
    assert eligible == ["ic_01"]


def test_kill_switch_restore_pair_exists() -> None:
    for fn in ap.KILL_RESTORE_FUNCTIONS:
        assert USERS.by_function(fn)
    triggers = {u.user_id for u in USERS.users if u.kill_trigger}
    assert triggers == set(ap.KILL_TRIGGER_USERS)


def test_executive_approves_nothing() -> None:
    exec_user = next(u for u in USERS.users if u.function is ApprovalFunction.EXECUTIVE)
    assert not exec_user.can_approve
    assert all(ApprovalFunction.EXECUTIVE not in r.approver_functions for r in ap.TIER_TABLE)


def test_password_is_never_in_the_seed_file() -> None:
    text = (REPO_ROOT / "data" / "seed" / "users.yaml").read_text()
    assert "password:" not in text and USERS.password_env == "DEMO_PASSWORD"  # noqa: S105
