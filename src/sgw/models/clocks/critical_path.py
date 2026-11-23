"""Decision critical path: CPM backward pass over the prerequisite DAG, per quantile.

The propagation rule is the K16 one (`sgw.contracts.clocks.propagate`): a prerequisite must have finished
its action by the time its dependent has to be decided. It runs once each for the P10, P50 and P90 decide-by
times, so the effective range is as honest as the own range. A node without its own clock enters with an
unbounded decide-by, so its dependents still bind it; if nothing binds it, it stays unbounded.

Criticality: an edge prerequisite -> dependent is tight when the prerequisite's effective decide-by is within
`tolerance_min` of the dependent's effective decide-by minus the prerequisite's lead time; both ends of a
tight edge are on the critical path, so exact ties count. `bound_by_case_id` is the P50 binder (ties resolve
to the smallest dependent id); the binders at P10 and P90 are reported separately because the binding
dependent can differ by quantile. Slack (CPM total float) is own decide-by minus effective at P50.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sgw.contracts.clocks import ClockNode, CycleError, propagate

QUANTILE_KEYS = ("p10", "p50", "p90")
UNBOUNDED = datetime(9000, 1, 1, tzinfo=UTC)
UNBOUNDED_LIMIT = datetime(8000, 1, 1, tzinfo=UTC)
DEFAULT_TOLERANCE_MIN = 1.0


@dataclass(frozen=True)
class NodeInput:
    case_id: str
    decide_by: Mapping[str, datetime] | None
    action_lead_time_min: int
    prerequisite_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PathResult:
    case_id: str
    effective: dict[str, datetime]
    bound_by_case_id: str | None
    bound_by_by_quantile: dict[str, str | None]
    on_critical_path: bool
    slack_min: float | None
    binding_chain: tuple[str, ...]
    derived: bool

    @property
    def unbounded(self) -> bool:
        return self.effective["p50"] >= UNBOUNDED_LIMIT


def find_cycle(prerequisites: Mapping[str, Sequence[str]]) -> list[str] | None:
    """One cycle as a closed list of case ids (first == last), or None for a DAG. Iterative DFS."""
    state: dict[str, int] = dict.fromkeys(prerequisites, 0)
    for root in sorted(prerequisites):
        if state[root]:
            continue
        path: list[str] = [root]
        iters = [iter(sorted(prerequisites.get(root, ())))]
        state[root] = 1
        while iters:
            nxt = next(iters[-1], None)
            if nxt is None:
                state[path.pop()] = 2
                iters.pop()
                continue
            mark = state.get(nxt, 2)
            if mark == 1:
                return [*path[path.index(nxt) :], nxt]
            if mark == 0:
                state[nxt] = 1
                path.append(nxt)
                iters.append(iter(sorted(prerequisites.get(nxt, ()))))
    return None


def critical_path(
    nodes: Sequence[NodeInput], tolerance_min: float = DEFAULT_TOLERANCE_MIN
) -> dict[str, PathResult]:
    by_id = {n.case_id: n for n in nodes}
    for n in nodes:
        unknown = [p for p in n.prerequisite_ids if p not in by_id]
        if unknown:
            raise KeyError(f"{n.case_id} names unknown prerequisites {unknown}")
    cycle = find_cycle({n.case_id: n.prerequisite_ids for n in nodes})
    if cycle:
        raise CycleError("prerequisite cycle: " + " -> ".join(cycle))
    by_q = {
        q: propagate(
            [
                ClockNode(
                    case_id=n.case_id,
                    decide_by_utc=n.decide_by[q] if n.decide_by is not None else UNBOUNDED,
                    action_lead_time_min=n.action_lead_time_min,
                    prerequisite_ids=n.prerequisite_ids,
                )
                for n in nodes
            ]
        )
        for q in QUANTILE_KEYS
    }
    eff = {cid: {q: by_q[q][cid].effective_decide_by_utc for q in QUANTILE_KEYS} for cid in by_id}
    tol = timedelta(minutes=tolerance_min)
    dependents: dict[str, list[str]] = {cid: [] for cid in by_id}
    for n in nodes:
        for pre in n.prerequisite_ids:
            dependents[pre].append(n.case_id)

    def binder(cid: str, q: str) -> str | None:
        lead = timedelta(minutes=by_id[cid].action_lead_time_min)
        if eff[cid][q] >= UNBOUNDED_LIMIT:
            return None
        tight = sorted(d for d in dependents[cid] if abs(eff[cid][q] - (eff[d][q] - lead)) <= tol)
        return tight[0] if tight else None

    bound = {cid: {q: binder(cid, q) for q in QUANTILE_KEYS} for cid in by_id}
    critical = {cid for cid in by_id if bound[cid]["p50"] is not None}
    critical |= {b for cid in by_id if (b := bound[cid]["p50"]) is not None}
    out: dict[str, PathResult] = {}
    for n in nodes:
        chain = [n.case_id]
        nxt = bound[n.case_id]["p50"]
        while nxt is not None and nxt not in chain:
            chain.append(nxt)
            nxt = bound[nxt]["p50"]
        own = n.decide_by["p50"] if n.decide_by is not None else None
        out[n.case_id] = PathResult(
            case_id=n.case_id,
            effective=eff[n.case_id],
            bound_by_case_id=bound[n.case_id]["p50"],
            bound_by_by_quantile=bound[n.case_id],
            on_critical_path=n.case_id in critical,
            slack_min=None if own is None else (own - eff[n.case_id]["p50"]) / timedelta(minutes=1),
            binding_chain=tuple(chain),
            derived=n.decide_by is None,
        )
    return out


def transitive_prerequisites(prerequisites: Mapping[str, Sequence[str]], case_id: str) -> set[str]:
    seen: set[str] = set()
    stack = list(prerequisites.get(case_id, ()))
    while stack:
        cid = stack.pop()
        if cid not in seen:
            seen.add(cid)
            stack.extend(prerequisites.get(cid, ()))
    return seen
