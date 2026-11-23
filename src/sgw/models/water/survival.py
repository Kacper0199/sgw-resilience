"""A4 station continuity Monte Carlo: generator survival, fuel ODE, refuelling and tank drain to the floor.

Per sample and minute (explicit, vectorised over samples):
- power: grid until `loss`, back at `restore`; in between a generator runs if it exists, has started (onsite:
  after the ATS delay; portable: at the hookup time), has not failed to start (Bernoulli by maintenance
  class), has not reached its run-failure time (exponential by class) and has fuel;
- fuel: dF/dt = -burn while running, burn = c * kW * (0.25 + 0.75 LF) gal/h; at the refuel trigger a delivery
  is requested and arrives after the truck lead plus a road delay (own fleet) or, when the route is blocked, a
  contract delivery delay; the delivery tops the tank up;
- tank: dV/dt = Q_pump - Q(t), Q_pump = capacity when powered else 0, V clipped to [0, V_full]; demand above
  pump capacity drains the tank even on power;
- service: the critical-node pressure of the zone twin against the state floor; first breach time and cause.
Uncertain inputs: maintenance class, fail-to-start, run failure, delivery delays, demand (leak multiplier and
demand scale). Seeded per station, so a run is exactly repeatable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from sgw.generator.config import Family, rng
from sgw.models.water.params import TwinParams
from sgw.models.water.twin import ZoneTwin

CAUSES = ("no_backup", "awaiting_hookup", "fail_to_start", "run_failure", "out_of_fuel", "demand")
GenKind = Literal["onsite", "portable", "none"]


@dataclass(frozen=True)
class StationCase:
    station: str
    loss_epoch: float
    restore_epoch: float | None
    generator: GenKind
    gen_kw: float = 0.0
    tank_gal: float = 0.0
    fuel0_gal: float | None = None
    hookup_epoch: float | None = None
    gen_class: str | None = None
    level0_ft: float | None = None


@dataclass
class SurvivalResult:
    station: str
    floor_psi: float
    samples: int
    horizon_h: float
    breach_t: np.ndarray
    cause: np.ndarray
    minutes_below: np.ndarray
    deliveries: np.ndarray
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def p_breach(self) -> float:
        return float(np.mean(~np.isnan(self.breach_t)))

    def breach_quantiles_min(self, loss_epoch: float) -> list[float] | None:
        hit = self.breach_t[~np.isnan(self.breach_t)]
        if len(hit) == 0:
            return None
        return [float(np.percentile((hit - loss_epoch) / 60.0, q)) for q in (10, 50, 90)]

    def summary(self, loss_epoch: float) -> dict[str, Any]:
        q = self.breach_quantiles_min(loss_epoch)
        causes = {c: float(np.mean(self.cause == c)) for c in CAUSES if np.any(self.cause == c)}
        return {
            "station": self.station,
            "floor_psi": self.floor_psi,
            "samples": self.samples,
            "horizon_h": self.horizon_h,
            "p_breach": round(self.p_breach, 4),
            "p_breach_se": round(float(np.sqrt(self.p_breach * (1 - self.p_breach) / self.samples)), 4),
            "breach_after_loss_min_p10_p50_p90": None if q is None else [round(x, 1) for x in q],
            "cause_share": {k: round(v, 4) for k, v in causes.items()},
            "mean_minutes_below_floor": round(float(self.minutes_below.mean()), 1),
            "mean_deliveries": round(float(self.deliveries.mean()), 3),
            **self.extra,
        }


def demand_multipliers(
    tp: TwinParams, r: np.random.Generator, n: int, stratified: bool = False
) -> np.ndarray:
    """Storm leak multiplier (triangular) times demand scale (lognormal); Latin-hypercube strata when
    asked."""
    lo, mode, hi = tp["demand.leak_multiplier_triangular"]
    sigma = tp.f("demand.base_scale_lognormal_sigma")
    if stratified:
        u1 = (r.permutation(n) + r.uniform(size=n)) / n
        u2 = (r.permutation(n) + r.uniform(size=n)) / n
    else:
        u1, u2 = r.uniform(size=n), r.uniform(size=n)
    fc = (mode - lo) / (hi - lo)
    leak = np.where(
        u1 < fc,
        lo + np.sqrt(u1 * (hi - lo) * (mode - lo)),
        hi - np.sqrt((1 - u1) * (hi - lo) * (hi - mode)),
    )
    from scipy.stats import norm

    scale = np.exp(sigma * norm.ppf(np.clip(u2, 1e-12, 1 - 1e-12)))
    return np.asarray(leak * scale)


def burn_gph(kw: float, fam: Family) -> float:
    return fam.f("generator.burn_coeff") * kw * (0.25 + 0.75 * fam.f("generator.load_fraction"))


def onsite_tank_gal(kw: float, fam: Family, days: float = 5.0) -> float:
    """Tank sized for `days` at 70 percent load (project fact base, Generators)."""
    return fam.f("generator.burn_coeff") * kw * fam.f("generator.load_fraction") * 24.0 * days


def simulate(
    twin: ZoneTwin,
    case: StationCase,
    floor_psi: float,
    fam: Family,
    tp: TwinParams,
    *,
    samples: int | None = None,
    horizon_h: float | None = None,
    seed: int | None = None,
    max_deliveries: int = 12,
) -> SurvivalResult:
    n = int(samples if samples is not None else tp["mc.samples"])
    horizon = float(horizon_h if horizon_h is not None else tp["rule.horizon_h"])
    r = rng(int(seed if seed is not None else tp["mc.seed"]), "water_survival", case.station)
    shares = tp["generator.class_share"]
    names = list(shares)
    if case.gen_class is not None:
        klass = np.full(n, case.gen_class)
    else:
        klass = np.asarray(names)[r.choice(len(names), size=n, p=[shares[k] for k in names])]
    p_fts = np.array([tp["generator.fail_to_start"][k] for k in klass])
    mttf_h = np.array([tp["generator.run_mttf_h"][k] for k in klass])
    fts = r.uniform(size=n) < p_fts
    run_fail_min = r.exponential(mttf_h) * 60.0
    mult = demand_multipliers(tp, r, n)
    own = tp["fuel.own_truck_extra_delay_lognormal"]
    contract = tp["fuel.contract_delay_lognormal"]
    blocked = r.uniform(size=(n, max_deliveries)) < tp.f("fuel.route_blocked_p")
    delay_h = np.where(
        blocked,
        r.lognormal(np.log(contract["median_h"]), contract["sigma"], size=(n, max_deliveries)),
        r.lognormal(np.log(own["median_h"]), own["sigma"], size=(n, max_deliveries)),
    )
    delay_s = fam.f("fuel.truck_lead_min") * 60.0 + delay_h * 3600.0

    has_gen = case.generator != "none"
    tank = case.tank_gal
    burn_min = burn_gph(case.gen_kw, fam) / 60.0 if has_gen else 0.0
    trigger = fam.f("fuel.refuel_trigger_frac") * tank
    fuel = np.full(n, case.fuel0_gal if case.fuel0_gal is not None else tank, dtype=float)
    start_t = (
        case.loss_epoch + fam.f("generator.ats_delay_s")
        if case.generator == "onsite"
        else (case.hookup_epoch if case.hookup_epoch is not None else np.inf)
    )
    pump_gpm = twin.pump_gpm
    gal_per_ft = twin.pm.gal_per_ft
    level = np.full(n, twin.pm.max_level_ft if case.level0_ft is None else case.level0_ft, dtype=float)
    run_min = np.zeros(n)
    pending = np.full(n, np.nan)
    calls = np.zeros(n, dtype=int)
    delivered = np.zeros(n, dtype=int)
    breach = np.full(n, np.nan)
    cause = np.full(n, "", dtype=object)
    below = np.zeros(n)
    idx = np.arange(n)
    steps = int(horizon * 60)
    for k in range(steps):
        t = case.loss_epoch + k * 60.0
        grid = case.restore_epoch is not None and t >= case.restore_epoch
        if has_gen and not grid:
            arrived = ~np.isnan(pending) & (t >= pending)
            fuel[arrived] = tank
            pending[arrived] = np.nan
            delivered += arrived
            started = np.full(n, t >= start_t)
            running = started & ~fts & (run_min < run_fail_min) & (fuel > 0.0)
            fuel = np.where(running, np.maximum(fuel - burn_min, 0.0), fuel)
            run_min += running
            ask = running & np.isnan(pending) & (fuel <= trigger) & (calls < max_deliveries)
            if ask.any():
                pending[ask] = t + delay_s[idx[ask], calls[ask]]
                calls += ask
        else:
            running = np.zeros(n, dtype=bool)
            started = np.zeros(n, dtype=bool)
        powered = running | grid
        q = twin.demand_gpm(np.array(t), mult)
        inflow = np.where(powered, pump_gpm, 0.0)
        level = np.clip(level + (inflow - q) / gal_per_ft, 0.0, twin.pm.max_level_ft)
        p = twin.pm.critical_psi(level, q)
        low = p < floor_psi
        below += low
        new = low & np.isnan(breach)
        if new.any():
            breach[new] = t
            if grid:
                why = np.full(n, "demand", dtype=object)
            elif not has_gen:
                why = np.full(n, "no_backup", dtype=object)
            else:
                why = np.select(
                    [~started, fts, run_min >= run_fail_min, fuel <= 0.0],
                    ["awaiting_hookup", "fail_to_start", "run_failure", "out_of_fuel"],
                    default="demand",
                ).astype(object)
            cause[new] = why[new]
    return SurvivalResult(
        station=case.station,
        floor_psi=floor_psi,
        samples=n,
        horizon_h=horizon,
        breach_t=breach,
        cause=cause,
        minutes_below=below,
        deliveries=delivered,
    )
