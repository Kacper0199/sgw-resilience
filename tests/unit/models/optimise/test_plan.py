from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from sgw.common import numbers as numbers_mod
from sgw.contracts.approval import Envelope, tier_for_reoptimisation
from sgw.contracts.eval_report import EvalReport
from sgw.contracts.vocab import Tier
from sgw.models.optimise.coa import (
    COA_IDS,
    PlanRun,
    base_policy,
    envelope_bounds,
    mak_morton_wood,
    plan_params,
    reoptimisation_assessment,
    reoptimise_within,
    run,
)
from sgw.models.optimise.plan import document
from sgw.models.optimise.saa import solve
from sgw.models.optimise.scenarios import (
    build_context,
    member_inputs,
    param,
    sample,
    scale_band,
)
from sgw.models.outage.forecast import serving_model

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def pr() -> PlanRun:
    return run(build_context("helene", "N"), n_out=400, replications=3, n_evpi=10, n_cvar=200)


def test_scale_band_never_uses_the_replayed_storm() -> None:
    lo, hi, ratios = scale_band("helene")
    assert "helene" not in ratios
    assert set(ratios) == {"michael", "ian", "debby"}
    assert lo * hi == pytest.approx(1.0)
    assert hi == pytest.approx(max(max(r, 1 / r) for r in ratios.values()))


def test_planning_inputs_come_from_a_model_that_never_saw_the_replayed_storm() -> None:
    assert "helene" not in serving_model().trained_on
    inputs = member_inputs("helene", "N")
    assert 0 not in inputs.members
    assert len(inputs.members) == 40


def test_full_size_instance_solves_within_limits() -> None:
    ctx = build_context("helene", "N")
    assert len(ctx.geo.yards) >= 10 and ctx.geo.n_clusters == 40
    scen = sample(ctx, int(param("scenarios")), 7, "size")
    assert scen.need.shape == (50, 40)
    res = solve(ctx, scen, base_policy(ctx, 60), mip_rel_gap=0.01, time_limit_s=120)
    assert res.status == "Optimal"
    assert res.seconds <= 120.0
    assert res.mip_gap <= 0.01


def test_vss_is_positive_and_the_stochastic_plan_beats_both_deterministic_plans(pr: PlanRun) -> None:
    for key in ("ev", "p50"):
        assert pr.vss[key]["value"] > 0
    a = pr.outcomes["COA-A"].mean_ch
    assert a < pr.outcomes["P50"].mean_ch
    assert a < pr.outcomes["EV"].mean_ch


def test_evpi_is_nonnegative_and_wait_and_see_bounds_the_saa(pr: PlanRun) -> None:
    assert pr.evpi["in_sample"] >= -1e-6
    assert pr.evpi["wait_and_see_in_sample"] <= pr.outcomes["COA-A"].solve.scenario_ch.mean() + 1e-6
    assert pr.evpi["wait_and_see_mip_gap"] == 1e-4


def test_paired_mak_morton_wood_uses_the_coa_a_plan_on_each_replication(pr: PlanRun) -> None:
    gaps = np.array([r["coa_a_plan_ch"] - r["dual_bound_ch"] for r in pr.replications])
    assert (gaps >= -1e-4 * np.array([r["coa_a_plan_ch"] for r in pr.replications])).all()
    again = mak_morton_wood(gaps, np.array([r["coa_a_plan_ch"] for r in pr.replications]))
    assert pr.mmw["gap_rel_upper95"] == pytest.approx(again["gap_rel_upper95"])
    assert pr.mmw["gap_rel_upper95"] >= pr.mmw["gap_rel"]
    known = mak_morton_wood(np.array([1.0, 2.0, 3.0]), np.array([100.0, 100.0, 100.0]))
    assert known["gap_ch"] == 2.0
    assert known["gap_ch_upper95"] == pytest.approx(2.0 + 2.919986 * 1.0 / np.sqrt(3), rel=1e-5)


def test_courses_of_action_differ_in_substance(pr: PlanRun) -> None:
    p50 = pr.outcomes["P50"]
    a, b, c = (pr.outcomes[k] for k in COA_IDS)
    assert c.solve.y.sum() == 0
    assert a.solve.y.sum() == p50.solve.y.sum() > 0
    assert b.solve.y.sum() > a.solve.y.sum()
    assert np.quantile(b.oos_ch, 0.9) < np.quantile(a.oos_ch, 0.9)
    assert c.mean_ch > a.mean_ch
    assert b.oos_idle.mean() > a.oos_idle.mean() > c.oos_idle.mean() == 0
    assert b.stress_ch < a.stress_ch < c.stress_ch
    assert c.cost.usd > 0 and c.cost.early_person_days == 0
    assert b.cost.usd > a.cost.usd > c.cost.usd


def test_cvar_placement_is_kept_only_when_it_beats_risk_neutral_at_the_same_cap(pr: PlanRun) -> None:
    cc = pr.cvar_check
    assert cc["scenarios"] >= 200
    better = cc["cvar90_out_of_sample_cvar_plan"] < cc["cvar90_out_of_sample_neutral_plan"]
    expected = "cvar" if (better and not cc["same_plan"]) else "neutral"
    assert cc["kept"] == expected
    b = pr.outcomes["COA-B"]
    assert b.policy.risk == expected
    assert ("CVaR" in b.title) == (expected == "cvar")


def test_every_plan_keeps_home_crews_and_respects_the_site_cap(pr: PlanRun) -> None:
    ctx = pr.ctx
    share = float(param("home_share_min"))
    cap = int(param("site_cap_persons"))
    for o in pr.outcomes.values():
        assert (o.solve.x >= np.floor(share * ctx.home_groups)).all()
        persons = o.solve.x * ctx.own_group_size + o.solve.y * ctx.ma_group_size
        assert persons.max() <= cap
    assert int(ctx.home_groups.sum()) == ctx.own_groups


def test_envelope_rule_agrees_with_wp09b_assess_including_one_yard_outside(pr: PlanRun) -> None:
    ctx = pr.ctx
    a = pr.outcomes["COA-A"]
    bounds = envelope_bounds(ctx, a.solve)
    pct = int(numbers_mod.value("policy_envelope_pct"))
    for key, qty in plan_params(ctx, a.solve).items():
        assert bounds[key].min == qty - qty * pct // 100
        assert bounds[key].max == qty + qty * pct // 100
    env = Envelope(
        envelope_id="ENV-CREW-AIK-0926A",
        proposal_id="PRP-CREW-AIK-0926A",
        bounds=bounds,
        valid_until_utc=ctx.landfall_utc,
    )
    nxt = build_context("helene", "N+1")
    re = reoptimise_within(nxt, sample(nxt, 50, 11, "n+1"), a.policy, bounds)
    free = solve(nxt, sample(nxt, 50, 11, "n+1"), base_policy(nxt, pr.caps["tail"]))
    inside = plan_params(ctx, re)
    wide = [k for k, b in bounds.items() if k.startswith("crew_groups.") and b.max > b.min]
    moved = dict(inside)
    src, dst = wide[0], wide[1]
    moved[src] = bounds[src].max + 1
    moved[dst] = moved[dst] - (moved[src] - inside[src])
    assert moved["mutual_aid_groups"] == inside["mutual_aid_groups"]
    assert sum(moved.values()) == sum(inside.values())
    cases = [
        (inside, ctx.issued_utc, Tier.T1),
        (plan_params(ctx, free), ctx.issued_utc, Tier.T3),
        (moved, ctx.issued_utc, Tier.T3),
        (inside, ctx.landfall_utc + timedelta(minutes=1), Tier.T3),
    ]
    for params, at, tier in cases:
        assert tier_for_reoptimisation(env, params, at=at) is tier
        shared = reoptimisation_assessment(bounds, params, at=at, valid_until=env.valid_until_utc)
        assert shared.tier is tier
    assert (
        src
        in reoptimisation_assessment(bounds, moved, at=ctx.issued_utc, valid_until=ctx.landfall_utc).outside
    )


def test_plan_document_carries_envelopes_costs_band_check_and_edxl_requests(pr: PlanRun) -> None:
    doc = json.loads(json.dumps(document(pr)))
    coas = {p["plan_id"]: p for p in doc["plans"] if p["plan_id"] in COA_IDS}
    assert set(coas) == set(COA_IDS)
    assert doc["recommendation"] is None
    band = doc["planning_band_check"]
    assert band["inside_planning_band"] is False and band["synthetic_truth_requirement_over_p50"] > 4
    for pid, plan in coas.items():
        assert plan["tier"] == "T3" and plan["action_type"] == "preposition_crews"
        assert all(set(b) == {"min", "max"} for b in plan["envelope"]["bounds"].values())
        for key in plan["envelope"]["pinned_yards"]:
            bound = plan["envelope"]["bounds"][key]
            assert bound["min"] == bound["max"] < 5
        assert plan["expected_cost"]["total_mutual_aid_usd"] > 0
        req = plan["resource_request"]
        if plan["early_mutual_aid_groups"] == 0:
            assert req is None
            continue
        assert req["MessageContentType"] == "RequestResource"
        quantities = [e["AssignmentInformation"]["Quantity"] for e in req["ResourceInformation"]]
        assert sum(q["MeasuredQuantity"]["Amount"] for q in quantities) == plan["early_mutual_aid_groups"]
        for e in req["ResourceInformation"]:
            requested, estimated = e["ScheduleInformation"]
            assert requested["DateTime"] == estimated["DateTime"]
        assert pid in req["MessageID"]
        assert "risk" not in json.dumps(req).lower()


def test_committed_saa_report_is_k17_valid_with_positive_vss() -> None:
    path = REPO / "evals" / "reports" / "saa.json"
    report = EvalReport.model_validate_json(path.read_text(encoding="utf-8"))
    rows = {m.metric: m for m in report.metrics}
    for key in ("ev", "p50"):
        vss = rows[f"saa.coa_a.vss_vs_{key}_out_of_sample"]
        assert vss.value > 0 and vss.ci_low is not None and vss.ci_low > 0
    assert rows["saa.coa_a.solve_seconds_max_over_replications"].passed
    assert rows["saa.coa_a.solve_seconds_max_over_replications"].n == 10
    assert rows["saa.coa_a.mip_rel_gap_max_over_replications"].passed
    gap = rows["saa.coa_a.optimality_gap_rel_upper95_paired_mak_morton_wood"]
    assert gap.passed and gap.value >= gap.baseline_value and gap.threshold == 0.01
    assert rows["saa.coa_b.cvar_solve_seconds"].passed
    assert rows["saa.coa_a.evpi_out_of_sample"].value >= 0
    assert rows["saa.coa_c.expected_mutual_aid_usd"].value > 0
    assert all(m.split.value == "dev" for m in report.metrics)
