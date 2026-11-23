"""Read-side facts of the advisory queue that the browser must not infer (P-19-01/02/04): for a decision case
at the scenario time, the advisory in force, the effective decide-by the previous advisory gave the same
case (the "Earlier by ... · was ..." shift), and the ensemble behind the no-regret share (members that need
the action and members in the ensemble). Computed from the same member table and clock job as the stored
queue (`advisory.compute`, no database), cached per advisory label."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import cache
from typing import Any

from sgw.models.clocks import advisory
from sgw.models.clocks.ps17 import ps17_specs
from sgw.models.clocks.service import QueueResult


@dataclass(frozen=True)
class CaseStory:
    advisory_label: str
    previous_advisory_label: str | None
    previous_effective_decide_by_utc: datetime | None
    members_needing: int | None
    members_total: int | None


@cache
def _table() -> dict[str, Any]:
    return advisory.member_table()


@cache
def _queue(label: str) -> QueueResult:
    return advisory.compute(_table(), label)


@cache
def _members(label: str) -> dict[str, tuple[int, int]]:
    table = _table()
    return {
        s.case_id: (sum(1 for m in s.member_needed if m), len(s.member_needed))
        for s in ps17_specs(table["advisories"][label], table)
        if s.member_needed is not None
    }


def advisory_at(now: datetime) -> str | None:
    """The advisory of the member table in force at `now` (None before the first)."""
    return advisory.advisory_in_force(_table(), now)


def _ordered_labels() -> list[str]:
    adv = _table()["advisories"]
    return sorted(adv, key=lambda label: adv[label]["issued_utc"])


def case_story(case_id: str, now: datetime) -> CaseStory | None:
    """None when no advisory of the table is in force at `now` or the case is not one of its cases."""
    table = _table()
    label = advisory.advisory_in_force(table, now)
    if label is None or case_id not in _queue(label).cases:
        return None
    labels = _ordered_labels()
    previous = labels[labels.index(label) - 1] if labels.index(label) > 0 else None
    before = _queue(previous).cases.get(case_id) if previous else None
    needing, total = _members(label).get(case_id, (None, None))
    return CaseStory(
        advisory_label=label,
        previous_advisory_label=previous if before else None,
        previous_effective_decide_by_utc=before.case.effective_decide_by_utc if before else None,
        members_needing=needing,
        members_total=total,
    )
