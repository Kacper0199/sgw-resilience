"""The outcome of a closed decision, computed once on the server and read by the queue, the decision
card and the copilot's clock state.

- `on_time` / `late`: approved or executed, timed by its first authority record on the scenario clock
  (execution token issued, break-glass used; the after-action review's rule) against the effective
  decide-by; no outcome when no authority record exists by the scenario time;
- `missed`: expired without the signatures it needed;
- none: still open, a draft, sent back or withdrawn."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

import psycopg

from sgw.contracts.vocab import ProposalState

DecisionOutcome = Literal["on_time", "late", "missed"]
DECIDED = frozenset({ProposalState.APPROVED, ProposalState.EXECUTED})
AUTHORITY_KINDS = ("execution_token_issued", "break_glass_used")


def decision_outcome(
    *, state: ProposalState | str, effective_decide_by_utc: datetime, decided_at: datetime | None
) -> DecisionOutcome | None:
    current = ProposalState(state)
    if current is ProposalState.EXPIRED:
        return "missed"
    if current not in DECIDED or decided_at is None:
        return None
    return "on_time" if decided_at <= effective_decide_by_utc else "late"


def authority_times(
    conn: psycopg.Connection[Any], proposal_ids: Sequence[str], at: datetime
) -> dict[str, datetime]:
    """First authority record per proposal at or before `at`: the scenario time a decision took effect."""
    if not proposal_ids:
        return {}
    rows = conn.execute(
        "SELECT subject, min(occurred_at) FROM audit_event WHERE subject = ANY(%s) AND kind = ANY(%s)"
        " AND occurred_at <= %s GROUP BY subject",
        (list(proposal_ids), list(AUTHORITY_KINDS), at),
    ).fetchall()
    return {str(subject): when for subject, when in rows}
