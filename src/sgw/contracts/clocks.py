"""K16 decision case and clock.

Clock = consequence time minus action lead time (O-03). Values come only from deterministic code;
the LLM may explain a clock but never sets it. Critical-path propagation: a prerequisite must have
finished its action by the time its dependent has to be decided, so

    effective(p) = min(decide_by(p), min over dependents d of effective(d) - lead_time(p)).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from pydantic import ConfigDict, Field, model_validator

from sgw.contracts.base import Contract, Identifier, Ppm, UtcDatetime
from sgw.contracts.vocab import ClockKind, DecisionStep, Domain, NoRegretVerdict


class ClockBasis(Contract):
    kind: ClockKind
    basis_id: str = Field(description="model id or rule id")
    basis_version: str
    citation: str | None = Field(default=None, description="rule clause, e.g. SC R.61-58.7.E(7)")


class DecisionClock(Contract):
    decide_by_utc: UtcDatetime = Field(description="P50 decide-by")
    decide_by_p10_utc: UtcDatetime
    decide_by_p90_utc: UtcDatetime
    consequence_utc: UtcDatetime
    consequence_p10_utc: UtcDatetime
    consequence_p90_utc: UtcDatetime
    consequence_basis: ClockBasis
    action_lead_time_min: int = Field(ge=0, le=60 * 24 * 14)
    lead_time_basis: ClockBasis
    clock_kind: ClockKind
    if_late: str = Field(min_length=1)

    @model_validator(mode="after")
    def _invariants(self) -> DecisionClock:
        lead = timedelta(minutes=self.action_lead_time_min)
        if not self.consequence_p10_utc <= self.consequence_utc <= self.consequence_p90_utc:
            raise ValueError("consequence range must satisfy P10 <= P50 <= P90")
        if not self.decide_by_p10_utc <= self.decide_by_utc <= self.decide_by_p90_utc:
            raise ValueError("decide-by range must satisfy P10 <= P50 <= P90")
        if self.decide_by_utc != self.consequence_utc - lead:
            raise ValueError("decide_by_utc must equal consequence_utc minus action lead time (O-03)")
        if self.decide_by_p10_utc != self.consequence_p10_utc - lead:
            raise ValueError("decide_by_p10_utc must equal consequence_p10_utc minus action lead time")
        if self.decide_by_p90_utc != self.consequence_p90_utc - lead:
            raise ValueError("decide_by_p90_utc must equal consequence_p90_utc minus action lead time")
        return self


class ClockWaterfall(Contract):
    """`GET proposals/{id}/clock`: the clock basis, shown as consequence minus lead time."""

    decision_case_id: Identifier
    consequence_utc: UtcDatetime
    consequence_range_utc: tuple[UtcDatetime, UtcDatetime]
    consequence_basis: ClockBasis
    action_lead_time_min: int = Field(ge=0)
    lead_time_basis: ClockBasis
    decide_by_utc: UtcDatetime
    effective_decide_by_utc: UtcDatetime
    bound_by_case_id: Identifier | None = None


LINK_FIELDS = ("blocked_by", "blocks", "chain", "chain_order", "timing", "timing_reason", "timing_basis")


def _optional_members(schema: dict[str, Any]) -> None:
    """The member counts and the read-side link fields are additive (G1): optional in the schema and
    TypeScript, as older mocks omit them."""
    names = ("no_regret_members", "ensemble_members", *LINK_FIELDS)
    schema["required"] = [r for r in schema.get("required", []) if r not in names]
    for name in names:
        schema.get("properties", {}).get(name, {}).pop("default", None)


def _unset(value: object) -> bool:
    return value is None


def _optional_places(schema: dict[str, Any]) -> None:
    """`place_ids` is additive: optional in the schema and TypeScript, as older mocks omit it."""
    schema["required"] = [r for r in schema.get("required", []) if r != "place_ids"]
    schema.get("properties", {}).get("place_ids", {}).pop("default", None)


class CaseChainStep(Contract):
    """One decision of the chain around a case, in the order the chain has to be decided (read side)."""

    model_config = ConfigDict(json_schema_extra=_optional_places)

    order: int = Field(ge=1, description="1 is decided first")
    decision_case_id: Identifier
    title: str
    effective_decide_by_utc: UtcDatetime
    on_critical_path: bool
    proposal_id: Identifier | None = Field(description="the latest proposal on this case; null when none")
    place_ids: list[Identifier] | None = Field(
        default=None,
        exclude_if=_unset,
        description="the assets where this step happens, for a step whose own targets are vehicles or that"
        " has no proposal yet (the pump station a generator is hooked up at, the hospital a tanker serves)",
    )


class DecisionCase(Contract):
    model_config = ConfigDict(json_schema_extra=_optional_members)

    decision_case_id: Identifier
    step: DecisionStep
    title: str
    domain: Domain
    region_id: str
    clock: DecisionClock
    prerequisite_ids: list[Identifier] = Field(default_factory=list)
    effective_decide_by_utc: UtcDatetime
    on_critical_path: bool = False
    no_regret_share_ppm: Ppm | None = None
    no_regret_verdict: NoRegretVerdict = NoRegretVerdict.NOT_APPLICABLE
    next_advisory_utc: UtcDatetime | None = None
    no_regret_members: int | None = Field(
        default=None,
        ge=0,
        exclude_if=lambda v: v is None,
        description="ensemble members in which the action is needed (share numerator); omitted when unknown",
    )
    ensemble_members: int | None = Field(
        default=None,
        ge=1,
        exclude_if=lambda v: v is None,
        description="members in the ensemble behind the no-regret share; omitted when unknown",
    )
    blocked_by: list[Identifier] | None = Field(
        default=None,
        exclude_if=_unset,
        description="cases that must be decided before this one (stored prerequisite edges); API read side",
    )
    blocks: list[Identifier] | None = Field(
        default=None,
        exclude_if=_unset,
        description="cases that cannot be decided before this one; API read side",
    )
    chain: list[CaseChainStep] | None = Field(
        default=None,
        exclude_if=_unset,
        description="every case linked to this one, in decision order; empty when the case is not linked",
    )
    chain_order: int | None = Field(
        default=None, ge=1, exclude_if=_unset, description="this case's position in `chain`; null if unlinked"
    )
    timing: NoRegretVerdict | None = Field(
        default=None,
        exclude_if=_unset,
        description="the Timing shown: the case's own verdict, else the verdict of the linked case whose"
        " ensemble share covers it, decide_now once the decide-by has passed; `n/a` only when no ensemble"
        " covers the chain (then `timing_reason` says so)",
    )
    timing_reason: str | None = Field(
        default=None,
        exclude_if=_unset,
        description="plain sentence when `timing` is not the case's own verdict; null otherwise",
    )
    timing_basis: str | None = Field(
        default=None,
        exclude_if=_unset,
        description="plain sentence with the scenario times behind an act-or-wait Timing: the next advisory,"
        " the time needed to act on it and the earliest likely deadline of the plan; null for Act now,"
        " without an ensemble, or once that advisory or the decide-by has passed",
    )

    @model_validator(mode="after")
    def _effective_not_later(self) -> DecisionCase:
        if self.effective_decide_by_utc > self.clock.decide_by_utc:
            raise ValueError("effective decide-by may never be later than the case's own decide-by")
        if self.decision_case_id in self.prerequisite_ids:
            raise ValueError("a case cannot be its own prerequisite")
        if self.no_regret_verdict is not NoRegretVerdict.NOT_APPLICABLE and (
            self.no_regret_share_ppm is None or self.next_advisory_utc is None
        ):
            raise ValueError("a no-regret verdict needs a share and the next advisory time")
        return self


class ClockNode(Contract):
    case_id: Identifier
    decide_by_utc: UtcDatetime
    action_lead_time_min: int = Field(ge=0)
    prerequisite_ids: tuple[Identifier, ...] = ()


class PropagatedClock(Contract):
    case_id: Identifier
    effective_decide_by_utc: UtcDatetime
    bound_by_case_id: Identifier | None
    on_critical_path: bool


class CycleError(ValueError):
    pass


def topological_order(nodes: Mapping[str, ClockNode]) -> list[str]:
    indegree = {cid: 0 for cid in nodes}
    dependents: dict[str, list[str]] = {cid: [] for cid in nodes}
    for cid, node in nodes.items():
        for pre in node.prerequisite_ids:
            if pre not in nodes:
                raise KeyError(f"{cid} names unknown prerequisite {pre}")
            indegree[cid] += 1
            dependents[pre].append(cid)
    ready = sorted(cid for cid, deg in indegree.items() if deg == 0)
    order: list[str] = []
    while ready:
        cid = ready.pop(0)
        order.append(cid)
        for dep in sorted(dependents[cid]):
            indegree[dep] -= 1
            if indegree[dep] == 0:
                ready.append(dep)
        ready.sort()
    if len(order) != len(nodes):
        raise CycleError("prerequisite graph has a cycle: " + ", ".join(sorted(set(nodes) - set(order))))
    return order


def propagate(nodes: Sequence[ClockNode]) -> dict[str, PropagatedClock]:
    by_id = {n.case_id: n for n in nodes}
    if len(by_id) != len(nodes):
        raise ValueError("duplicate case ids")
    order = topological_order(by_id)
    effective: dict[str, datetime] = {cid: by_id[cid].decide_by_utc for cid in by_id}
    bound_by: dict[str, str | None] = {cid: None for cid in by_id}
    for cid in reversed(order):
        node = by_id[cid]
        for pre in node.prerequisite_ids:
            candidate = effective[cid] - timedelta(minutes=by_id[pre].action_lead_time_min)
            if candidate < effective[pre]:
                effective[pre] = candidate
                bound_by[pre] = cid
    binding = {b for b in bound_by.values() if b is not None}
    return {
        cid: PropagatedClock(
            case_id=cid,
            effective_decide_by_utc=effective[cid],
            bound_by_case_id=bound_by[cid],
            on_critical_path=bound_by[cid] is not None or cid in binding,
        )
        for cid in order
    }


def no_regret_verdict(
    *,
    share_ppm: int | None,
    effective_decide_by_utc: datetime,
    next_advisory_utc: datetime | None,
    act_now_threshold_ppm: int,
) -> NoRegretVerdict:
    """`decide_now` when the next advisory lands at or after the effective decide-by (waiting is not an
    option, whatever the share); otherwise `act_now` when acting is not regretted in at least the threshold
    share of scenarios, else `wait_for_next_advisory`. `n/a` without a share or a next advisory."""
    if share_ppm is None or next_advisory_utc is None:
        return NoRegretVerdict.NOT_APPLICABLE
    if next_advisory_utc >= effective_decide_by_utc:
        return NoRegretVerdict.DECIDE_NOW
    if share_ppm >= act_now_threshold_ppm:
        return NoRegretVerdict.ACT_NOW
    return NoRegretVerdict.WAIT_FOR_NEXT_ADVISORY


def build_clock(
    *,
    consequence_p10_utc: datetime,
    consequence_utc: datetime,
    consequence_p90_utc: datetime,
    consequence_basis: ClockBasis,
    action_lead_time_min: int,
    lead_time_basis: ClockBasis,
    if_late: str,
) -> DecisionClock:
    lead = timedelta(minutes=action_lead_time_min)
    return DecisionClock(
        decide_by_utc=consequence_utc - lead,
        decide_by_p10_utc=consequence_p10_utc - lead,
        decide_by_p90_utc=consequence_p90_utc - lead,
        consequence_utc=consequence_utc,
        consequence_p10_utc=consequence_p10_utc,
        consequence_p90_utc=consequence_p90_utc,
        consequence_basis=consequence_basis,
        action_lead_time_min=action_lead_time_min,
        lead_time_basis=lead_time_basis,
        clock_kind=consequence_basis.kind,
        if_late=if_late,
    )
