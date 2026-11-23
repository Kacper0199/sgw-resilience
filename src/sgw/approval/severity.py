"""Queue severity of a decision (K7 `UiSeverity`), computed once on the server from the decision clock and
the scenario time; the UI only renders it.

Rule, evaluated in order for an open proposal (`proposed`, `in_review`, `escalated`):
- Critical: the effective decide-by has passed (missed).
- Severe: less than `policy_decision_severe_within_min` to the effective decide-by.
- Elevated: on the critical path, or less than `policy_decision_elevated_within_min` left.
- Advisory: otherwise.
Every other state (draft, approved, executed, rejected, withdrawn, expired) waits on no signer, so it shows
the observed state of what the decision acts on: `observed` when the caller found it still in trouble (a
water zone below the state floor), else Normal. `unknown_stale` is not produced here; it marks stale data,
not a decision clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sgw.common import numbers
from sgw.contracts.vocab import ProposalState, UiSeverity

QUEUE_OPEN_STATES = frozenset({ProposalState.PROPOSED, ProposalState.IN_REVIEW, ProposalState.ESCALATED})
SEVERE_KEY = "policy_decision_severe_within_min"
ELEVATED_KEY = "policy_decision_elevated_within_min"


def decision_severity(
    *,
    state: ProposalState | str,
    effective_decide_by_utc: datetime,
    on_critical_path: bool,
    now: datetime,
    observed: UiSeverity | None = None,
) -> UiSeverity:
    if ProposalState(state) not in QUEUE_OPEN_STATES:
        return observed or UiSeverity.NORMAL
    left = effective_decide_by_utc - now
    if left < timedelta(0):
        return UiSeverity.CRITICAL
    if left < timedelta(minutes=numbers.value(SEVERE_KEY)):
        return UiSeverity.SEVERE
    if on_critical_path or left < timedelta(minutes=numbers.value(ELEVATED_KEY)):
        return UiSeverity.ELEVATED
    return UiSeverity.ADVISORY
