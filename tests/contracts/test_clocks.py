from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from sgw.contracts import golden
from sgw.contracts.clocks import (
    ClockBasis,
    ClockNode,
    CycleError,
    DecisionCase,
    build_clock,
    no_regret_verdict,
    propagate,
)
from sgw.contracts.vocab import ClockKind, DecisionStep, Domain, NoRegretVerdict

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = datetime(2024, 9, 27, 0, 0, tzinfo=UTC)
BASIS = ClockBasis(kind=ClockKind.MODEL_ESTIMATE, basis_id="m", basis_version="1")


@st.composite
def dags(draw: st.DrawFn) -> list[ClockNode]:
    n = draw(st.integers(min_value=1, max_value=12))
    nodes = []
    for i in range(n):
        prereqs = draw(st.sets(st.integers(min_value=0, max_value=i - 1), max_size=3)) if i else set()
        nodes.append(
            ClockNode(
                case_id=f"C{i:02d}",
                decide_by_utc=BASE + timedelta(minutes=draw(st.integers(min_value=-600, max_value=3000))),
                action_lead_time_min=draw(st.integers(min_value=0, max_value=720)),
                prerequisite_ids=tuple(f"C{p:02d}" for p in sorted(prereqs)),
            )
        )
    return nodes


@settings(max_examples=300, deadline=None)
@given(dags())
def test_effective_never_later_than_own_and_respects_every_dependent(nodes: list[ClockNode]) -> None:
    out = propagate(nodes)
    by_id = {n.case_id: n for n in nodes}
    for node in nodes:
        eff = out[node.case_id].effective_decide_by_utc
        assert eff <= node.decide_by_utc
        for pre in node.prerequisite_ids:
            assert out[pre].effective_decide_by_utc <= eff - timedelta(
                minutes=by_id[pre].action_lead_time_min
            )
        bound = out[node.case_id].bound_by_case_id
        if bound is None:
            assert eff == node.decide_by_utc
        else:
            assert eff == out[bound].effective_decide_by_utc - timedelta(minutes=node.action_lead_time_min)
            assert out[node.case_id].on_critical_path and out[bound].on_critical_path


@settings(max_examples=200, deadline=None)
@given(dags(), st.data())
def test_cycles_are_rejected(nodes: list[ClockNode], data: st.DataObject) -> None:
    if len(nodes) < 2:
        return
    i = data.draw(st.integers(min_value=1, max_value=len(nodes) - 1))
    j = data.draw(st.integers(min_value=0, max_value=i - 1))
    a, b = nodes[i], nodes[j]
    path_exists = _reaches(nodes, a.case_id, b.case_id)
    if not path_exists:
        nodes[i] = a.model_copy(update={"prerequisite_ids": (*a.prerequisite_ids, b.case_id)})
    nodes[j] = b.model_copy(update={"prerequisite_ids": (*b.prerequisite_ids, a.case_id)})
    with pytest.raises(CycleError):
        propagate(nodes)


def _reaches(nodes: list[ClockNode], start: str, goal: str) -> bool:
    by_id = {n.case_id: n for n in nodes}
    stack, seen = [start], set()
    while stack:
        cur = stack.pop()
        if cur == goal:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(by_id[cur].prerequisite_ids)
    return False


def test_self_loop_and_unknown_prerequisite() -> None:
    with pytest.raises(CycleError):
        propagate(
            [ClockNode(case_id="A", decide_by_utc=BASE, action_lead_time_min=1, prerequisite_ids=("A",))]
        )
    with pytest.raises(KeyError):
        propagate(
            [ClockNode(case_id="A", decide_by_utc=BASE, action_lead_time_min=1, prerequisite_ids=("Z",))]
        )


@settings(max_examples=300, deadline=None)
@given(st.integers(-600, 600), st.integers(0, 600), st.integers(0, 600), st.integers(0, 1440))
def test_clock_ranges_ordered_and_waterfall_holds(c50: int, d10: int, d90: int, lead: int) -> None:
    c = BASE + timedelta(minutes=c50)
    clock = build_clock(
        consequence_p10_utc=c - timedelta(minutes=d10),
        consequence_utc=c,
        consequence_p90_utc=c + timedelta(minutes=d90),
        consequence_basis=BASIS,
        action_lead_time_min=lead,
        lead_time_basis=BASIS,
        if_late="late",
    )
    assert clock.decide_by_p10_utc <= clock.decide_by_utc <= clock.decide_by_p90_utc
    assert clock.consequence_utc - clock.decide_by_utc == timedelta(minutes=lead)


def test_unordered_quantiles_rejected() -> None:
    with pytest.raises(ValidationError):
        build_clock(
            consequence_p10_utc=BASE + timedelta(hours=1),
            consequence_utc=BASE,
            consequence_p90_utc=BASE,
            consequence_basis=BASIS,
            action_lead_time_min=10,
            lead_time_basis=BASIS,
            if_late="late",
        )


def test_decision_case_verdict_needs_share_and_next_advisory() -> None:
    clock = golden.ps17_clock(golden.ADVISORY_N)
    with pytest.raises(ValidationError, match="share"):
        DecisionCase(
            decision_case_id="DC-X",
            step=DecisionStep.D3,
            title="t",
            domain=Domain.WATER,
            region_id="SC-45003",
            clock=clock,
            effective_decide_by_utc=clock.decide_by_utc,
            no_regret_verdict=NoRegretVerdict.ACT_NOW,
        )


def test_decision_case_effective_later_than_own_rejected() -> None:
    clock = golden.ps17_clock(golden.ADVISORY_N)
    with pytest.raises(ValidationError, match="never be later"):
        DecisionCase(
            decision_case_id="DC-X",
            step=DecisionStep.D3,
            title="t",
            domain=Domain.WATER,
            region_id="SC-45003",
            clock=clock,
            effective_decide_by_utc=clock.decide_by_utc + timedelta(minutes=1),
        )


@settings(max_examples=200, deadline=None)
@given(
    st.one_of(st.none(), st.integers(0, 1_000_000)),
    st.integers(-600, 600),
    st.one_of(st.none(), st.integers(-600, 600)),
)
def test_no_regret_verdict_rules(share: int | None, eff: int, nxt: int | None) -> None:
    eff_t = BASE + timedelta(minutes=eff)
    nxt_t = None if nxt is None else BASE + timedelta(minutes=nxt)
    v = no_regret_verdict(
        share_ppm=share, effective_decide_by_utc=eff_t, next_advisory_utc=nxt_t, act_now_threshold_ppm=800_000
    )
    if share is None or nxt_t is None:
        assert v is NoRegretVerdict.NOT_APPLICABLE
    elif nxt_t >= eff_t:
        assert v is NoRegretVerdict.DECIDE_NOW
    else:
        assert v is (NoRegretVerdict.ACT_NOW if share >= 800_000 else NoRegretVerdict.WAIT_FOR_NEXT_ADVISORY)


def test_ps17_hinge_golden_vectors() -> None:
    committed = json.loads((REPO_ROOT / "contracts" / "vectors" / "clock_ps17_hinge.json").read_text())
    assert committed == json.loads(json.dumps(golden.hinge_vectors()))
    n, n1 = committed["cases"]["N"], committed["cases"]["N+1"]
    assert n["ps17"]["decide_by_utc"] == "2024-09-27T05:30:00Z"
    assert n1["ps17"]["decide_by_utc"] == "2024-09-27T04:10:00Z"
    assert n1["ps17"]["decide_by_utc"] < n["ps17"]["decide_by_utc"]
    assert n["ps17"]["no_regret_verdict"] == "wait_for_next_advisory"
    assert n1["ps17"]["no_regret_verdict"] == "act_now"
    for case in (n, n1):
        assert case["crews"]["bound_by_case_id"] == "DC-D3-PS17-POWER"
        assert case["crews"]["effective_decide_by_utc"] < case["crews"]["decide_by_utc"]
