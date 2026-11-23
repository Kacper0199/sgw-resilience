"""Courses of action for D2 crew pre-positioning, the deterministic baselines, VSS, EVPI and the SAA bounds.

Three courses of action differ in what they commit before landfall and in the risk they plan for:

- COA-A "Spend-matched": exactly the early mutual-aid request of the P50 plan, placed for the whole scenario
  set (risk-neutral SAA). Trade-off: no extra money, better placement; still short when the storm is bigger
  than the P50.
- COA-B "Tail hedge": early mutual-aid request sized for the P90 scenario requirement. Its placement uses
  E[CH] + w CVaR90[CH] on `cvar_scenarios` scenarios only if that beats the risk-neutral placement at the same
  cap on CVaR90 out of sample; otherwise it is the risk-neutral "P90-sized request" (the comparison is
  reported either way). Trade-off: far more committed spend and idle crews in small storms, for fewer
  customer-hours in Helene-scale scenarios (the ones the forecast under-predicts).
- COA-C "Own crews, request later": no early mutual aid; mutual aid requested when damage is seen. Trade-off:
  no committed early spend and no idle crews, but later (and, in big storms, scarcer) aid: the most
  customer-hours, and not free: post-landfall aid is paid too.

Every plan keeps at least `home_share_min` of each yard's home crews in place and stays under
`site_cap_persons` per yard (Assumed SGW policy). Baselines: the P50 deterministic plan (A5 baseline) and
the expected-value plan (Birge's EV), both with COA-A's request.
VSS = E_out[CH(baseline)] - E_out[CH(COA-A)] on fresh scenarios. EVPI = E[CH(COA-A)] - E[wait-and-see
CH]. Optimality gap: paired Mak-Morton-Wood estimator
over `replications` independent SAA samples: G_r = mean CH of the COA-A plan on sample r minus the MILP dual
bound on sample r; one-sided 95% t upper bound.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
from scipy import stats

from sgw.approval.envelope import EnvelopeAssessment, assess
from sgw.common import numbers as numbers_mod
from sgw.contracts.approval import EnvelopeBound, envelope_from_plan
from sgw.models.optimise.saa import Evaluation, Policy, Solve, cvar_of, evaluate, solve
from sgw.models.optimise.scenarios import (
    Context,
    ScenarioSet,
    assemble,
    mean_scenario,
    observed_ratio,
    p50_scenario,
    param,
    sample,
    synthetic_truth,
)

ENGINE_VERSION = "a5-saa-1.1"
COA_IDS = ("COA-A", "COA-B", "COA-C")
WS_GAP = 1e-4


@dataclass(frozen=True)
class Cost:
    """Expected mutual-aid person-days and USD (early + post-landfall), engaged from arrival to release."""

    early_person_days: float
    late_person_days: float
    usd: float

    @property
    def person_days(self) -> float:
        return self.early_person_days + self.late_person_days


def cost_of(ctx: Context, scen: ScenarioSet, y: np.ndarray, ev: Evaluation) -> Cost:
    release = float(param("release_hours_after_landfall"))
    rate = float(param("mutual_aid_usd_per_person_day"))
    early_persons = float(y.sum() * ctx.ma_group_size)
    early = early_persons * np.maximum(0.0, release - scen.early_arrival) / 24.0
    late = (
        ev.late * np.maximum(0.0, release - scen.late_delay)
        + ev.overflow * np.maximum(0.0, release - scen.overflow_delay)
    ) / 24.0
    return Cost(float(early.mean()), float(late.mean()), float((early + late).mean() * rate))


@dataclass
class Outcome:
    """A first-stage plan evaluated out of sample and under the two stress views."""

    plan_id: str
    title: str
    trade_off: str
    policy: Policy
    solve: Solve
    oos: Evaluation
    cost: Cost
    truth_ch: float
    stress_ch: float

    @property
    def oos_ch(self) -> np.ndarray:
        return self.oos.ch

    @property
    def oos_idle(self) -> np.ndarray:
        return self.oos.idle

    @property
    def mean_ch(self) -> float:
        return float(self.oos.ch.mean())

    def summary(self, ctx: Context, p50: Outcome | None = None) -> dict[str, Any]:
        alpha = float(param("cvar_alpha"))
        day_rate = float(param("mutual_aid_usd_per_person_day"))
        ma_persons = int(self.solve.y.sum()) * ctx.ma_group_size
        usd_per_ch = None
        if p50 is not None and self is not p50 and p50.mean_ch > self.mean_ch:
            usd_per_ch = round((self.cost.usd - p50.cost.usd) / (p50.mean_ch - self.mean_ch), 2)
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "trade_off": self.trade_off,
            "risk": self.policy.risk,
            "early_mutual_aid_groups": int(self.solve.y.sum()),
            "early_mutual_aid_persons": ma_persons,
            "own_groups_staged": int(self.solve.x.sum()),
            "committed_early_mutual_aid_usd_per_day": int(round(ma_persons * day_rate)),
            "expected_cost": {
                "early_mutual_aid_person_days": round(self.cost.early_person_days),
                "post_landfall_mutual_aid_person_days": round(self.cost.late_person_days),
                "total_mutual_aid_person_days": round(self.cost.person_days),
                "total_mutual_aid_usd": round(self.cost.usd),
                "usd_per_customer_hour_avoided_vs_p50": usd_per_ch,
            },
            "yards": {
                y.yard_id: {
                    "home_groups": int(ctx.home_groups[i]),
                    "own_groups": int(self.solve.x[i]),
                    "mutual_aid_groups": int(self.solve.y[i]),
                    "persons": int(
                        self.solve.x[i] * ctx.own_group_size + self.solve.y[i] * ctx.ma_group_size
                    ),
                }
                for i, y in enumerate(ctx.geo.yards)
            },
            "out_of_sample": {
                "n": int(self.oos.ch.size),
                "expected_customer_hours": round(self.mean_ch),
                "p90_customer_hours": round(float(np.quantile(self.oos.ch, 0.9))),
                f"cvar{int(alpha * 100)}_customer_hours": round(cvar_of(self.oos.ch, alpha)),
                "expected_idle_early_mutual_aid_persons": round(float(self.oos.idle.mean()), 1),
                "expected_late_mutual_aid_persons": round(float(self.oos.late.mean()), 1),
                "expected_second_rotation_mutual_aid_persons": round(float(self.oos.overflow.mean()), 1),
            },
            "synthetic_truth_customer_hours": round(self.truth_ch),
            "observed_scale_stress_customer_hours": round(self.stress_ch),
            "solver": {
                "status": self.solve.status,
                "seconds": round(self.solve.seconds, 3),
                "mip_gap": self.solve.mip_gap,
                "cols": self.solve.n_cols,
                "rows": self.solve.n_rows,
            },
        }


@dataclass
class PlanRun:
    ctx: Context
    caps: dict[str, int]
    outcomes: dict[str, Outcome]
    vss: dict[str, dict[str, float]]
    evpi: dict[str, float]
    mmw: dict[str, Any]
    replications: list[dict[str, Any]]
    cvar_check: dict[str, Any]
    stress_k: float
    truth_k: float
    n_in: int
    n_out: int
    meta: dict[str, Any] = field(default_factory=dict)


def groups_for(ctx: Context, need: float) -> int:
    own_persons = ctx.own_groups * ctx.own_group_size
    return max(0, math.ceil((need - own_persons) / ctx.ma_group_size))


def base_policy(ctx: Context, cap: int, **kw: Any) -> Policy:
    """A COA's cap with the staging rules every plan keeps (home share, site cap, tie-breaking cost)."""
    share = float(param("home_share_min"))
    own_min = tuple(int(math.floor(share * h)) for h in ctx.home_groups)
    return Policy(
        spend_cap_groups=cap,
        own_min=own_min,
        site_cap_persons=int(param("site_cap_persons")),
        early_group_cost_ch=float(param("early_group_cost_ch")),
        **kw,
    )


def stress_set(ctx: Context) -> tuple[ScenarioSet, float]:
    """Every member at the replayed storm's observed hindcast scale (evaluation only, hindcast knowledge)."""
    k = observed_ratio(ctx.scenario)
    m = len(ctx.inputs.members)
    med = np.full(m, ctx.ma_median_h)
    return assemble(ctx, np.arange(m), np.full(m, k), med, med, "observed_scale_stress"), k


def paired(base: np.ndarray, plan: np.ndarray) -> dict[str, float]:
    diff = base - plan
    se = float(diff.std(ddof=1) / math.sqrt(diff.size))
    z = float(stats.norm.ppf(0.975))
    return {
        "value": float(diff.mean()),
        "ci_low": float(diff.mean() - z * se),
        "ci_high": float(diff.mean() + z * se),
        "n": int(diff.size),
        "share_scenarios_better": float((diff > 0).mean()),
    }


def mak_morton_wood(gaps: np.ndarray, upper: np.ndarray) -> dict[str, Any]:
    """Paired MMW: point gap, one-sided 95% t upper bound, both also relative to the mean evaluated cost."""
    m = gaps.size
    mean = float(gaps.mean())
    se = float(gaps.std(ddof=1) / math.sqrt(m)) if m > 1 else 0.0
    t = float(stats.t.ppf(0.95, max(1, m - 1)))
    scale = float(upper.mean())
    return {
        "gap_ch": mean,
        "gap_ch_upper95": mean + t * se,
        "gap_rel": mean / scale,
        "gap_rel_upper95": (mean + t * se) / scale,
        "replications": int(m),
        "estimator": "paired Mak-Morton-Wood (1999), dual bounds, one-sided t",
    }


def run(
    ctx: Context,
    *,
    n_in: int | None = None,
    n_out: int | None = None,
    replications: int | None = None,
    n_evpi: int | None = None,
    n_cvar: int | None = None,
    seed: int | None = None,
) -> PlanRun:
    seed = int(seed if seed is not None else param("seed"))
    n_in = int(n_in or param("scenarios"))
    n_out = int(n_out or param("out_of_sample"))
    reps = int(replications or param("replications"))
    n_evpi = int(n_evpi or param("evpi_out_of_sample"))
    n_cvar = int(n_cvar or param("cvar_scenarios"))
    gap = float(param("mip_rel_gap"))
    limit = float(param("time_limit_s"))
    alpha = float(param("cvar_alpha"))
    weight = float(param("cvar_weight"))

    insample = sample(ctx, n_in, seed, "in_sample")
    tail_sample = sample(ctx, n_cvar, seed + 300_000, "cvar_sample")
    fresh = sample(ctx, n_out, seed + 100_000, "out_of_sample")
    truth = synthetic_truth(ctx)
    stress, stress_k = stress_set(ctx)

    def opt(scen: ScenarioSet, pol: Policy, mip_gap: float = gap) -> Solve:
        return solve(ctx, scen, pol, mip_rel_gap=mip_gap, time_limit_s=limit)

    p50_cap = groups_for(ctx, float(p50_scenario(ctx).need.sum()))
    tail_cap = groups_for(
        ctx, float(np.quantile(tail_sample.need.sum(axis=1), float(param("tail_spend_quantile"))))
    )
    p50_res = opt(p50_scenario(ctx), base_policy(ctx, p50_cap))
    matched = int(p50_res.y.sum())
    caps = {"p50_sized": p50_cap, "spend_matched": matched, "tail": tail_cap, "none": 0}
    pol_a = base_policy(ctx, matched, ma_total_bounds=(matched, matched))
    pol_c = base_policy(ctx, 0)
    pol_b_cvar = base_policy(ctx, tail_cap, risk="cvar", cvar_alpha=alpha, cvar_weight=weight)
    pol_b_neutral = base_policy(ctx, tail_cap)
    b_cvar = opt(tail_sample, pol_b_cvar)
    b_neutral = opt(tail_sample, pol_b_neutral)
    b_cvar_oos = evaluate(ctx, fresh, b_cvar.x, b_cvar.y)
    b_neutral_oos = evaluate(ctx, fresh, b_neutral.x, b_neutral.y)
    cvar_cvar = cvar_of(b_cvar_oos.ch, alpha)
    cvar_neutral = cvar_of(b_neutral_oos.ch, alpha)
    same_plan = bool(np.array_equal(b_cvar.x, b_neutral.x) and np.array_equal(b_cvar.y, b_neutral.y))
    keep_cvar = (not same_plan) and cvar_cvar < cvar_neutral
    cvar_check = {
        "scenarios": n_cvar,
        "cap_groups": tail_cap,
        "same_plan": same_plan,
        f"cvar{int(alpha * 100)}_out_of_sample_cvar_plan": cvar_cvar,
        f"cvar{int(alpha * 100)}_out_of_sample_neutral_plan": cvar_neutral,
        "expected_out_of_sample_cvar_plan": float(b_cvar_oos.ch.mean()),
        "expected_out_of_sample_neutral_plan": float(b_neutral_oos.ch.mean()),
        "kept": "cvar" if keep_cvar else "neutral",
        "cvar_solve_seconds": b_cvar.seconds,
        "cvar_mip_gap": b_cvar.mip_gap,
    }
    if keep_cvar:
        b_title, b_pol, b_res = "Tail hedge: P90-sized request, placed for E + CVaR90", pol_b_cvar, b_cvar
    else:
        b_title, b_pol, b_res = "Tail hedge: P90-sized request", pol_b_neutral, b_neutral

    plans: dict[str, tuple[str, str, Policy, Solve]] = {
        "P50": (
            "P50 deterministic plan",
            "A5 baseline: plans for the median forecast only.",
            base_policy(ctx, p50_cap),
            p50_res,
        ),
        "EV": (
            "Expected-value plan",
            "Textbook VSS baseline: every random input replaced by its mean; same request as COA-A.",
            pol_a,
            opt(mean_scenario(insample), pol_a),
        ),
        "COA-A": (
            "Spend-matched: the P50 request, placed for the spread",
            "Same early mutual-aid request as the P50 plan; crews placed for all scenarios. Still short when "
            "the storm is bigger than the P50.",
            pol_a,
            opt(insample, pol_a),
        ),
        "COA-B": (
            b_title,
            "Commits far more mutual aid before landfall and leaves crews idle in small storms, to cut "
            "customer-hours in Helene-scale scenarios that the forecast under-predicts.",
            b_pol,
            b_res,
        ),
        "COA-C": (
            "Own crews only, request mutual aid after landfall",
            "No early request and no idle crews; post-landfall aid arrives a day or more later and is "
            "scarcer in big storms, so the most customer-hours. Post-landfall aid is still paid.",
            pol_c,
            opt(insample, pol_c),
        ),
    }

    outcomes: dict[str, Outcome] = {}
    for pid, (title, trade, pol, res) in plans.items():
        ev = (
            b_cvar_oos
            if res is b_cvar
            else b_neutral_oos
            if res is b_neutral
            else evaluate(ctx, fresh, res.x, res.y)
        )
        truth_ch = float(evaluate(ctx, truth, res.x, res.y).ch[0])
        stress_ch = float(evaluate(ctx, stress, res.x, res.y).ch.mean())
        outcomes[pid] = Outcome(
            pid, title, trade, pol, res, ev, cost_of(ctx, fresh, res.y, ev), truth_ch, stress_ch
        )

    a = outcomes["COA-A"]
    vss = {
        "ev": paired(outcomes["EV"].oos_ch, a.oos_ch),
        "p50": paired(outcomes["P50"].oos_ch, a.oos_ch),
    }

    ws_in = np.array(
        [opt(insample.subset(np.array([i]), "ws"), pol_a, WS_GAP).objective_ch for i in range(insample.n)]
    )
    evpi_fresh = sample(ctx, n_evpi, seed + 200_000, "evpi")
    ws_out = np.array(
        [opt(evpi_fresh.subset(np.array([i]), "ws"), pol_a, WS_GAP).objective_ch for i in range(evpi_fresh.n)]
    )
    a_on_evpi = evaluate(ctx, evpi_fresh, a.solve.x, a.solve.y).ch
    evpi = {
        "in_sample": float(a.solve.scenario_ch.mean() - ws_in.mean()),
        "out_of_sample": float(a_on_evpi.mean() - ws_out.mean()),
        "out_of_sample_n": int(n_evpi),
        "in_sample_n": int(insample.n),
        "wait_and_see_in_sample": float(ws_in.mean()),
        "wait_and_see_out_of_sample": float(ws_out.mean()),
        "wait_and_see_mip_gap": WS_GAP,
    }

    rep_rows: list[dict[str, Any]] = []
    gaps: list[float] = []
    uppers: list[float] = []
    for rep in range(reps):
        scen = insample if rep == 0 else sample(ctx, n_in, seed + 1_000 * rep, f"rep{rep}")
        res = a.solve if rep == 0 else opt(scen, pol_a)
        upper = float(evaluate(ctx, scen, a.solve.x, a.solve.y).ch.mean())
        gaps.append(upper - res.dual_bound_ch)
        uppers.append(upper)
        rep_rows.append(
            {
                "replication": rep,
                "seconds": res.seconds,
                "mip_gap": res.mip_gap,
                "objective_ch": res.objective_ch,
                "dual_bound_ch": res.dual_bound_ch,
                "coa_a_plan_ch": upper,
                "status": res.status,
            }
        )
    mmw = mak_morton_wood(np.array(gaps), np.array(uppers))
    mmw["scenarios_per_replication"] = n_in
    return PlanRun(
        ctx=ctx,
        caps=caps,
        outcomes=outcomes,
        vss=vss,
        evpi=evpi,
        mmw=mmw,
        replications=rep_rows,
        cvar_check=cvar_check,
        stress_k=stress_k,
        truth_k=float(truth.k[0]),
        n_in=n_in,
        n_out=n_out,
        meta={"seed": seed},
    )


def plan_params(ctx: Context, res: Solve) -> dict[str, int]:
    """Material params of the proposal: crew groups per yard (own + early mutual aid) and the request size."""
    out = {f"crew_groups.{y.yard_id}": int(res.x[i] + res.y[i]) for i, y in enumerate(ctx.geo.yards)}
    out["mutual_aid_groups"] = int(res.y.sum())
    return out


def envelope_bounds(ctx: Context, res: Solve, pct: int | None = None) -> dict[str, EnvelopeBound]:
    """K8 bounds ({min, max}, inclusive, integers) of +-`policy_envelope_pct` around the approved plan."""
    pct = int(pct if pct is not None else numbers_mod.value("policy_envelope_pct"))
    return envelope_from_plan(plan_params(ctx, res), pct=pct)


def reoptimise_within(
    ctx: Context, scen: ScenarioSet, policy: Policy, bounds: dict[str, EnvelopeBound]
) -> Solve:
    """Re-solve on new scenarios with every per-yard total and the request size held inside the envelope, so
    the result stays T1 under the WP-09b envelope rule (`reoptimisation_assessment`)."""
    yard_bounds = {
        i: (bounds[f"crew_groups.{y.yard_id}"].min, bounds[f"crew_groups.{y.yard_id}"].max)
        for i, y in enumerate(ctx.geo.yards)
    }
    ma = bounds["mutual_aid_groups"]
    pol = Policy(
        spend_cap_groups=max(policy.spend_cap_groups, ma.max),
        risk=policy.risk,
        cvar_alpha=policy.cvar_alpha,
        cvar_weight=policy.cvar_weight,
        yard_total_bounds=yard_bounds,
        ma_total_bounds=(ma.min, ma.max),
        own_min=policy.own_min,
        site_cap_persons=policy.site_cap_persons,
        early_group_cost_ch=policy.early_group_cost_ch,
    )
    return solve(
        ctx, scen, pol, mip_rel_gap=float(param("mip_rel_gap")), time_limit_s=float(param("time_limit_s"))
    )


def reoptimisation_assessment(
    bounds: dict[str, EnvelopeBound], params: dict[str, int], *, at: datetime, valid_until: datetime
) -> EnvelopeAssessment:
    """Tier of a re-optimised plan under WP-09b's shared envelope rule (`sgw.approval.envelope.assess`)."""
    return assess(bounds, params, at=at, valid_until=valid_until)
