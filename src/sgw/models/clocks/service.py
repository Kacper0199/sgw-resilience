"""Clock service: typed model outputs and rules in, K16 decision cases with waterfall, critical path and
no-regret / wait verdict out. Deterministic code only; no LLM sets or edits a clock (NEW-prod-02).

Verdict (K16 `no_regret_verdict` semantics): waiting for the next advisory is offered only when that advisory,
plus the advisory-processing latency (policy parameter), lands before the earliest **P10** effective decide-by
over the case and all its transitive prerequisites, so a planner never waits into the early tail of any step
the action depends on. Given the scenario clock `now`, a decide-by already passed (`missed`) or a next
advisory that is not in the future never yields `wait_for_next_advisory`; both give `decide_now`.

A prerequisite without its own clock (too few members reach its consequence) still gets a **derived** case
when a clocked dependent binds it: consequence = its effective decide-by plus its own lead time, basis
`critical_path.required_by` naming the binder. Case ids without any clock go to `no_clock`; dropped edges go
to `dropped_edges`, never mixed with case ids.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sgw.common import numbers as numbers_mod
from sgw.contracts.base import ppm_from_fraction
from sgw.contracts.clocks import (
    ClockBasis,
    ClockWaterfall,
    DecisionCase,
    DecisionClock,
    build_clock,
    no_regret_verdict,
)
from sgw.contracts.vocab import ClockKind, DecisionStep, Domain, NoRegretVerdict
from sgw.models.clocks.critical_path import (
    NodeInput,
    PathResult,
    critical_path,
    transitive_prerequisites,
)
from sgw.models.clocks.lead_times import LeadTime, lead_time, policy_value
from sgw.models.clocks.waterfall import (
    ConsequenceEstimate,
    ConsequenceSpec,
    InsufficientMembers,
    TermKind,
    WaterfallRow,
    estimate,
)

SERVICE_ID = "clocks.service"
SERVICE_VERSION = "1.1"


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    step: DecisionStep
    title: str
    domain: Domain
    region_id: str
    consequence: ConsequenceSpec
    lead_key: str
    if_late: str
    prerequisite_ids: tuple[str, ...] = ()
    member_needed: Sequence[bool] | None = None
    next_advisory_utc: datetime | None = None


@dataclass(frozen=True)
class ComputedCase:
    case: DecisionCase
    consequence: ConsequenceEstimate
    lead: LeadTime
    path: PathResult
    verdict_basis_utc: datetime | None
    missed: bool = False

    @property
    def clock(self) -> DecisionClock:
        return self.case.clock

    def waterfall(self) -> ClockWaterfall:
        c = self.case.clock
        return ClockWaterfall(
            decision_case_id=self.case.decision_case_id,
            consequence_utc=c.consequence_utc,
            consequence_range_utc=(c.consequence_p10_utc, c.consequence_p90_utc),
            consequence_basis=c.consequence_basis,
            action_lead_time_min=c.action_lead_time_min,
            lead_time_basis=c.lead_time_basis,
            decide_by_utc=c.decide_by_utc,
            effective_decide_by_utc=self.case.effective_decide_by_utc,
            bound_by_case_id=self.path.bound_by_case_id,
        )

    def waterfall_rows(self) -> tuple[WaterfallRow, ...]:
        """Consequence rows, then lead time (negative) and the critical-path adjustment, each with its id."""
        lead = float(self.lead.minutes)
        adj = {
            q: -(self._decide_by(q) - self.path.effective[q]).total_seconds() / 60.0
            for q in self.path.effective
        }
        return (
            *self.consequence.rows,
            WaterfallRow(
                f"action lead time ({self.lead.key})",
                self.lead.basis,
                -lead,
                -lead,
                -lead,
                term_kind=TermKind.LEAD_TIME,
            ),
            WaterfallRow(
                f"critical path (bound by {self.path.bound_by_case_id or 'none'})",
                None,
                adj["p10"],
                adj["p50"],
                adj["p90"],
                term_kind=TermKind.CRITICAL_PATH,
            ),
        )

    def _decide_by(self, q: str) -> datetime:
        c = self.case.clock
        return {"p10": c.decide_by_p10_utc, "p50": c.decide_by_utc, "p90": c.decide_by_p90_utc}[q]


@dataclass(frozen=True)
class QueueResult:
    cases: dict[str, ComputedCase]
    no_clock: dict[str, str] = field(default_factory=dict)
    dropped_edges: dict[tuple[str, str], str] = field(default_factory=dict)


def share_ppm(member_needed: Sequence[bool]) -> int:
    if not member_needed:
        raise ValueError("no-regret share needs at least one member")
    return ppm_from_fraction(sum(1 for m in member_needed if m) / len(member_needed))


def _derived_estimate(path: PathResult, lead: LeadTime) -> ConsequenceEstimate:
    lt = timedelta(minutes=lead.minutes)
    p10, p50, p90 = (path.effective[q] + lt for q in ("p10", "p50", "p90"))
    basis = ClockBasis(
        kind=ClockKind.MODEL_ESTIMATE,
        basis_id="critical_path.required_by",
        basis_version=SERVICE_VERSION,
        citation=path.bound_by_case_id,
    )
    row = WaterfallRow(
        f"required by {path.bound_by_case_id} (its effective decide-by plus this lead time)",
        basis,
        p10.timestamp(),
        p50.timestamp(),
        p90.timestamp(),
        unit="epoch_s",
        term_kind=TermKind.ANCHOR,
    )
    return ConsequenceEstimate(p10, p50, p90, basis, 0, 0, (row,))


def compute_queue(
    specs: Sequence[CaseSpec],
    *,
    now: datetime | None = None,
    act_now_threshold_ppm: int | None = None,
    advisory_latency_min: float | None = None,
    wait_quantile: str = "p10",
) -> QueueResult:
    if wait_quantile not in ("p10", "p50", "p90"):
        raise ValueError("wait_quantile must be p10, p50 or p90")
    ids = [s.case_id for s in specs]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case ids")
    threshold = (
        int(numbers_mod.value("policy_no_regret_act_now_ppm"))
        if act_now_threshold_ppm is None
        else act_now_threshold_ppm
    )
    latency = timedelta(
        minutes=policy_value("advisory_processing_latency_min")
        if advisory_latency_min is None
        else advisory_latency_min
    )
    by_id = {s.case_id: s for s in specs}
    leads = {s.case_id: lead_time(s.lead_key) for s in specs}
    estimates: dict[str, ConsequenceEstimate] = {}
    reasons: dict[str, str] = {}
    for s in specs:
        try:
            estimates[s.case_id] = estimate(s.consequence)
        except InsufficientMembers as exc:
            reasons[s.case_id] = str(exc)
    own: dict[str, DecisionClock] = {}
    for cid, est in estimates.items():
        own[cid] = _clock(est, leads[cid], by_id[cid].if_late)
    paths = critical_path(
        [
            NodeInput(
                case_id=s.case_id,
                decide_by=(
                    {
                        "p10": own[s.case_id].decide_by_p10_utc,
                        "p50": own[s.case_id].decide_by_utc,
                        "p90": own[s.case_id].decide_by_p90_utc,
                    }
                    if s.case_id in own
                    else None
                ),
                action_lead_time_min=leads[s.case_id].minutes,
                prerequisite_ids=s.prerequisite_ids,
            )
            for s in specs
        ],
        tolerance_min=policy_value("critical_path_tolerance_min"),
    )
    no_clock = {cid: reasons[cid] for cid in by_id if cid not in own and paths[cid].unbounded}
    for cid, path in paths.items():
        if cid not in own and not path.unbounded:
            estimates[cid] = _derived_estimate(path, leads[cid])
            own[cid] = _clock(estimates[cid], leads[cid], by_id[cid].if_late)
    dropped = {
        (s.case_id, pre): f"prerequisite {pre} has no clock and nothing binds it"
        for s in specs
        for pre in s.prerequisite_ids
        if s.case_id in own and pre in no_clock
    }
    prereq_map = {s.case_id: tuple(p for p in s.prerequisite_ids if p in own) for s in specs}
    out: dict[str, ComputedCase] = {}
    for cid, c in own.items():
        s, path = by_id[cid], paths[cid]
        share = share_ppm(s.member_needed) if s.member_needed is not None else None
        closure = transitive_prerequisites(prereq_map, cid) | {cid}
        earliest = min(paths[x].effective[wait_quantile] for x in closure)
        missed = now is not None and now > path.effective["p50"]
        verdict = NoRegretVerdict.NOT_APPLICABLE
        basis_utc: datetime | None = None
        if share is not None and s.next_advisory_utc is not None:
            basis_utc = earliest
            if missed or (now is not None and s.next_advisory_utc <= now):
                verdict = NoRegretVerdict.DECIDE_NOW
            else:
                verdict = no_regret_verdict(
                    share_ppm=share,
                    effective_decide_by_utc=earliest,
                    next_advisory_utc=s.next_advisory_utc + latency,
                    act_now_threshold_ppm=threshold,
                )
        case = DecisionCase(
            decision_case_id=cid,
            step=s.step,
            title=s.title,
            domain=s.domain,
            region_id=s.region_id,
            clock=c,
            prerequisite_ids=list(prereq_map[cid]),
            effective_decide_by_utc=path.effective["p50"],
            on_critical_path=path.on_critical_path,
            no_regret_share_ppm=share,
            no_regret_verdict=verdict,
            next_advisory_utc=s.next_advisory_utc if share is not None else None,
            no_regret_members=sum(1 for m in s.member_needed if m) if s.member_needed else None,
            ensemble_members=len(s.member_needed) if s.member_needed else None,
        )
        out[cid] = ComputedCase(
            case=case,
            consequence=estimates[cid],
            lead=leads[cid],
            path=path,
            verdict_basis_utc=basis_utc,
            missed=missed,
        )
    return QueueResult(cases=out, no_clock=no_clock, dropped_edges=dropped)


def _clock(est: ConsequenceEstimate, lead: LeadTime, if_late: str) -> DecisionClock:
    return build_clock(
        consequence_p10_utc=est.p10_utc,
        consequence_utc=est.p50_utc,
        consequence_p90_utc=est.p90_utc,
        consequence_basis=est.basis,
        action_lead_time_min=lead.minutes,
        lead_time_basis=lead.basis,
        if_late=if_late,
    )
