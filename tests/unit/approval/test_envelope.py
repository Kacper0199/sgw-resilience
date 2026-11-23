"""Envelopes (O-04): inside bounds T1, outside T3. One bounds function, pinned against the K8 contract
function, the Python policy mirror and OPA; the service records the envelope of an approved crew plan."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sgw.approval import envelope as env_mod
from sgw.approval import errors
from sgw.approval import testkit as tk
from sgw.approval.breakglass_policy import OpaGovernance, ReferenceGovernance, build, is_current
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.contracts import approval as ap
from sgw.contracts.vocab import Tier

NO_OPA = "no OPA: set SGW_TEST_OPA_URL or start docker"
AT = datetime(2024, 9, 26, 10, 0, tzinfo=UTC)
UNTIL = AT + timedelta(hours=6)
BOUNDS = ap.envelope_from_plan({"crews_at_a": 10, "crews_at_b": 5}, pct=20)

values = st.one_of(
    st.integers(min_value=-5, max_value=20),
    st.booleans(),
    st.floats(min_value=-5, max_value=20, allow_nan=False),
    st.text(max_size=3),
)
params = st.dictionaries(st.sampled_from(["crews_at_a", "crews_at_b", "crews_at_c"]), values, max_size=3)
offsets = st.integers(min_value=-3600, max_value=3600)


def _case(p: dict[str, Any], offset_s: int) -> tuple[datetime, dict[str, Any]]:
    now = UNTIL + timedelta(seconds=offset_s)
    env = ap.Envelope(envelope_id="ENV-T", proposal_id="PRP-T", bounds=BOUNDS, valid_until_utc=UNTIL)
    return now, env_mod.policy_input(env, p, now)


def test_bounds_are_plus_minus_policy_pct() -> None:
    assert env_mod.envelope_pct() == 20
    assert BOUNDS["crews_at_a"] == ap.EnvelopeBound(min=8, max=12)
    assert BOUNDS["crews_at_b"] == ap.EnvelopeBound(min=4, max=6)


@pytest.mark.parametrize(
    ("p", "at", "tier"),
    [
        ({"crews_at_a": 12, "crews_at_b": 4}, AT, Tier.T1),
        ({"crews_at_a": 8}, UNTIL, Tier.T1),
        ({"crews_at_a": 13}, AT, Tier.T3),
        ({"crews_at_b": 3}, AT, Tier.T3),
        ({"crews_at_c": 1}, AT, Tier.T3),
        ({"crews_at_a": 10}, UNTIL + timedelta(seconds=1), Tier.T3),
    ],
)
def test_inside_bounds_t1_outside_t3(p: dict[str, int], at: datetime, tier: Tier) -> None:
    got = env_mod.assess(BOUNDS, p, at=at, valid_until=UNTIL)
    assert got.tier is tier
    env = ap.Envelope(envelope_id="ENV-T", proposal_id="PRP-T", bounds=BOUNDS, valid_until_utc=UNTIL)
    assert ap.tier_for_reoptimisation(env, p, at=at) is tier


@settings(max_examples=300, deadline=None)
@given(p=params, offset_s=offsets)
def test_assess_agrees_with_the_contract_and_the_policy_mirror(p: dict[str, Any], offset_s: int) -> None:
    now, payload = _case(p, offset_s)
    pure = env_mod.assess(BOUNDS, p, at=now, valid_until=UNTIL)
    assert ReferenceGovernance().envelope(payload) == pure
    env = ap.Envelope(envelope_id="ENV-T", proposal_id="PRP-T", bounds=BOUNDS, valid_until_utc=UNTIL)
    assert ap.tier_for_reoptimisation(env, p, at=now) is pure.tier


@pytest.mark.parametrize("value", [10.5, 10.0, True, "10", None, 12, 12.0000001])
def test_contract_and_assess_agree_on_floats_bools_and_strings(value: Any) -> None:
    env = ap.Envelope(envelope_id="ENV-T", proposal_id="PRP-T", bounds=BOUNDS, valid_until_utc=UNTIL)
    p = {"crews_at_a": value}
    assert (
        ap.tier_for_reoptimisation(env, p, at=AT) is env_mod.assess(BOUNDS, p, at=AT, valid_until=UNTIL).tier
    )


def test_governance_data_is_generated_and_committed() -> None:
    assert is_current(), "run: uv run sgw audit policy-data"
    assert build()["break_glass"]["cosign_hours"] == ap.BREAK_GLASS_COSIGN_HOURS


@pytest.fixture(scope="module")
def opa() -> Iterator[OpaGovernance]:
    with tk.opa_server() as url:
        if url is None:
            pytest.skip(NO_OPA)  # sgw-allow-skip: needs docker
        client = OpaGovernance(url, allow_load=True)
        client.load()
        yield client
        client.close()


@settings(max_examples=120, deadline=None)
@given(p=params, offset_s=offsets)
def test_opa_envelope_agrees_with_the_pure_function(
    opa: OpaGovernance, p: dict[str, Any], offset_s: int
) -> None:
    now, payload = _case(p, offset_s)
    assert opa.envelope(payload) == env_mod.assess(BOUNDS, p, at=now, valid_until=UNTIL)


def _bg_cases() -> list[dict[str, Any]]:
    ic = {"user_id": "ic_01", "functions": ["command"], "break_glass_eligible": True, "on_shift": True}
    proposal = {
        "tier": "T3",
        "state": "proposed",
        "proposed_by": "ops_dm_01",
        "required_functions": ["command", "logistics"],
        "expires_at_ns": 2_000,
    }
    reason = {"reason": "Lockout imminent, chief unreachable", "existing": False}
    out = [{"subject": ic, "proposal": proposal, "break_glass": reason, "context": {"now_ns": 1_000}}]
    for key, value in [
        ("proposed_by", "ic_01"),
        ("tier", "T2"),
        ("state", "approved"),
        ("state", "escalated"),
        ("expires_at_ns", 500),
        ("expires_at_ns", None),
    ]:
        out.append({**out[0], "proposal": {**proposal, key: value}})
    for key, value in [("break_glass_eligible", False), ("functions", ["operations"]), ("on_shift", False)]:
        out.append({**out[0], "subject": {**ic, key: value}})
    for bg in (
        {"reason": "   short    ", "existing": False},
        {"existing": False},
        {**reason, "existing": True},
    ):
        out.append({**out[0], "break_glass": bg})
    return out


def _cosign_cases() -> list[dict[str, Any]]:
    log = {"user_id": "log_01", "functions": ["logistics"], "can_approve": True, "on_shift": True}
    proposal = {
        "state": "approved",
        "proposed_by": "ops_dm_01",
        "required_functions": ["command", "logistics"],
    }
    base = {"subject": log, "proposal": proposal, "break_glass": {"ic_id": "ic_01", "cosigned": False}}
    out = [base]
    for key, value in [("user_id", "ic_01"), ("user_id", "ops_dm_01"), ("functions", ["compliance"])]:
        out.append({**base, "subject": {**log, key: value}})
    out.append({**base, "subject": {**log, "can_approve": False, "on_shift": False}})
    out.append({**base, "break_glass": {"ic_id": "ic_01", "cosigned": True}})
    out.append({**base, "proposal": {**proposal, "state": "in_review"}})
    out.append({**base, "proposal": {**proposal, "required_functions": ["water_operations", "compliance"]}})
    return out


def test_opa_break_glass_and_cosign_agree_with_the_mirror(opa: OpaGovernance) -> None:
    ref = ReferenceGovernance()
    for case in _bg_cases():
        assert opa.break_glass(case) == ref.break_glass(case), case
    for case in _cosign_cases():
        assert opa.cosign(case) == ref.cosign(case), case


# ---- service -------------------------------------------------------------------------------------------


@pytest.fixture
def approved_crews(conn: psycopg.Connection[Any], svc: ApprovalService) -> str:
    card = tk.new_crew_proposal(conn, svc)
    for user in ("ic_01", "log_01"):
        svc.decide(conn, user_id=user, proposal_id=card.proposal_id, request=tk.approve_req(card))
    return card.proposal_id


def test_service_records_envelope_once_and_classifies(
    conn: psycopg.Connection[Any], approved_crews: str, clock: tk.MutableClock
) -> None:
    service = env_mod.EnvelopeService(ReferenceGovernance(), clock=clock)
    with conn.transaction():
        env = service.record(conn, approved_crews, actor_id="ic_01")
    with conn.transaction():
        assert service.record(conn, approved_crews, actor_id="ic_01") == env
    plan = ApprovalService(ReferencePolicy()).card(conn, approved_crews).params
    assert env.bounds == env_mod.bounds_from_params(plan, 20) and len(env.bounds) == 2
    keys = list(env.bounds)
    inside = {k: env.bounds[k].max for k in keys}
    outside = {keys[0]: env.bounds[keys[0]].max + 1}
    assert service.classify(conn, approved_crews, inside).tier is Tier.T1
    out = service.classify(conn, approved_crews, outside)
    assert out.tier is Tier.T3 and out.outside == (keys[0],)
    clock.at = env.valid_until_utc + timedelta(seconds=1)
    assert service.classify(conn, approved_crews, inside).expired


def test_envelope_needs_an_approved_t3_plan(
    conn: psycopg.Connection[Any], svc: ApprovalService, clock: tk.MutableClock
) -> None:
    card = tk.new_crew_proposal(conn, svc)
    service = env_mod.EnvelopeService(clock=clock)
    with pytest.raises(errors.ConflictError), conn.transaction():
        service.record(conn, card.proposal_id, actor_id="ic_01")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "INSERT INTO envelope (envelope_id, proposal_id, bounds, valid_until) VALUES ('ENV-X', %s,"
            ' \'{"a": {"min": 1, "max": 2}}\', now())',
            (card.proposal_id,),
        )


class _Broken:
    def envelope(self, payload: dict[str, Any]) -> env_mod.EnvelopeAssessment:
        raise errors.PolicyUnavailableError("down")


class _Lying:
    def envelope(self, payload: dict[str, Any]) -> env_mod.EnvelopeAssessment:
        return env_mod.EnvelopeAssessment(Tier.T1)


@pytest.mark.parametrize("policy", [_Broken(), _Lying()])
def test_policy_failure_or_disagreement_fails_closed_to_t3(
    conn: psycopg.Connection[Any], approved_crews: str, clock: tk.MutableClock, policy: Any
) -> None:
    with conn.transaction():
        env = env_mod.EnvelopeService(clock=clock).record(conn, approved_crews, actor_id="ic_01")
    key = next(iter(env.bounds))
    service = env_mod.EnvelopeService(policy, clock=clock)
    assert service.classify(conn, approved_crews, {key: env.bounds[key].max + 5}).tier is Tier.T3


def test_without_an_envelope_every_reoptimisation_is_t3(
    conn: psycopg.Connection[Any], clock: tk.MutableClock
) -> None:
    service = env_mod.EnvelopeService(ReferenceGovernance(), clock=clock)
    assert service.classify(conn, "PRP-NONE", {"crews_at_a": 1}).tier is Tier.T3
