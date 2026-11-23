"""K8 approval semantics: DC-17 material fields, RFC 8785 action hash, TTL rule, tier table, envelope and
break-glass rules. `policy/approval.rego` must agree with `TIER_TABLE`; the canonical-hash golden
vectors in `contracts/vectors/action_hash.json` pin Python and TypeScript to the same bytes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

import rfc8785
from pydantic import Field, field_validator, model_validator

from sgw.contracts.base import Contract, Identifier, UtcDatetime
from sgw.contracts.vocab import ActionType, ApprovalFunction, DecisionStep, RiskBand, Tier

MATERIAL_FIELDS: tuple[str, ...] = (
    "action_type",
    "params",
    "target_ids",
    "risk_band",
    "preconditions",
    "tier",
    "escalators",
    "retracted_evidence_ids",
)
NON_MATERIAL_EXAMPLES: tuple[str, ...] = (
    "rationale_text",
    "evidence_refresh_same_band",
    "ordering",
    "score_in_band",
)

CanonicalScalar = int | str | bool | None


def _check_canonical(value: Any, path: str = "$") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, int):
        if abs(value) > 2**53 - 1:
            raise ValueError(f"{path}: integer outside the IEEE-754 safe range")
        return
    if isinstance(value, float):
        raise ValueError(f"{path}: floats are not allowed in material fields; use integer ppm or round first")
    if isinstance(value, list | tuple):
        for i, item in enumerate(value):
            _check_canonical(item, f"{path}[{i}]")
        return
    if isinstance(value, Mapping):
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError(f"{path}: object keys must be strings")
            _check_canonical(v, f"{path}.{k}")
        return
    raise ValueError(f"{path}: unsupported type {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    _check_canonical(value)
    return rfc8785.dumps(value)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class MaterialFields(Contract):
    action_type: ActionType
    params: dict[str, CanonicalScalar | list[CanonicalScalar]] = Field(
        description="action parameters already rounded to the action's declared granularity"
    )
    target_ids: list[Identifier]
    risk_band: RiskBand
    preconditions: dict[str, bool]
    tier: Tier
    escalators: list[str]
    retracted_evidence_ids: list[Identifier] = Field(default_factory=list)

    @field_validator("target_ids", "escalators", "retracted_evidence_ids")
    @classmethod
    def _sorted_unique(cls, v: list[str]) -> list[str]:
        return sorted(set(v))


def action_hash(material: MaterialFields, policy_version: str) -> str:
    body = {
        "material": material.model_dump(mode="json"),
        "policy_version": policy_version,
        "tier": material.tier.value,
    }
    return sha256_hex(canonical_json(body))


def material_diff(old: MaterialFields, new: MaterialFields) -> list[str]:
    a, b = old.model_dump(mode="json"), new.model_dump(mode="json")
    return [f for f in MATERIAL_FIELDS if a.get(f) != b.get(f)]


TIER_TTL_MIN: dict[Tier, int] = {Tier.T1: 240, Tier.T2: 120, Tier.T3: 60}
EVIDENCE_AGE_LIMIT_MIN: dict[Tier, int] = {Tier.T1: 60, Tier.T2: 30, Tier.T3: 15}
BREAK_GLASS_COSIGN_HOURS = 24


def expires_at(
    *,
    now: datetime,
    tier: Tier,
    earliest_evidence_expiry: datetime | None,
    next_forecast_issue: datetime | None,
    approver_shift_end: datetime | None,
) -> datetime:
    """DC-09 (5) on the scenario clock: min(now + tier TTL, evidence expiry, next forecast, shift end)."""
    if tier not in TIER_TTL_MIN:
        raise ValueError(f"{tier} has no approval TTL")
    candidates = [now + timedelta(minutes=TIER_TTL_MIN[tier])]
    candidates += [
        t for t in (earliest_evidence_expiry, next_forecast_issue, approver_shift_end) if t is not None
    ]
    return min(candidates)


class TierRule(Contract):
    step: DecisionStep | None
    action_type: ActionType
    tier: Tier
    approver_functions: tuple[ApprovalFunction, ...]
    proposer: tuple[str, ...] = Field(
        min_length=1, description="user ids or system initiators that may propose"
    )
    note: str = ""


EXERCISE_INJECT = "system:rule:exercise_inject"

TIER_TABLE: tuple[TierRule, ...] = (
    TierRule(
        step=DecisionStep.D1,
        action_type=ActionType.SET_EVENT_TYPE,
        tier=Tier.T2,
        approver_functions=(ApprovalFunction.COMMAND,),
        proposer=("ops_dm_01", "ops_dm_02", EXERCISE_INJECT),
    ),
    TierRule(
        step=DecisionStep.D2,
        action_type=ActionType.PREPOSITION_CREWS,
        tier=Tier.T3,
        approver_functions=(ApprovalFunction.COMMAND, ApprovalFunction.LOGISTICS),
        proposer=("ops_dm_01", "ops_dm_02"),
        note="Helene-scale pre-positioning with envelope",
    ),
    TierRule(
        step=DecisionStep.D2,
        action_type=ActionType.MUTUAL_AID_REQUEST,
        tier=Tier.T3,
        approver_functions=(ApprovalFunction.COMMAND, ApprovalFunction.LOGISTICS),
        proposer=("ops_dm_01", "ops_dm_02", EXERCISE_INJECT),
    ),
    TierRule(
        step=DecisionStep.D2,
        action_type=ActionType.REOPTIMISE_WITHIN_ENVELOPE,
        tier=Tier.T1,
        approver_functions=(),
        proposer=("system:optimiser",),
        note="promotion by a person",
    ),
    TierRule(
        step=DecisionStep.D2,
        action_type=ActionType.STAGE_CREWS_SMALL,
        tier=Tier.T2,
        approver_functions=(ApprovalFunction.OPERATIONS,),
        proposer=("ops_dm_01", "ops_dm_02", EXERCISE_INJECT),
        note="< 1,000 customers, <= 10 targets; approver is not the proposer",
    ),
    TierRule(
        step=DecisionStep.D3,
        action_type=ActionType.CROSS_DOMAIN_PRIORITY,
        tier=Tier.T3,
        approver_functions=(ApprovalFunction.COMMAND, ApprovalFunction.WATER_OPERATIONS),
        proposer=(
            "system:rule:ps17_pressure_floor",
            "system:rule:zone_restoration_order",
            "ops_dm_01",
            "ops_dm_02",
            EXERCISE_INJECT,
        ),
    ),
    TierRule(
        step=DecisionStep.D3,
        action_type=ActionType.BOIL_WATER_NOTICE,
        tier=Tier.T3,
        approver_functions=(ApprovalFunction.WATER_OPERATIONS, ApprovalFunction.COMPLIANCE),
        proposer=("system:rule:bwa_pressure_loss", "system:rule:bwa_pre_landfall"),
    ),
    TierRule(
        step=DecisionStep.D3,
        action_type=ActionType.LIFT_BOIL_WATER_NOTICE,
        tier=Tier.T3,
        approver_functions=(ApprovalFunction.WATER_OPERATIONS, ApprovalFunction.COMPLIANCE),
        proposer=("system:rule:bwa_lift_clean_samples",),
        note="R29 SGW policy (assumed): mirror of the issue; compliance attests SCDES concurrence (SC-L4)",
    ),
    TierRule(
        step=DecisionStep.D3,
        action_type=ActionType.FIELD_RESOURCE_ORDER,
        tier=Tier.T2,
        approver_functions=(ApprovalFunction.LOGISTICS,),
        proposer=(
            "system:rule:zone_hospital_tanker",
            "system:rule:zone_fuel_dispatch",
            "system:rule:zone_fuel_reroute",
            "system:rule:zone_mobile_generator",
            EXERCISE_INJECT,
        ),
        note="R29 SGW policy (assumed): tanker, fuel or mobile generator order; logistics signs",
    ),
    TierRule(
        step=DecisionStep.D4,
        action_type=ActionType.PUBLISH_GLOBAL_ETR,
        tier=Tier.T3,
        approver_functions=(ApprovalFunction.COMMAND, ApprovalFunction.OPERATIONS),
        proposer=("plan_etr_01",),
    ),
    TierRule(
        step=None,
        action_type=ActionType.WORK_ORDER_DRAFT,
        tier=Tier.T1,
        approver_functions=(),
        proposer=("agent", "system:rule:ami_dark_section", EXERCISE_INJECT),
        note="promotion by a person",
    ),
    TierRule(
        step=None,
        action_type=ActionType.SITREP_DRAFT,
        tier=Tier.T1,
        approver_functions=(),
        proposer=("agent",),
        note="promotion by a person",
    ),
    TierRule(
        step=None,
        action_type=ActionType.POLICY_CHANGE,
        tier=Tier.T2,
        approver_functions=(ApprovalFunction.COMPLIANCE,),
        proposer=("system:learning-loop",),
        note="after-action lead-time change (WP-38); approval never applies it",
    ),
)

KILL_TRIGGER_USERS: tuple[str, ...] = ("ic_01", "ops_dm_01", "wtr_lead_01", "exec_01")
KILL_RESTORE_FUNCTIONS: tuple[ApprovalFunction, ...] = (ApprovalFunction.COMMAND, ApprovalFunction.COMPLIANCE)


def tier_rule(action_type: ActionType) -> TierRule:
    for rule in TIER_TABLE:
        if rule.action_type is action_type:
            return rule
    raise KeyError(action_type)


class EnvelopeBound(Contract):
    """Inclusive bounds of one rounded parameter; the only envelope bound shape (K8, K2 EnvelopeApproved)."""

    min: int
    max: int

    @model_validator(mode="after")
    def _ordered(self) -> EnvelopeBound:
        if self.min > self.max:
            raise ValueError("envelope min must not exceed max")
        return self


class Envelope(Contract):
    envelope_id: Identifier
    proposal_id: Identifier
    bounds: dict[str, EnvelopeBound] = Field(description="param key -> inclusive bounds after rounding")
    valid_until_utc: UtcDatetime


def envelope_from_plan(plan: Mapping[str, int], *, pct: int) -> dict[str, EnvelopeBound]:
    """Bounds of +-pct percent around each planned integer quantity (O-04 example: +-20% crews per site)."""
    out: dict[str, EnvelopeBound] = {}
    for key, qty in plan.items():
        delta = (abs(qty) * pct) // 100
        out[key] = EnvelopeBound(min=qty - delta, max=qty + delta)
    return out


def within_bound(bound: EnvelopeBound, value: object) -> bool:
    """The one envelope bounds test (K8, O-04), shared by the contract, the service and the Rego mirror:
    a whole number (not a bool) inside the inclusive bounds."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return float(value).is_integer() and bound.min <= value <= bound.max


def tier_for_reoptimisation(envelope: Envelope, new_params: Mapping[str, object], *, at: datetime) -> Tier:
    """Inside an approved, unexpired envelope a re-optimisation is T1; anything else is T3 again (O-04)."""
    if at > envelope.valid_until_utc:
        return Tier.T3
    if set(new_params) - set(envelope.bounds):
        return Tier.T3
    for key, value in new_params.items():
        if not within_bound(envelope.bounds[key], value):
            return Tier.T3
    return Tier.T1


class BreakGlass(Contract):
    proposal_id: Identifier
    ic_id: Identifier
    reason: str = Field(min_length=10)
    used_at_utc: UtcDatetime
    cosign_due_utc: UtcDatetime
    cosigned_by: Identifier | None = None
    cosigned_at_utc: UtcDatetime | None = None
    flagged_for_after_action: bool = True


def break_glass(*, proposal_id: str, ic_id: str, reason: str, used_at: datetime, tier: Tier) -> BreakGlass:
    """IC alone, mandatory reason, co-sign by the second function within 24 h, auto-flag (O-04)."""
    if tier is not Tier.T3:
        raise ValueError("break-glass applies to T3 actions only")
    return BreakGlass(
        proposal_id=proposal_id,
        ic_id=ic_id,
        reason=reason.strip(),
        used_at_utc=used_at,
        cosign_due_utc=used_at + timedelta(hours=BREAK_GLASS_COSIGN_HOURS),
    )


def cosign_overdue(bg: BreakGlass, *, now: datetime) -> bool:
    return bg.cosigned_at_utc is None and now > bg.cosign_due_utc
