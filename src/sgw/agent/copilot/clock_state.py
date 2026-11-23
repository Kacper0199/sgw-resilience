"""What became of a decision clock once the advisories are over (R30 phase model).

Storm-night clocks answer "how long is left"; after the final advisory they are history, so each clock the
copilot reads gains two closed hints computed by code at the true scenario time:

- `deadline`: `passed` or `open`, against the effective decide-by of the case's latest proposal (the
  advisory clock when the case has none);
- `decision`: from the latest proposal per case and action (FA2's decisions read): `decided_on_time` /
  `decided_late` (approved or executed, timed by its first authority record on the scenario clock, the
  after-action review's rule; `decided` when it has none), `waiting` / `missed` (still open, the states
  FA2's severity rule queues), `expired`, `closed` (rejected or withdrawn), `draft`, `no_proposal`.

`missed` is then `yes` only for an open proposal past its deadline, an expired one, or a passed clock that
never got a proposal. Before the final advisory nothing changes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sgw.agent.copilot.tools import CopilotTools, ToolOutcome
from sgw.approval.outcome import DECIDED, decision_outcome
from sgw.approval.severity import QUEUE_OPEN_STATES
from sgw.contracts.vocab import ProposalState

CLOSED = frozenset({ProposalState.REJECTED, ProposalState.WITHDRAWN})
RANK = {"decided": 0, "open": 1, "expired": 2, "closed": 3, "draft": 4}


def advisories_over(scenario: str, at: datetime) -> bool:
    from sgw.api.scenario_phase import final_advisory_utc

    final = final_advisory_utc(scenario)
    return final is not None and at >= final


def _group(state: ProposalState) -> str:
    if state in DECIDED:
        return "decided"
    if state in QUEUE_OPEN_STATES:
        return "open"
    if state is ProposalState.EXPIRED:
        return "expired"
    if state in CLOSED:
        return "closed"
    return "draft"


def authority_times(dsn: str, proposal_ids: Sequence[str], at: datetime) -> dict[str, datetime]:

    from sgw.approval import outcome

    if not proposal_ids:
        return {}
    from sgw.common import dbconnect

    with dbconnect.connect(dsn, autocommit=True) as conn:
        return outcome.authority_times(conn, proposal_ids, at)


def clock_state(
    case_id: str,
    clock_due: datetime | None,
    proposals: Sequence[Any],
    now: datetime,
    decided_at: Mapping[str, datetime],
) -> dict[str, str]:
    mine = [p for p in proposals if p.decision_case_id == case_id]
    latest = min(
        mine, key=lambda p: (RANK[_group(ProposalState(p.state))], -p.proposal_version), default=None
    )
    due = latest.effective_decide_by_utc if latest is not None else clock_due
    passed = due is not None and due < now
    if latest is None:
        decision = "no_proposal"
    else:
        group = _group(ProposalState(latest.state))
        if group == "decided":
            settled_as = decision_outcome(
                state=latest.state,
                effective_decide_by_utc=latest.effective_decide_by_utc,
                decided_at=decided_at.get(latest.proposal_id),
            )
            decision = f"decided_{settled_as}" if settled_as else "decided"
        elif group == "open":
            decision = "missed" if passed else "waiting"
        else:
            decision = group
    missed = decision in ("missed", "expired") or (decision == "no_proposal" and passed)
    return {
        "deadline": "passed" if passed else "open",
        "decision": decision,
        "missed": "yes" if missed else "no",
    }


def settled(tools: CopilotTools, outcome: ToolOutcome, hints: Mapping[str, str]) -> ToolOutcome:
    """The decision-clock outcome with `hints` on its item, in the evidence and in the model's text."""
    if outcome.is_error or not outcome.new_items or not hints:
        return outcome
    old = outcome.new_items[0]
    new = old.model_copy(update={"hints": {**old.hints, **hints}})
    tools.items = [new if i.id == old.id else i for i in tools.items]
    return ToolOutcome(tools._view_text([new]), new_items=[new])


def clock_due(outcome: ToolOutcome) -> datetime | None:
    if not outcome.new_items:
        return None
    slot = outcome.new_items[0].values.get("effective_decide_by")
    return slot.value if slot is not None and isinstance(slot.value, datetime) else None
