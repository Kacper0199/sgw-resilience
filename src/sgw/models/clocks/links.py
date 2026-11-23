"""Read-side links of a stored decision case: what it waits for, what waits for it, the whole chain in
decision order, and the Timing shown when the case carries no ensemble share of its own.

Timing inheritance follows the queue engine: the verdict of a case with a share is computed over its whole
prerequisite closure, so every case that must be decided before it, and every case that follows it, takes
that verdict. A case whose decide-by has passed shows `decide_now`. With no share anywhere on its line the
Timing stays `n/a` and a plain reason says why. Pure functions; the stored verdicts are never rewritten.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sgw.contracts.clocks import CaseChainStep
from sgw.contracts.vocab import NoRegretVerdict
from sgw.models.clocks.ps17 import CASE_PLACES

NO_ENSEMBLE = (
    "No forecast ensemble covers this decision, so there is no act-or-wait advice; decide by the time shown."
)
PASSED = "Its decide-by time has passed."
EASTERN = ZoneInfo("America/New_York")
DECIDE_BEFORE = "Decide before the next advisory."


@dataclass(frozen=True)
class CaseFacts:
    case_id: str
    title: str
    effective_decide_by_utc: datetime
    on_critical_path: bool
    verdict: NoRegretVerdict
    prerequisite_ids: tuple[str, ...] = ()
    proposal_id: str | None = None
    next_advisory_utc: datetime | None = None
    verdict_basis_utc: datetime | None = None
    effective_decide_by_p10_utc: datetime | None = None


@dataclass(frozen=True)
class CaseLinks:
    blocked_by: list[str]
    blocks: list[str]
    chain: list[CaseChainStep]
    chain_order: int | None
    timing: NoRegretVerdict
    timing_reason: str | None
    timing_basis: str | None = None


def _edges(facts: Mapping[str, CaseFacts]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    pre = {cid: sorted(p for p in f.prerequisite_ids if p in facts and p != cid) for cid, f in facts.items()}
    post: dict[str, list[str]] = {cid: [] for cid in facts}
    for cid, ps in pre.items():
        for p in ps:
            post[p].append(cid)
    return pre, {cid: sorted(ds) for cid, ds in post.items()}


def _reach(start: str, step: Mapping[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    todo = list(step[start])
    while todo:
        cur = todo.pop()
        if cur not in seen:
            seen.add(cur)
            todo.extend(step[cur])
    return seen


def _ordered(component: set[str], pre: Mapping[str, list[str]], facts: Mapping[str, CaseFacts]) -> list[str]:
    def key(cid: str) -> tuple[datetime, str]:
        return facts[cid].effective_decide_by_utc, cid

    waiting = {cid: {p for p in pre[cid] if p in component} for cid in component}
    order: list[str] = []
    while waiting:
        ready = sorted((cid for cid, ps in waiting.items() if not ps), key=key)
        if not ready:
            order.extend(sorted(waiting, key=key))
            break
        nxt = ready[0]
        order.append(nxt)
        del waiting[nxt]
        for ps in waiting.values():
            ps.discard(nxt)
    return order


def _timing(
    case_id: str,
    facts: Mapping[str, CaseFacts],
    before: set[str],
    after: set[str],
    now: datetime | None,
) -> tuple[NoRegretVerdict, str | None, str | None]:
    own = facts[case_id]
    if (
        now is not None
        and now > own.effective_decide_by_utc
        and own.verdict is NoRegretVerdict.NOT_APPLICABLE
    ):
        return NoRegretVerdict.DECIDE_NOW, PASSED, None
    if own.verdict is not NoRegretVerdict.NOT_APPLICABLE:
        return own.verdict, None, _basis(own, facts, now)
    anchors = sorted(
        (c for c in before | after if facts[c].verdict is not NoRegretVerdict.NOT_APPLICABLE),
        key=lambda c: (c not in after, facts[c].effective_decide_by_utc, c),
    )
    if not anchors:
        return NoRegretVerdict.NOT_APPLICABLE, NO_ENSEMBLE, None
    anchor = facts[anchors[0]]
    basis = _basis(anchor, facts, now)
    if anchor.case_id in after:
        return anchor.verdict, f"Needed before “{anchor.title}”, so it follows that decision's timing.", basis
    return anchor.verdict, f"Follows “{anchor.title}”, so it shares that decision's timing.", basis


def _et(t: datetime, day_of: datetime) -> str:
    local, ref = t.astimezone(EASTERN), day_of.astimezone(EASTERN)
    day = "" if local.date() == ref.date() else f" on {local.day} {local:%b}"
    return f"{local:%H:%M} ET{day}"


def _wait(minutes: float) -> str:
    hours, rest = divmod(round(minutes), 60)
    return " ".join(p for p in (f"{hours} h" if hours else "", f"{rest} min" if rest else "") if p) or "0 min"


def _basis(anchor: CaseFacts, facts: Mapping[str, CaseFacts], now: datetime | None) -> str | None:
    """Why the act-or-wait advice is what it is, in scenario times: the next advisory, the time needed to
    act on it (policy `advisory_processing_latency_min`) and the earliest likely deadline over the decision
    and every step it needs (the queue engine's verdict basis). None when the times are missing or past."""
    from sgw.models.clocks.lead_times import policy_value

    advisory, earliest = anchor.next_advisory_utc, anchor.verdict_basis_utc
    if advisory is None or earliest is None or (now is not None and now >= advisory):
        return None
    if anchor.verdict not in (NoRegretVerdict.DECIDE_NOW, NoRegretVerdict.WAIT_FOR_NEXT_ADVISORY):
        return None
    pre, _ = _edges(facts)
    closure = _reach(anchor.case_id, pre) | {anchor.case_id}
    binding = min(
        (facts[c] for c in closure if facts[c].effective_decide_by_p10_utc is not None),
        key=lambda f: (
            abs(((f.effective_decide_by_p10_utc or earliest) - earliest).total_seconds()),
            f.case_id,
        ),
        default=anchor,
    )
    latency = _wait(policy_value("advisory_processing_latency_min"))
    lead = f"The next advisory at {_et(advisory, advisory)} takes {latency} to act on"
    deadline = f"{_et(earliest, advisory)} (“{binding.title}”)"
    if anchor.verdict is NoRegretVerdict.DECIDE_NOW:
        return f"{lead}, and this plan may need a decision as early as {deadline}. {DECIDE_BEFORE}"
    return (
        f"{lead}, and the earliest likely deadline of this plan is {deadline}. It can wait for that advisory."
    )


def facts_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, CaseFacts]:
    """Case facts from `sgw.approval.repository.CASE_GRAPH` rows, keyed by case id."""
    return {
        r["decision_case_id"]: CaseFacts(
            case_id=r["decision_case_id"],
            title=r["title"],
            effective_decide_by_utc=r["effective_decide_by_utc"],
            on_critical_path=r["on_critical_path"],
            verdict=NoRegretVerdict(r["no_regret_verdict"]),
            prerequisite_ids=tuple(r["prerequisite_ids"]),
            proposal_id=r["proposal_id"],
            next_advisory_utc=r.get("next_advisory_utc"),
            verdict_basis_utc=r.get("verdict_basis_utc"),
            effective_decide_by_p10_utc=r.get("effective_decide_by_p10_utc"),
        )
        for r in rows
    }


def case_links(case_id: str, facts: Mapping[str, CaseFacts], now: datetime | None = None) -> CaseLinks:
    """Links and Timing of one stored case among all stored cases. Unknown prerequisite ids are ignored."""
    pre, post = _edges(facts)
    before, after = _reach(case_id, pre), _reach(case_id, post)
    component = {case_id}
    todo = [case_id]
    while todo:
        cur = todo.pop()
        for nb in (*pre[cur], *post[cur]):
            if nb not in component:
                component.add(nb)
                todo.append(nb)
    chain: list[CaseChainStep] = []
    if len(component) > 1:
        chain = [
            CaseChainStep(
                order=i,
                decision_case_id=cid,
                title=facts[cid].title,
                effective_decide_by_utc=facts[cid].effective_decide_by_utc,
                on_critical_path=facts[cid].on_critical_path,
                proposal_id=facts[cid].proposal_id,
                place_ids=list(CASE_PLACES[cid]) if cid in CASE_PLACES else None,
            )
            for i, cid in enumerate(_ordered(component, pre, facts), start=1)
        ]
    order = next((s.order for s in chain if s.decision_case_id == case_id), None)
    timing, reason, basis = _timing(case_id, facts, before, after, now)
    return CaseLinks(
        blocked_by=pre[case_id],
        blocks=post[case_id],
        chain=chain,
        chain_order=order,
        timing=timing,
        timing_reason=reason,
        timing_basis=basis,
    )
