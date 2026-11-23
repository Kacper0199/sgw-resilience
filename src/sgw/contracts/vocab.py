"""K7 shared vocabularies.

Values are appended, never reordered or removed, after the W0 freeze. Each enum is exported to
TypeScript (`web/src/contracts/vocab.gen.ts`) and to Postgres domains (`contracts/db/vocab_domains.sql`).
"""

from __future__ import annotations

from enum import StrEnum


class RunMode(StrEnum):
    LIVE = "live"
    REPLAY = "replay"
    BACKFILL = "backfill"
    SHADOW = "shadow"
    WHAT_IF = "what_if"


class FeedMode(StrEnum):
    LIVE = "live"
    REPLAY = "replay"
    SYNTHETIC = "synthetic"


class ScenarioMode(StrEnum):
    REPLAY = "REPLAY"
    EXERCISE = "EXERCISE"


class CrewStatus(StrEnum):
    AVAILABLE = "available"
    STAGED = "staged"
    ENROUTE = "enroute"
    ONSITE = "onsite"
    BLOCKED = "blocked"
    DONE = "done"
    OFF_SHIFT = "off_shift"


class BlockReason(StrEnum):
    SAFETY_HOLD = "safety_hold"
    ROAD_CLOSED = "road_closed"
    WIND_ABOVE_BUCKET_LIMIT = "wind_above_bucket_limit"
    AWAITING_MATERIAL = "awaiting_material"
    AWAITING_SWITCHING = "awaiting_switching"


class Quality(StrEnum):
    GOOD = "good"
    SUSPECT = "suspect"
    BAD = "bad"
    MISSING = "missing"


class Finality(StrEnum):
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"
    RETRACTED = "retracted"


class UiSeverity(StrEnum):
    CRITICAL = "critical"
    SEVERE = "severe"
    ELEVATED = "elevated"
    ADVISORY = "advisory"
    NORMAL = "normal"
    UNKNOWN_STALE = "unknown_stale"


class Classification(StrEnum):
    C0 = "C0"
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"
    C3_N = "C3-N"
    C4 = "C4"
    CX = "CX"


class Trust(StrEnum):
    SYSTEM = "system"
    VERIFIED_INTERNAL = "verified_internal"
    INTERNAL_FREE_TEXT = "internal_free_text"
    EXTERNAL = "external"


class Tier(StrEnum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"


class ProposalState(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"
    ESCALATED = "escalated"
    EXECUTED = "executed"


class EffectState(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERY_UNKNOWN = "delivery_unknown"
    ACKNOWLEDGED = "acknowledged"


class KillLevel(StrEnum):
    K0 = "K0"
    K1 = "K1"
    K2 = "K2"
    K3 = "K3"
    K4 = "K4"


class DegradedMode(StrEnum):
    M0 = "M0"
    M1 = "M1"
    M2 = "M2"
    M3 = "M3"
    M4 = "M4"


class Domain(StrEnum):
    ELECTRIC = "electric"
    WATER = "water"


class ApprovalFunction(StrEnum):
    """X-01: PS DC-10 functions plus `communications`, reserved and unused in seeds."""

    COMMAND = "command"
    OPERATIONS = "operations"
    PLANNING = "planning"
    LOGISTICS = "logistics"
    WATER_OPERATIONS = "water_operations"
    COMPLIANCE = "compliance"
    EXECUTIVE = "executive"
    AUDIT = "audit"
    PLATFORM = "platform"
    DATA = "data"
    COMMUNICATIONS = "communications"


class RiskBand(StrEnum):
    VERY_LOW = "very_low"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


class ClockKind(StrEnum):
    RULE_DEADLINE = "rule_deadline"
    MODEL_ESTIMATE = "model_estimate"


class NoRegretVerdict(StrEnum):
    ACT_NOW = "act_now"
    WAIT_FOR_NEXT_ADVISORY = "wait_for_next_advisory"
    NOT_APPLICABLE = "n/a"
    DECIDE_NOW = "decide_now"


class Module(StrEnum):
    MAP = "map"
    DECISIONS = "decisions"
    FORECAST = "forecast"
    CREWS = "crews"
    WATER = "water"
    ASK = "ask"
    BRIEF = "brief"
    AFTER_ACTION = "after_action"
    HEALTH = "health"
    READINESS = "readiness"
    ADMIN = "admin"


class DecisionStep(StrEnum):
    D1 = "D1"
    D2 = "D2"
    D3 = "D3"
    D4 = "D4"
    D5 = "D5"


class ActionType(StrEnum):
    SET_EVENT_TYPE = "set_event_type"
    PREPOSITION_CREWS = "preposition_crews"
    REOPTIMISE_WITHIN_ENVELOPE = "reoptimise_within_envelope"
    STAGE_CREWS_SMALL = "stage_crews_small"
    MUTUAL_AID_REQUEST = "mutual_aid_request"
    CROSS_DOMAIN_PRIORITY = "cross_domain_priority"
    BOIL_WATER_NOTICE = "boil_water_notice"
    LIFT_BOIL_WATER_NOTICE = "lift_boil_water_notice"
    FIELD_RESOURCE_ORDER = "field_resource_order"
    PUBLISH_GLOBAL_ETR = "publish_global_etr"
    WORK_ORDER_DRAFT = "work_order_draft"
    SITREP_DRAFT = "sitrep_draft"
    POLICY_CHANGE = "policy_change"


class InitiatorKind(StrEnum):
    PERSON = "person"
    SYSTEM_RULE = "system_rule"
    AGENT = "agent"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    BREAK_GLASS = "break_glass"
    COSIGN = "cosign"


class CommitmentState(StrEnum):
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    DRIFTED = "drifted"
    MET = "met"
    MISSED = "missed"
    CANCELLED = "cancelled"


class WebhookDeliveryState(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    RETRYING = "retrying"
    FAILED = "failed"
    DISABLED = "disabled"


class ApiScope(StrEnum):
    DECISIONS_READ = "decisions:read"
    CLOCKS_READ = "clocks:read"
    COMMITMENTS_READ = "commitments:read"
    WEBHOOKS_MANAGE = "webhooks:manage"


class NumberLabel(StrEnum):
    F = "F"
    C = "C"
    A = "A"
    U = "U"
    P = "P"
    S = "S"


class NumberKind(StrEnum):
    FACT = "fact"
    COMPUTED = "computed"
    ASSUMPTION = "assumption"
    POLICY = "policy"


class EvalSplit(StrEnum):
    DEV = "dev"
    HELDOUT_FAMILY_B = "heldout_family_b"
    REAL_LOSO = "real_loso"
    LADI_REFERENCE = "ladi_reference"
    HELDOUT = "heldout"


class ModelAlias(StrEnum):
    SONNET = "sonnet"
    HAIKU = "haiku"
    OPUS = "opus"


class Effort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


ALL_VOCABS: dict[str, type[StrEnum]] = {
    "run_mode": RunMode,
    "feed_mode": FeedMode,
    "scenario_mode": ScenarioMode,
    "crew_status": CrewStatus,
    "block_reason": BlockReason,
    "quality": Quality,
    "finality": Finality,
    "ui_severity": UiSeverity,
    "classification": Classification,
    "trust": Trust,
    "tier": Tier,
    "proposal_state": ProposalState,
    "effect_state": EffectState,
    "kill_level": KillLevel,
    "degraded_mode": DegradedMode,
    "domain": Domain,
    "approval_function": ApprovalFunction,
    "risk_band": RiskBand,
    "clock_kind": ClockKind,
    "no_regret_verdict": NoRegretVerdict,
    "module": Module,
    "decision_step": DecisionStep,
    "action_type": ActionType,
    "initiator_kind": InitiatorKind,
    "approval_decision": ApprovalDecision,
    "commitment_state": CommitmentState,
    "webhook_delivery_state": WebhookDeliveryState,
    "api_scope": ApiScope,
    "number_label": NumberLabel,
    "number_kind": NumberKind,
    "eval_split": EvalSplit,
    "model_alias": ModelAlias,
    "effort": Effort,
}

SIDE_EFFECT_FREE_RUN_MODES = frozenset(m for m in RunMode if m is not RunMode.LIVE)

CLASSIFICATION_ORDER: tuple[Classification, ...] = (
    Classification.C0,
    Classification.C1,
    Classification.C2,
    Classification.C3,
    Classification.C3_N,
    Classification.C4,
    Classification.CX,
)


def high_water(*classes: Classification) -> Classification:
    if not classes:
        raise ValueError("high_water needs at least one classification")
    return max(classes, key=CLASSIFICATION_ORDER.index)


RISK_BAND_UPPER_PPM: dict[RiskBand, int] = {
    RiskBand.VERY_LOW: 50_000,
    RiskBand.LOW: 200_000,
    RiskBand.MODERATE: 500_000,
    RiskBand.HIGH: 800_000,
    RiskBand.VERY_HIGH: 1_000_000,
}


def risk_band_for(p_ppm: int) -> RiskBand:
    if not 0 <= p_ppm <= 1_000_000:
        raise ValueError("p_ppm out of range")
    for band, upper in RISK_BAND_UPPER_PPM.items():
        if p_ppm < upper or band is RiskBand.VERY_HIGH:
            return band
    raise AssertionError("unreachable")
