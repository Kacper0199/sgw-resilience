"""Policy data for `policy/approval.rego`, generated from the K8 tier table (PLAN section 2 via
`sgw.contracts.approval.TIER_TABLE`) and the K10 policy numbers. The Rego policy holds no tier, function or
threshold literal; it reads `data.sgw.tiers`, which is this module's output committed at `DATA_PATH`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sgw.common import numbers
from sgw.contracts import approval as ap
from sgw.contracts.golden import POLICY_VERSION
from sgw.contracts.vocab import ActionType, ApprovalFunction, Tier

REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_DIR = REPO_ROOT / "policy"
DATA_PATH = POLICY_DIR / "sgw" / "tiers" / "data.json"
REGO_PATH = POLICY_DIR / "approval.rego"
DATA_DOCUMENT = "sgw/tiers"
POLICY_ID = "sgw-approval"

ESCALATOR_TARGET_LIMIT = 10
ESCALATED_FUNCTIONS: dict[ActionType, tuple[ApprovalFunction, ApprovalFunction]] = {
    ActionType.SET_EVENT_TYPE: (ApprovalFunction.COMMAND, ApprovalFunction.OPERATIONS),
    ActionType.STAGE_CREWS_SMALL: (ApprovalFunction.COMMAND, ApprovalFunction.LOGISTICS),
    ActionType.POLICY_CHANGE: (ApprovalFunction.COMMAND, ApprovalFunction.COMPLIANCE),
    ActionType.FIELD_RESOURCE_ORDER: (ApprovalFunction.COMMAND, ApprovalFunction.LOGISTICS),
}
ESCALATOR_FLAGS: tuple[str, ...] = (
    "customers_unknown",
    "critical_facility",
    "hazard_zone_entry",
    "irreversible",
    "untrusted_evidence_only",
    "conflicting_sources",
    "telemetry_unverified",
    "model_out_of_range",
    "contradicts_sop",
)
COMPUTED_ESCALATORS: tuple[str, ...] = ("customers_ge_limit", "targets_gt_limit", "degraded_mode")
REVIEWABLE_STATES: tuple[str, ...] = ("proposed", "in_review")


def _rule_entry(rule: ap.TierRule) -> dict[str, Any]:
    escalated = ESCALATED_FUNCTIONS.get(rule.action_type)
    if rule.tier is Tier.T2 and escalated is None:
        raise ValueError(f"T2 action {rule.action_type} needs an escalated T3 function pair")
    if rule.tier is not Tier.T2 and escalated is not None:
        raise ValueError(f"only T2 actions escalate; {rule.action_type} is {rule.tier}")
    return {
        "step": rule.step.value if rule.step else None,
        "tier": rule.tier.value,
        "approver_functions": [f.value for f in rule.approver_functions],
        "escalated_functions": [f.value for f in escalated] if escalated else [],
        "proposers": list(rule.proposer),
    }


def build() -> dict[str, Any]:
    return {
        "generated_from": "sgw.contracts.approval.TIER_TABLE (PLAN section 2) and data/numbers/numbers.yaml",
        "policy_version": POLICY_VERSION,
        "rules": {rule.action_type.value: _rule_entry(rule) for rule in ap.TIER_TABLE},
        "approval_tiers": [Tier.T2.value, Tier.T3.value],
        "reviewable_states": list(REVIEWABLE_STATES),
        "escalation": {
            "customer_limit": int(numbers.value("policy_small_staging_customer_limit")),
            "target_limit": ESCALATOR_TARGET_LIMIT,
            "flags": list(ESCALATOR_FLAGS),
            "normal_degraded_mode": "M0",
        },
        "evidence_age_limit_s": {t.value: m * 60 for t, m in ap.EVIDENCE_AGE_LIMIT_MIN.items()},
    }


def render() -> str:
    return json.dumps(build(), indent=2, sort_keys=True) + "\n"


def write(path: Path = DATA_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8", newline="\n")
    return path


def is_current(path: Path = DATA_PATH) -> bool:
    return path.is_file() and path.read_text(encoding="utf-8") == render()
