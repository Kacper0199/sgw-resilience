"""Kill levels K0-K4, degraded modes M0-M4 and what each one leaves the platform able to do.

STM sections 8 and 9: degradation can only reduce autonomy or raise approval; the kill switch is easy to pull
(one listed role) and hard to release (two people, `command` + `compliance`). Every rule here is data, so the
API, the CLI, the reconciler and the tests read one table. The database repeats the hard parts (migration
5000): execution refused from K1 or while a blocking signal is active, agent runs from K2, ingestion and
new proposals from K3, and a kill level lowered only inside a completed two-function restore.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sgw.contracts.vocab import ApprovalFunction, DegradedMode, KillLevel


def kill_rank(level: KillLevel) -> int:
    return int(level.value[1:])


def mode_rank(mode: DegradedMode) -> int:
    return int(mode.value[1:])


def mode_of_rank(rank: int) -> DegradedMode:
    return DegradedMode(f"M{max(0, min(4, rank))}")


KILL_MODE_FLOOR: dict[KillLevel, DegradedMode] = {
    KillLevel.K0: DegradedMode.M0,
    KillLevel.K1: DegradedMode.M0,
    KillLevel.K2: DegradedMode.M2,
    KillLevel.K3: DegradedMode.M3,
    KillLevel.K4: DegradedMode.M4,
}

RESTORE_FUNCTIONS = frozenset({ApprovalFunction.COMMAND, ApprovalFunction.COMPLIANCE})
MODE_RAISE_ROLES = frozenset({"platform_admin"})
MODE_LOWER_FUNCTIONS = frozenset({ApprovalFunction.COMMAND})
RESTORE_TTL_S = 15 * 60
RESTORE_CHECKLIST = (
    "cause_contained",
    "audit_chain_verified",
    "corpus_and_prompts_checked",
    "credentials_rotated_if_relevant",
    "security_smoke_passed",
)


class Capability(StrEnum):
    VIEW_DASHBOARDS = "view_dashboards"
    CREATE_PROPOSALS = "create_proposals"
    APPROVE_AND_EXECUTE = "approve_and_execute"
    AGENT_RUNS = "agent_runs"
    LLM_CALLS = "llm_calls"
    FREE_FORM_PLANS = "free_form_plans"
    INGEST_EXTERNAL = "ingest_external"
    PIPELINE_RUNS = "pipeline_runs"
    MANUAL_WORKFLOW = "manual_workflow"
    CREW_INTO_HAZARD_PROPOSALS = "crew_into_hazard_proposals"


ALL = frozenset(Capability)
KILL_REMOVES: dict[KillLevel, frozenset[Capability]] = {
    KillLevel.K0: frozenset(),
    KillLevel.K1: frozenset({Capability.APPROVE_AND_EXECUTE}),
    KillLevel.K2: frozenset(
        {
            Capability.APPROVE_AND_EXECUTE,
            Capability.AGENT_RUNS,
            Capability.LLM_CALLS,
            Capability.FREE_FORM_PLANS,
        }
    ),
    KillLevel.K3: frozenset(
        {
            Capability.APPROVE_AND_EXECUTE,
            Capability.AGENT_RUNS,
            Capability.LLM_CALLS,
            Capability.FREE_FORM_PLANS,
            Capability.INGEST_EXTERNAL,
            Capability.PIPELINE_RUNS,
            Capability.CREATE_PROPOSALS,
        }
    ),
    KillLevel.K4: ALL,
}
MODE_REMOVES: dict[DegradedMode, frozenset[Capability]] = {
    DegradedMode.M0: frozenset(),
    DegradedMode.M1: frozenset({Capability.FREE_FORM_PLANS}),
    DegradedMode.M2: frozenset({Capability.FREE_FORM_PLANS, Capability.LLM_CALLS}),
    DegradedMode.M3: frozenset(
        {
            Capability.FREE_FORM_PLANS,
            Capability.LLM_CALLS,
            Capability.INGEST_EXTERNAL,
            Capability.PIPELINE_RUNS,
        }
    ),
    DegradedMode.M4: ALL,
}


def capabilities(
    kill: KillLevel, mode: DegradedMode, extra_removed: frozenset[Capability] = frozenset()
) -> dict[Capability, bool]:
    removed = KILL_REMOVES[kill] | MODE_REMOVES[mode] | extra_removed
    return {cap: cap not in removed for cap in Capability}


@dataclass(frozen=True)
class SignalRule:
    """One row of the failure table (STM 8.3): what raises the signal, what follows, how it exits."""

    signal: str
    fault_flag: str
    floor: DegradedMode
    blocks_execution: bool
    removes: frozenset[Capability]
    entry: str
    behaviour: str
    exit: str
    enter_after: int = 2
    exit_after: int = 3


SIGNAL_RULES: tuple[SignalRule, ...] = (
    SignalRule(
        "llm_down",
        "FAULT_LLM_DOWN",
        DegradedMode.M2,
        False,
        frozenset(),
        "gateway unreachable or its circuit breaker open on 2 consecutive probes, or FAULT_LLM_DOWN=1",
        "M2: deterministic only; agent nodes take the template path with the same slot values; dashboards, "
        "stored forecasts, risk scores and the manual approval workflow keep working",
        "flag cleared and 3 consecutive healthy gateway probes (breaker closed)",
    ),
    SignalRule(
        "llm_degraded",
        "FAULT_LLM_DEGRADED",
        DegradedMode.M1,
        False,
        frozenset(),
        "gateway breaker half-open or the budget past its soft stop on 2 consecutive probes",
        "M1: no new free-form agent plans; templates, retrieval without generation and maps stay",
        "3 consecutive probes with the breaker closed and the budget acknowledged",
    ),
    SignalRule(
        "opa_down",
        "FAULT_OPA_DOWN",
        DegradedMode.M1,
        True,
        frozenset({Capability.APPROVE_AND_EXECUTE}),
        "OPA health probe fails twice, or FAULT_OPA_DOWN=1",
        "deny all writes and egress above C0: approvals, tokens and effects refused by the database; the "
        "gateway and the approval service fail closed on their own",
        "3 consecutive healthy OPA probes",
    ),
    SignalRule(
        "audit_down",
        "FAULT_AUDIT_DOWN",
        DegradedMode.M1,
        True,
        frozenset({Capability.APPROVE_AND_EXECUTE}),
        "audit append probe fails twice, or FAULT_AUDIT_DOWN=1",
        "T2 and T3 stop: approvals, tokens and effects refused; reads continue",
        "3 consecutive successful probes and a verified chain",
    ),
    SignalRule(
        "weather_stale",
        "FAULT_WEATHER_STALE",
        DegradedMode.M0,
        False,
        frozenset({Capability.CREW_INTO_HAZARD_PROPOSALS}),
        "NWS or NHC feed past twice its freshness limit, or FAULT_WEATHER_STALE=1",
        "banner with data age; no new crew-into-hazard proposal",
        "fresh validated weather data",
        enter_after=1,
        exit_after=1,
    ),
    SignalRule(
        "telemetry_unverified",
        "FAULT_TELEMETRY_SPOOF",
        DegradedMode.M1,
        False,
        frozenset(),
        "FAULT_TELEMETRY_SPOOF=1 (drill), or a physics or cross-source mismatch flagged by ingest",
        "telemetry shown unverified, tiers raised, no free-form plans; nothing is sent to OT",
        "the source owner clears the source",
        enter_after=1,
        exit_after=1,
    ),
)
RULES_BY_SIGNAL = {rule.signal: rule for rule in SIGNAL_RULES}
MANUAL_SIGNAL = "manual"


@dataclass(frozen=True)
class ModeRule:
    mode: DegradedMode
    name: str
    available: str
    disabled: str


MODE_LADDER: tuple[ModeRule, ...] = (
    ModeRule(DegradedMode.M0, "Normal", "everything allowed by policy", "nothing"),
    ModeRule(
        DegradedMode.M1,
        "Reduced AI",
        "maps, ML, deterministic rules, retrieval without generation, template sitreps",
        "new free-form agent plans",
    ),
    ModeRule(
        DegradedMode.M2,
        "Deterministic only",
        "dashboards, stored forecasts, risk scores, SOP search, manual work orders and approvals",
        "all LLM calls",
    ),
    ModeRule(
        DegradedMode.M3,
        "Local continuity",
        "last signed snapshot, offline SOP pack, cached crew and critical customer lists",
        "new external data, pipeline runs, LLM calls",
    ),
    ModeRule(DegradedMode.M4, "Off", "nothing; existing ICS and control-room procedures", "everything"),
)
