from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from sgw.contracts.clocks import ClockBasis, CycleError
from sgw.contracts.vocab import ClockKind, DecisionStep, Domain, NoRegretVerdict
from sgw.models.clocks.critical_path import NodeInput, critical_path, find_cycle
from sgw.models.clocks.service import CaseSpec, ComputedCase, compute_queue
from sgw.models.clocks.waterfall import AddOnTerm, ConsequenceSpec, InsufficientMembers, estimate

T0 = datetime(2024, 9, 26, 12, 0, tzinfo=UTC)
BASIS = ClockBasis(kind=ClockKind.MODEL_ESTIMATE, basis_id="test.anchor", basis_version="1")
LEADS = ("crew_mobilise_and_stage", "fuel_truck_dispatch", "portable_generator_hookup", "pump_restart_refill")
LEAD_MIN = {
    "crew_mobilise_and_stage": 300,
    "fuel_truck_dispatch": 90,
    "portable_generator_hookup": 150,
    "pump_restart_refill": 30,
}
Q = ("p10", "p50", "p90")

offsets = st.lists(st.integers(min_value=0, max_value=3000), min_size=3, max_size=25)


@st.composite
def dags(draw: st.DrawFn, max_nodes: int = 8) -> list[tuple[list[int], list[int], str]]:
    n = draw(st.integers(min_value=1, max_value=max_nodes))
    nodes = []
    for i in range(n):
        pres = sorted(draw(st.sets(st.integers(min_value=0, max_value=i - 1), max_size=3))) if i else []
        nodes.append((draw(offsets), pres, draw(st.sampled_from(LEADS))))
    return nodes


def _specs(nodes: list[tuple[list[int], list[int], str]], shift_min: int = 0) -> list[CaseSpec]:
    return [
        CaseSpec(
            case_id=f"DC-T-{i}",
            step=DecisionStep.D3,
            title=f"case {i}",
            domain=Domain.WATER,
            region_id="SC-45003",
            consequence=ConsequenceSpec(
                consequence_basis=BASIS,
                anchor_label="anchor",
                anchor_basis=BASIS,
                anchor_utc=[T0 + timedelta(minutes=o + shift_min) for o in offs],
                terms=(AddOnTerm("drain", BASIS, [float(o % 97) for o in offs]),),
            ),
            lead_key=lead,
            if_late="late",
            prerequisite_ids=tuple(f"DC-T-{p}" for p in pres),
        )
        for i, (offs, pres, lead) in enumerate(nodes)
    ]


@given(dags())
@settings(max_examples=150, deadline=None)
def test_queue_invariants(nodes: list[tuple[list[int], list[int], str]]) -> None:
    q = compute_queue(_specs(nodes))
    for cid, c in q.cases.items():
        k = c.case.clock
        lead = timedelta(minutes=k.action_lead_time_min)
        assert k.consequence_p10_utc <= k.consequence_utc <= k.consequence_p90_utc
        assert (k.decide_by_p10_utc, k.decide_by_utc, k.decide_by_p90_utc) == (
            k.consequence_p10_utc - lead,
            k.consequence_utc - lead,
            k.consequence_p90_utc - lead,
        )
        own = {"p10": k.decide_by_p10_utc, "p50": k.decide_by_utc, "p90": k.decide_by_p90_utc}
        for qk in Q:
            assert c.path.effective[qk] <= own[qk]
        assert c.path.effective["p10"] <= c.path.effective["p50"] <= c.path.effective["p90"]
        assert c.path.derived or (c.path.slack_min is not None and c.path.slack_min >= 0)
        for pre in c.case.prerequisite_ids:
            pc = q.cases[pre]
            plead = timedelta(minutes=pc.case.clock.action_lead_time_min)
            for qk in Q:
                assert pc.path.effective[qk] <= c.path.effective[qk] - plead
        deps = [d for d in q.cases.values() if cid in d.case.prerequisite_ids]
        for qk in Q:
            tight = min([own[qk], *(d.path.effective[qk] - lead for d in deps)])
            assert c.path.effective[qk] == tight
        chain = c.path.binding_chain
        assert chain[0] == cid and len(set(chain)) == len(chain)


@given(dags(), st.integers(min_value=-600, max_value=600))
@settings(max_examples=60, deadline=None)
def test_time_shift_equivariance(nodes: list[tuple[list[int], list[int], str]], shift: int) -> None:
    a, b = compute_queue(_specs(nodes)), compute_queue(_specs(nodes, shift))
    for cid in a.cases:
        for qk in Q:
            assert b.cases[cid].path.effective[qk] - a.cases[cid].path.effective[qk] == timedelta(
                minutes=shift
            )


@given(dags(), st.randoms(use_true_random=False))
@settings(max_examples=60, deadline=None)
def test_member_and_case_order_invariance(nodes: list[tuple[list[int], list[int], str]], rnd) -> None:  # type: ignore[no-untyped-def]
    specs = _specs(nodes)
    shuffled_nodes = [(sorted(o, key=lambda _: rnd.random()), p, lead) for o, p, lead in nodes]
    other = _specs(shuffled_nodes)
    rnd.shuffle(other)
    a, b = compute_queue(specs), compute_queue(other)
    assert {k: v.case for k, v in a.cases.items()} == {k: v.case for k, v in b.cases.items()}


def _nodes(dec: list[int], edges: dict[int, tuple[int, ...]], leads: list[int]) -> list[NodeInput]:
    return [
        NodeInput(
            case_id=f"C{i}",
            decide_by={q: T0 + timedelta(minutes=d) for q in Q},
            action_lead_time_min=leads[i],
            prerequisite_ids=tuple(f"C{p}" for p in edges.get(i, ())),
        )
        for i, d in enumerate(dec)
    ]


@given(
    st.lists(st.integers(min_value=0, max_value=2000), min_size=2, max_size=7),
    st.data(),
)
@settings(max_examples=100, deadline=None)
def test_longer_lead_or_extra_edge_never_makes_anything_later(dec: list[int], data: st.DataObject) -> None:
    n = len(dec)
    leads = data.draw(st.lists(st.integers(min_value=0, max_value=400), min_size=n, max_size=n))
    edges = {i: tuple(sorted(data.draw(st.sets(st.integers(0, i - 1), max_size=2)))) for i in range(1, n)}
    base = critical_path(_nodes(dec, edges, leads))
    j = data.draw(st.integers(0, n - 1))
    longer = leads[:]
    longer[j] += data.draw(st.integers(1, 300))
    after_lead = critical_path(_nodes(dec, edges, longer))
    a, b = data.draw(st.integers(0, n - 1)), data.draw(st.integers(0, n - 1))
    assume(a != b)
    lo, hi = min(a, b), max(a, b)
    more = {**edges, hi: tuple(sorted({*edges.get(hi, ()), lo}))}
    after_edge = critical_path(_nodes(dec, more, leads))
    for cid in base:
        assert after_lead[cid].effective["p50"] <= base[cid].effective["p50"]
        assert after_edge[cid].effective["p50"] <= base[cid].effective["p50"]


def test_cycle_is_reported_as_a_closed_path() -> None:
    prereqs = {"A": ("C",), "B": ("A",), "C": ("B",), "D": ()}
    cycle = find_cycle(prereqs)
    assert cycle is not None and cycle[0] == cycle[-1] and set(cycle) == {"A", "B", "C"}
    with pytest.raises(CycleError, match="->"):
        critical_path(_nodes([0, 10, 20, 30], {0: (2,), 1: (0,), 2: (1,)}, [10, 10, 10, 10]))
    assert find_cycle({"A": (), "B": ("A",)}) is None


def test_self_loop_and_unknown_prerequisite() -> None:
    with pytest.raises(CycleError):
        critical_path(_nodes([0], {0: (0,)}, [5]))
    with pytest.raises(KeyError):
        critical_path(_nodes([0], {0: (9,)}, [5]))


def _chain(share: list[bool], next_adv: datetime | None, pre_offset: int = 300) -> list[CaseSpec]:
    """Case V (with a share) needs prerequisite P (lead 90 min) done first."""
    members = len(share)
    pre = CaseSpec(
        "DC-T-P",
        DecisionStep.D3,
        "p",
        Domain.WATER,
        "SC-45003",
        ConsequenceSpec(
            BASIS, "a", BASIS, [T0 + timedelta(minutes=pre_offset + 7 * i) for i in range(members)]
        ),
        "fuel_truck_dispatch",
        "late",
    )
    case = CaseSpec(
        "DC-T-V",
        DecisionStep.D3,
        "v",
        Domain.WATER,
        "SC-45003",
        ConsequenceSpec(BASIS, "a", BASIS, [T0 + timedelta(minutes=600 + 10 * i) for i in range(members)]),
        "pump_restart_refill",
        "late",
        prerequisite_ids=("DC-T-P",),
        member_needed=share,
        next_advisory_utc=next_adv,
    )
    return [pre, case]


def _verdict(share: list[bool], next_min: int, now_min: int | None, latency: float = 60) -> ComputedCase:
    now = None if now_min is None else T0 + timedelta(minutes=now_min)
    q = compute_queue(
        _chain(share, T0 + timedelta(minutes=next_min)),
        now=now,
        act_now_threshold_ppm=800_000,
        advisory_latency_min=latency,
    )
    return q.cases["DC-T-V"]


WAITING = {
    NoRegretVerdict.WAIT_FOR_NEXT_ADVISORY: 0,
    NoRegretVerdict.ACT_NOW: 1,
    NoRegretVerdict.DECIDE_NOW: 1,
}
shares = st.lists(st.booleans(), min_size=3, max_size=30)
minutes_ = st.integers(min_value=-600, max_value=1200)


@given(shares, minutes_, st.none() | minutes_, st.integers(min_value=0, max_value=180))
@settings(max_examples=200, deadline=None)
def test_wait_is_only_offered_when_the_advisory_is_usable_in_time(
    share: list[bool], next_min: int, now_min: int | None, latency: int
) -> None:
    c = _verdict(share, next_min, now_min, latency)
    basis = c.verdict_basis_utc
    assert basis is not None
    assert basis <= c.path.effective["p10"]
    if c.case.no_regret_verdict is NoRegretVerdict.WAIT_FOR_NEXT_ADVISORY:
        next_adv = T0 + timedelta(minutes=next_min)
        assert next_adv + timedelta(minutes=latency) < basis
        assert now_min is None or T0 + timedelta(minutes=now_min) < next_adv
        assert not c.missed
    if c.missed:
        assert c.case.no_regret_verdict is NoRegretVerdict.DECIDE_NOW


@given(shares, st.integers(min_value=0, max_value=30), minutes_, st.none() | minutes_)
@settings(max_examples=150, deadline=None)
def test_verdict_monotone_in_share(share: list[bool], extra: int, next_min: int, now_min: int | None) -> None:
    more = [True] * min(extra, len(share)) + share[min(extra, len(share)) :]
    low, high = _verdict(share, next_min, now_min), _verdict(more, next_min, now_min)
    assert WAITING[high.case.no_regret_verdict] >= WAITING[low.case.no_regret_verdict]
    if low.case.no_regret_verdict is NoRegretVerdict.ACT_NOW:
        assert high.case.no_regret_verdict is NoRegretVerdict.ACT_NOW


@given(shares, minutes_, st.integers(min_value=1, max_value=600), st.none() | minutes_)
@settings(max_examples=150, deadline=None)
def test_later_advisory_never_turns_decide_now_into_wait(
    share: list[bool], next_min: int, delay: int, now_min: int | None
) -> None:
    assume(now_min is None or next_min > now_min)
    early, late = _verdict(share, next_min, now_min), _verdict(share, next_min + delay, now_min)
    if early.case.no_regret_verdict is NoRegretVerdict.DECIDE_NOW:
        assert late.case.no_regret_verdict is NoRegretVerdict.DECIDE_NOW


def test_wait_uses_p10_of_the_prerequisite_chain_not_p50_of_the_case() -> None:
    share = [False] * 10
    c = _verdict(share, 0, None, latency=0)
    p10_pre = c.verdict_basis_utc
    assert p10_pre is not None and p10_pre < c.path.effective["p10"] < c.path.effective["p50"]
    before = int((p10_pre - T0) / timedelta(minutes=1)) - 5
    after = before + 10
    assert _verdict(share, before, None, 0).case.no_regret_verdict is NoRegretVerdict.WAIT_FOR_NEXT_ADVISORY
    assert _verdict(share, after, None, 0).case.no_regret_verdict is NoRegretVerdict.DECIDE_NOW


def test_missed_and_stale_advisory_never_wait() -> None:
    share = [False] * 10
    missed = _verdict(share, 2000, now_min=1500)
    assert missed.missed and missed.case.no_regret_verdict is NoRegretVerdict.DECIDE_NOW
    stale = _verdict(share, -30, now_min=0)
    assert not stale.missed and stale.case.no_regret_verdict is NoRegretVerdict.DECIDE_NOW


def test_unclocked_prerequisite_gets_a_derived_case() -> None:
    no_members = ConsequenceSpec(BASIS, "a", BASIS, [T0 + timedelta(minutes=5)] + [None] * 5)
    with pytest.raises(InsufficientMembers):
        estimate(no_members)
    pre = CaseSpec(
        "P", DecisionStep.D3, "p", Domain.WATER, "SC-45003", no_members, "fuel_truck_dispatch", "late"
    )
    dep = CaseSpec(
        "D",
        DecisionStep.D3,
        "d",
        Domain.WATER,
        "SC-45003",
        ConsequenceSpec(BASIS, "a", BASIS, [T0 + timedelta(minutes=900)] * 3),
        "pump_restart_refill",
        "late",
        prerequisite_ids=("P",),
    )
    q = compute_queue([pre, dep])
    assert q.no_clock == {} and q.dropped_edges == {}
    derived = q.cases["P"]
    assert derived.path.derived and derived.path.bound_by_case_id == "D"
    assert derived.case.clock.consequence_basis.basis_id == "critical_path.required_by"
    assert derived.case.effective_decide_by_utc == q.cases["D"].case.effective_decide_by_utc - timedelta(
        minutes=90
    )
    assert derived.case.effective_decide_by_utc == derived.case.clock.decide_by_utc
    assert derived.case.on_critical_path and q.cases["D"].case.prerequisite_ids == ["P"]


def test_unbound_unclocked_cases_and_dropped_edges_are_kept_apart() -> None:
    none = ConsequenceSpec(BASIS, "a", BASIS, [None] * 4)
    a = CaseSpec("A", DecisionStep.D3, "a", Domain.WATER, "SC-45003", none, "fuel_truck_dispatch", "late")
    b = CaseSpec(
        "B", DecisionStep.D3, "b", Domain.WATER, "SC-45003", none, "pump_restart_refill", "late", ("A",)
    )
    q = compute_queue([a, b])
    assert set(q.no_clock) == {"A", "B"} and q.cases == {} and q.dropped_edges == {}


def test_exact_tie_counts_as_critical() -> None:
    nodes = [
        NodeInput("P", {q: T0 for q in Q}, 60, ()),
        NodeInput("D", {q: T0 + timedelta(minutes=60) for q in Q}, 30, ("P",)),
    ]
    res = critical_path(nodes)
    assert res["P"].on_critical_path and res["D"].on_critical_path
    assert res["P"].bound_by_case_id == "D" and res["P"].slack_min == 0


def test_per_member_propagation_differs_from_summed_quantiles_when_terms_anticorrelate() -> None:
    anchors = [T0 + timedelta(minutes=10 * i) for i in range(11)]
    drain = [float(100 - 10 * i) for i in range(11)]
    est = estimate(ConsequenceSpec(BASIS, "a", BASIS, anchors, (AddOnTerm("drain", BASIS, drain),)))
    assert est.p10_utc == est.p50_utc == est.p90_utc == T0 + timedelta(minutes=100)


def test_lead_registry_values_carry_sop_citations() -> None:
    from sgw.models.clocks.lead_times import registry

    for key, minutes in LEAD_MIN.items():
        lt = registry()[key]
        assert lt.minutes == minutes
        assert lt.basis.basis_id == f"lead_time.{key}" and lt.basis.citation
