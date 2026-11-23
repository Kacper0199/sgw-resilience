"""Two-stage stochastic MILP for crew pre-positioning, solved by sample average approximation in HiGHS.

First stage (decided at the advisory, integer):
  x_d  own crew groups staged at yard d          sum_d x_d <= own groups; x_d >= home share x home groups
  y_d  mutual-aid groups requested now to yard d  sum_d y_d <= spend cap (the course of action's policy)
  site cap per yard: own size x_d + mutual-aid size y_d <= staging persons (policy)
Second stage (per scenario s, continuous, persons):
  a_sdc own persons from yard d to cluster c       sum_c a_sdc <= own size * x_d
  b_sdc early mutual aid from yard d to cluster c  sum_c b_sdc <= mutual-aid size * y_d
  l_sc  first-wave mutual aid after landfall       sum_c l_sc <= first-wave persons
  o_sc  later mutual aid (second rotation)         sum_d (a_sdc + b_sdc) + l_sc + o_sc >= need_sc
Cost of a person-unit of work = customers per person x hours until it starts:
  own:   hold_sd + travel_dc
  early: max(early arrival_s, hold_sd) + travel_dc
  late:  late arrival_s + min_d travel_dc;  overflow: overflow arrival_s + min_d travel_dc
CH_s is the scenario's customer-hours of crew-arrival delay. Objective: mean_s CH_s, plus w CVaR_alpha(CH)
for the tail course of action (Rockafellar-Uryasev: eta + 1 / ((1 - alpha) S) sum_s max(0, CH_s - eta)),
plus a tie-breaking cost per early group (so a cap binds only when a group saves something).
The objective is scaled to million customer-hours for the solver.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

import highspy
import numpy as np
import scipy.sparse as sp

from sgw.models.optimise.scenarios import Context, ScenarioSet

SCALE = 1e-6
INF = highspy.kHighsInf


@dataclass(frozen=True)
class Policy:
    spend_cap_groups: int
    risk: Literal["neutral", "cvar"] = "neutral"
    cvar_alpha: float = 0.9
    cvar_weight: float = 1.0
    yard_total_bounds: dict[int, tuple[int, int]] | None = None
    ma_total_bounds: tuple[int, int] | None = None
    own_min: tuple[int, ...] | None = None
    site_cap_persons: int | None = None
    early_group_cost_ch: float = 0.0


@dataclass
class Solve:
    x: np.ndarray
    y: np.ndarray
    objective_ch: float
    scenario_ch: np.ndarray
    idle_ma_persons: np.ndarray
    late_persons: np.ndarray
    overflow_persons: np.ndarray
    mip_gap: float
    dual_bound_ch: float
    seconds: float
    status: str
    n_cols: int
    n_rows: int
    cvar_ch: float | None = None
    meta: dict[str, float] = field(default_factory=dict)


def delay_costs(ctx: Context, scen: ScenarioSet) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Hours until a person-unit of work starts: own (S,D,C), early (S,D,C), late (S,C), overflow (S,C)."""
    travel = ctx.geo.travel_h
    nearest = travel.min(axis=0)[None, :]
    own = scen.hold[:, :, None] + travel[None, :, :]
    early = np.maximum(scen.early_delay[:, None], scen.hold)[:, :, None] + travel[None, :, :]
    late = scen.late_delay[:, None] + nearest
    overflow = scen.overflow_delay[:, None] + nearest
    return own, early, late, overflow


def _ch_matrix(ctx: Context, scen: ScenarioSet) -> np.ndarray:
    own, early, late, overflow = delay_costs(ctx, scen)
    s = scen.n
    parts = [own.reshape(s, -1), early.reshape(s, -1), late, overflow]
    return np.concatenate(parts, axis=1) * ctx.customers_per_person


class _Rows:
    def __init__(self) -> None:
        self.rows: list[np.ndarray] = []
        self.cols: list[np.ndarray] = []
        self.vals: list[np.ndarray] = []
        self.lo: list[float] = []
        self.hi: list[float] = []

    @property
    def n(self) -> int:
        return len(self.lo)

    def add(
        self, entries: list[tuple[np.ndarray, np.ndarray, np.ndarray]], lo: list[float], hi: list[float]
    ) -> None:
        for r, c, v in entries:
            self.rows.append(np.asarray(r))
            self.cols.append(np.asarray(c))
            self.vals.append(np.asarray(v, dtype=float))
        self.lo.extend(lo)
        self.hi.extend(hi)


def solve(
    ctx: Context,
    scen: ScenarioSet,
    policy: Policy,
    *,
    fixed: tuple[np.ndarray, np.ndarray] | None = None,
    mip_rel_gap: float = 0.01,
    time_limit_s: float = 120.0,
    threads: int = 1,
) -> Solve:
    d, c, s = len(ctx.geo.yards), ctx.geo.n_clusters, scen.n
    per = 2 * d * c + 2 * c
    n_first = 2 * d
    cvar = policy.risk == "cvar"
    n_cols = n_first + s * per + (1 + s if cvar else 0)
    cost_rows = _ch_matrix(ctx, scen)

    cost = np.zeros(n_cols)
    lower = np.zeros(n_cols)
    upper = np.full(n_cols, INF)
    upper[:d] = ctx.own_groups
    upper[d:n_first] = policy.spend_cap_groups
    if policy.own_min is not None:
        lower[:d] = np.asarray(policy.own_min, dtype=float)
    cost[d:n_first] = policy.early_group_cost_ch * SCALE
    if fixed is not None:
        lower[:d] = upper[:d] = fixed[0]
        lower[d:n_first] = upper[d:n_first] = fixed[1]
        cost[d:n_first] = 0.0
    for k in range(s):
        cost[n_first + k * per : n_first + (k + 1) * per] = cost_rows[k] * SCALE / s
    eta = n_first + s * per
    if cvar:
        lower[eta] = -INF
        cost[eta] = policy.cvar_weight
        cost[eta + 1 :] = policy.cvar_weight / ((1.0 - policy.cvar_alpha) * s)

    m = _Rows()
    ones_d = np.ones(d)
    if fixed is None:
        m.add([(np.full(d, m.n), np.arange(d), ones_d)], [-INF], [float(ctx.own_groups)])
        m.add([(np.full(d, m.n), np.arange(d, 2 * d), ones_d)], [-INF], [float(policy.spend_cap_groups)])
        if policy.ma_total_bounds is not None:
            lo, hi = policy.ma_total_bounds
            m.add([(np.full(d, m.n), np.arange(d, 2 * d), ones_d)], [float(lo)], [float(hi)])
        for yard, (lo, hi) in sorted((policy.yard_total_bounds or {}).items()):
            m.add([(np.array([m.n, m.n]), np.array([yard, d + yard]), np.ones(2))], [float(lo)], [float(hi)])
        if policy.site_cap_persons is not None:
            r0 = m.n
            m.add(
                [
                    (r0 + np.arange(d), np.arange(d), np.full(d, float(ctx.own_group_size))),
                    (r0 + np.arange(d), d + np.arange(d), np.full(d, float(ctx.ma_group_size))),
                ],
                [-INF] * d,
                [float(policy.site_cap_persons)] * d,
            )

    dc = np.arange(d * c)
    by_yard = np.repeat(np.arange(d), c)
    by_cluster = np.tile(np.arange(c), d)
    for k in range(s):
        base = n_first + k * per
        a0, b0, l0, o0 = base, base + d * c, base + 2 * d * c, base + 2 * d * c + c
        r = m.n
        m.add(
            [
                (r + by_yard, a0 + dc, np.ones(d * c)),
                (r + np.arange(d), np.arange(d), np.full(d, -float(ctx.own_group_size))),
            ],
            [-INF] * d,
            [0.0] * d,
        )
        r = m.n
        m.add(
            [
                (r + by_yard, b0 + dc, np.ones(d * c)),
                (r + np.arange(d), d + np.arange(d), np.full(d, -float(ctx.ma_group_size))),
            ],
            [-INF] * d,
            [0.0] * d,
        )
        r = m.n
        m.add(
            [
                (r + by_cluster, a0 + dc, np.ones(d * c)),
                (r + by_cluster, b0 + dc, np.ones(d * c)),
                (r + np.arange(c), l0 + np.arange(c), np.ones(c)),
                (r + np.arange(c), o0 + np.arange(c), np.ones(c)),
            ],
            scen.need[k].tolist(),
            [INF] * c,
        )
        m.add([(np.full(c, m.n), l0 + np.arange(c), np.ones(c))], [-INF], [ctx.late_first_wave_persons])
        if cvar:
            r = m.n
            m.add(
                [
                    (np.full(per, r), base + np.arange(per), cost_rows[k] * SCALE),
                    (np.array([r, r]), np.array([eta, eta + 1 + k]), np.array([-1.0, -1.0])),
                ],
                [-INF],
                [0.0],
            )

    n_rows = m.n
    a = sp.csc_matrix(
        (np.concatenate(m.vals), (np.concatenate(m.rows), np.concatenate(m.cols))), shape=(n_rows, n_cols)
    )
    lp = highspy.HighsLp()
    lp.num_col_ = n_cols
    lp.num_row_ = n_rows
    lp.col_cost_ = cost
    lp.col_lower_ = lower
    lp.col_upper_ = upper
    lp.row_lower_ = np.asarray(m.lo, dtype=float)
    lp.row_upper_ = np.asarray(m.hi, dtype=float)
    lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lp.a_matrix_.start_ = a.indptr
    lp.a_matrix_.index_ = a.indices
    lp.a_matrix_.value_ = a.data
    lp.a_matrix_.num_col_ = n_cols
    lp.a_matrix_.num_row_ = n_rows
    if fixed is None:
        lp.integrality_ = [highspy.HighsVarType.kInteger] * n_first + [highspy.HighsVarType.kContinuous] * (
            n_cols - n_first
        )

    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("mip_rel_gap", float(mip_rel_gap))
    h.setOptionValue("time_limit", float(time_limit_s))
    h.setOptionValue("threads", int(threads))
    h.setOptionValue("random_seed", 16027)
    h.passModel(lp)
    t0 = time.perf_counter()
    h.run()
    seconds = time.perf_counter() - t0
    status = h.modelStatusToString(h.getModelStatus())
    info = h.getInfo()
    col = np.asarray(h.getSolution().col_value)
    if col.size != n_cols:
        raise RuntimeError(f"HiGHS returned no solution ({status})")
    x = np.rint(col[:d]).astype(int)
    y = np.rint(col[d:n_first]).astype(int)
    second = col[n_first : n_first + s * per].reshape(s, per)
    scen_ch = (second * cost_rows).sum(axis=1)
    b_used = second[:, d * c : 2 * d * c].sum(axis=1)
    idle = y.sum() * ctx.ma_group_size - b_used
    is_mip = fixed is None
    gap = float(info.mip_gap) if is_mip else 0.0
    if not np.isfinite(gap) or gap < 0:
        gap = 0.0
    tie = policy.early_group_cost_ch if is_mip else 0.0
    obj = float(info.objective_function_value) / SCALE - tie * float(y.sum())
    dual = float(info.mip_dual_bound) / SCALE - tie * float(policy.spend_cap_groups) if is_mip else obj
    out = Solve(
        x=x,
        y=y,
        objective_ch=obj,
        scenario_ch=scen_ch,
        idle_ma_persons=np.maximum(idle, 0.0),
        late_persons=second[:, 2 * d * c : 2 * d * c + c].sum(axis=1),
        overflow_persons=second[:, 2 * d * c + c :].sum(axis=1),
        mip_gap=gap,
        dual_bound_ch=dual,
        seconds=seconds,
        status=status,
        n_cols=n_cols,
        n_rows=n_rows,
    )
    if cvar:
        out.cvar_ch = cvar_of(scen_ch, policy.cvar_alpha)
    return out


def cvar_of(values: np.ndarray, alpha: float) -> float:
    """Sample CVaR_alpha: mean of the worst (1 - alpha) share, with the fractional atom at VaR."""
    v = np.sort(np.asarray(values, dtype=float))[::-1]
    n = len(v)
    tail = (1.0 - alpha) * n
    whole = int(np.floor(tail))
    total = v[:whole].sum() + (tail - whole) * (v[whole] if whole < n else 0.0)
    return float(total / tail)


@dataclass(frozen=True)
class Evaluation:
    ch: np.ndarray
    idle: np.ndarray
    late: np.ndarray
    overflow: np.ndarray


def evaluate(ctx: Context, scen: ScenarioSet, x: np.ndarray, y: np.ndarray, *, batch: int = 10) -> Evaluation:
    """Per-scenario outcome of a fixed first stage: the second-stage LP solved in batches."""
    parts: list[Solve] = []
    cap = int(y.sum())
    for start in range(0, scen.n, batch):
        idx = np.arange(start, min(scen.n, start + batch))
        parts.append(solve(ctx, scen.subset(idx, scen.label), Policy(spend_cap_groups=cap), fixed=(x, y)))
    return Evaluation(
        ch=np.concatenate([p.scenario_ch for p in parts]),
        idle=np.concatenate([p.idle_ma_persons for p in parts]),
        late=np.concatenate([p.late_persons for p in parts]),
        overflow=np.concatenate([p.overflow_persons for p in parts]),
    )
