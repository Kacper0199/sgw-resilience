from __future__ import annotations

import dataclasses
import itertools

import numpy as np
import pytest

from sgw.models.optimise.saa import Policy, cvar_of, delay_costs, evaluate, solve
from sgw.models.optimise.scenarios import Context, Geography, ScenarioSet, Yard, build_context


@pytest.fixture(scope="module")
def ctx() -> Context:
    return build_context("helene", "N")


def toy(ctx: Context) -> Context:
    """Two yards, two clusters: yard 0 is next to cluster 0 but held by wind; yard 1 is far and clear."""
    geo = Geography(
        counties=ctx.geo.counties,
        cluster_of=ctx.geo.cluster_of,
        cluster_lat=np.zeros(2),
        cluster_lon=np.zeros(2),
        cluster_customers=np.ones(2),
        cluster_names=("A", "B"),
        yards=(Yard("Y0", "0", 0.0, 0.0), Yard("Y1", "1", 0.0, 0.0)),
        travel_h=np.array([[1.0, 6.0], [5.0, 2.0]]),
    )
    return dataclasses.replace(
        ctx,
        geo=geo,
        own_groups=2,
        own_group_size=10,
        ma_group_size=10,
        customers_per_person=1.0,
        home_groups=np.array([1, 1]),
        late_first_wave_persons=20.0,
    )


def toy_scenarios() -> ScenarioSet:
    return ScenarioSet(
        need=np.array([[10.0, 0.0], [10.0, 30.0]]),
        hold=np.array([[0.0, 0.0], [8.0, 0.0]]),
        early_arrival=np.array([3.0, -2.0]),
        late_delay=np.array([40.0, 40.0]),
        overflow_delay=np.array([76.0, 76.0]),
        k=np.ones(2),
        member=np.array([1, 2]),
        label="toy",
    )


def brute_force(c: Context, scen: ScenarioSet, cap: int) -> float:
    best = float("inf")
    for x0, x1 in itertools.product(range(c.own_groups + 1), repeat=2):
        if x0 + x1 > c.own_groups:
            continue
        for y0, y1 in itertools.product(range(cap + 1), repeat=2):
            if y0 + y1 > cap:
                continue
            ch = evaluate(c, scen, np.array([x0, x1]), np.array([y0, y1])).ch
            best = min(best, float(ch.mean()))
    return best


def test_milp_optimum_equals_enumeration_on_a_toy_instance(ctx: Context) -> None:
    c, scen = toy(ctx), toy_scenarios()
    res = solve(c, scen, Policy(spend_cap_groups=2), mip_rel_gap=0.0)
    assert res.status == "Optimal"
    assert res.objective_ch == pytest.approx(brute_force(c, scen, 2), rel=1e-6)
    ch = evaluate(c, scen, res.x, res.y).ch
    assert ch.mean() == pytest.approx(res.objective_ch, rel=1e-6)


def test_delay_costs_follow_the_documented_rules(ctx: Context) -> None:
    c, scen = toy(ctx), toy_scenarios()
    own, early, late, overflow = delay_costs(c, scen)
    assert own[1, 0, 1] == 8.0 + 6.0
    assert early[1, 0, 0] == max(0.0, 8.0) + 1.0
    assert early[0, 1, 1] == 3.0 + 2.0
    assert early[1, 1, 1] == 0.0 + 2.0
    assert late[0, 1] == 40.0 + 2.0
    assert overflow[0, 0] == 76.0 + 1.0


def test_late_aid_beyond_the_first_wave_waits_for_the_second_rotation(ctx: Context) -> None:
    c = dataclasses.replace(toy(ctx), late_first_wave_persons=10.0)
    res = solve(c, toy_scenarios(), Policy(0), mip_rel_gap=0.0)
    assert res.late_persons.max() <= 10.0 + 1e-6
    assert res.overflow_persons[0] == pytest.approx(0.0, abs=1e-6)
    assert res.overflow_persons[1] == pytest.approx(40.0 - 20.0 - 10.0, abs=1e-6)


def test_staging_rules_bind_home_share_and_site_cap(ctx: Context) -> None:
    c, scen = toy(ctx), toy_scenarios()
    pol = Policy(2, own_min=(1, 1), site_cap_persons=20)
    res = solve(c, scen, pol, mip_rel_gap=0.0)
    assert (res.x >= 1).all()
    assert (res.x * 10 + res.y * 10 <= 20).all()


def test_tie_breaking_cost_leaves_useless_groups_unrequested(ctx: Context) -> None:
    c = toy(ctx)
    small = dataclasses.replace(toy_scenarios(), need=np.array([[5.0, 0.0], [5.0, 0.0]]))
    res = solve(c, small, Policy(2, early_group_cost_ch=1.0), mip_rel_gap=0.0)
    assert res.y.sum() == 0


def test_more_early_mutual_aid_never_adds_customer_hours(ctx: Context) -> None:
    c, scen = toy(ctx), toy_scenarios()
    values = [solve(c, scen, Policy(cap), mip_rel_gap=0.0).objective_ch for cap in range(4)]
    assert all(b <= a + 1e-6 for a, b in itertools.pairwise(values))


def test_cvar_matches_the_tail_mean() -> None:
    v = np.arange(1.0, 11.0)
    assert cvar_of(v, 0.9) == pytest.approx(10.0)
    assert cvar_of(v, 0.8) == pytest.approx(9.5)
    assert cvar_of(v, 0.85) == pytest.approx((10.0 + 0.5 * 9.0) / 1.5)


def test_cvar_policy_reports_the_sample_cvar_of_its_scenarios(ctx: Context) -> None:
    c, scen = toy(ctx), toy_scenarios()
    res = solve(c, scen, Policy(2, risk="cvar", cvar_alpha=0.5, cvar_weight=1.0), mip_rel_gap=0.0)
    assert res.cvar_ch is not None
    assert res.cvar_ch == pytest.approx(cvar_of(res.scenario_ch, 0.5))
    assert res.objective_ch == pytest.approx(res.scenario_ch.mean() + res.cvar_ch, rel=1e-6)
