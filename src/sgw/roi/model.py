"""Cash-flow model: benefits, costs, NPV, break-even multiples, sensitivity and storm-year spread.

Two views are kept apart everywhere: utility cash (what SGW funds from) and customer value (avoided outage
minutes at marginal interruption cost, which accrues to customers, not to SGW).
"""

from __future__ import annotations

import random
import statistics as st
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sgw.roi.inputs import (
    CUSTOMER_EFFECT_KEYS,
    EFFECT_KEYS,
    ONE_OFF_SCHEDULE,
    RAMP,
    RUN_COST_KEYS,
    RUN_SCHEDULE,
    SCENARIOS,
    STRICT_CASH,
    footprint,
    ice_weights,
    inputs,
)

Params = dict[str, float]
STORM_CASH_LINES = ("Storm restoration efficiency", "Storm cost recovery protected")
MAJOR_EVENT_LINE = "Major-event customer minutes avoided"
ROUTINE_LINE = "Routine customer minutes avoided"


def params(scenario: str, overrides: Mapping[str, float] | None = None) -> Params:
    p = {k: v.value(scenario) for k, v in inputs().items()}
    p.update(overrides or {})
    return p


def customers_m(p: Params) -> float:
    return p["residents_m"] * p["accounts_per_resident"]


def benefits(p: Params) -> tuple[dict[str, float], dict[str, float]]:
    c = customers_m(p)
    storm = c * p["storm_cost_per_cust"]
    main_miles = p["water_pop_m"] * 1000 * p["main_miles_per_1000"]
    vegetation_spend = c * 1e6 * p["oh_miles_per_cust"] / p["vm_cycle_yr"] * p["vm_cost_per_mile"] / 1e6
    cash = {
        "Storm restoration efficiency": storm * p["storm_om_share"] * p["storm_eff"],
        "Storm cost recovery protected": storm * p["disallow_rate"] * p["disallow_capture"],
        "Vegetation programme optimisation": vegetation_spend * p["vm_eff"],
        "Predictive T&D maintenance": c * p["maint_per_cust"] * p["maint_addressable"] * p["maint_eff"],
        "Water non-revenue reduction": p["water_pop_m"] * p["nrw_per_capita"] * p["nrw_reduction"],
        "Avoided main-break repairs": main_miles
        / 100
        * p["break_rate"]
        * p["cost_per_break"]
        / 1e6
        * p["break_reduction"],
        "Analyst and reporting time": p["fte_released"] * p["fte_value"],
        "Insurance premium effect": p["insurance_base"] * p["insurance_saving"],
    }
    customer = {
        MAJOR_EVENT_LINE: c * p["saidi_med"] * p["cmi_rr_med"] * p["w_major"],
        ROUTINE_LINE: c * p["saidi_blue"] * p["cmi_rr_blue"] * p["w_routine"],
    }
    return cash, customer


def llm_cost(p: Params) -> float:
    per_request = (p["llm_input_tok"] * p["llm_in_price"] + p["llm_output_tok"] * p["llm_out_price"]) / 1e6
    return p["llm_requests_m"] * per_request * p["llm_overhead"]


def costs(p: Params) -> tuple[dict[str, float], dict[str, float]]:
    one_time = {
        "Integrator and product build": p["build"],
        "Data integration and quality": p["data_integration"],
        "Security and compliance set-up": p["security_oneoff"],
        "Change management and exercises": p["change_mgmt"],
    }
    run = {
        "Platform team": p["team_fte"] * p["fte_cost"],
        "Cloud and data platform": p["cloud"],
        "Licences and data feeds": p["licences"],
        "AI model usage": llm_cost(p),
        "Assurance and audits": p["assurance"],
        "Vendor support": p["build"] * p["support_rate"],
    }
    return one_time, run


def npv(cash_flows: Sequence[float], rate: float) -> float:
    return sum(x / (1 + rate) ** (t + 1) for t, x in enumerate(cash_flows))


def irr(cash_flows: Sequence[float]) -> float | None:
    lo, hi = -0.95, 5.0
    if npv(cash_flows, lo) * npv(cash_flows, hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(cash_flows, lo) * npv(cash_flows, mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def payback(cash_flows: Sequence[float], rate: float = 0.0) -> float | None:
    total = 0.0
    for year, x in enumerate(cash_flows, 1):
        discounted = x / (1 + rate) ** year
        previous = total
        total += discounted
        if total >= 0 and year > 1 and previous < 0:
            return round(year - 1 + (-previous / discounted), 1)
    return None


@dataclass(frozen=True)
class Result:
    scenario: str
    cash_lines: dict[str, float]
    customer_lines: dict[str, float]
    one_time_lines: dict[str, float]
    run_lines: dict[str, float]
    one_time: float
    run_cost: float
    cash_benefit: float
    customer_value: float
    cash_flows: list[float]
    cash_flows_with_customer: list[float]
    spend: list[float]
    npv_cash: float
    npv_customer: float
    irr_cash: float | None
    irr_customer: float | None
    payback_cash: float | None
    payback_cash_discounted: float | None
    payback_customer: float | None
    pv_costs: float
    bcr_cash: float
    bcr_customer: float


def run(
    scenario: str,
    overrides: Mapping[str, float] | None = None,
    storm_path: Sequence[float] | None = None,
    detail: bool = True,
) -> Result:
    p = params(scenario, overrides)
    cash, customer = benefits(p)
    one_time_lines, run_lines = costs(p)
    cash_total, one_time, run_cost = sum(cash.values()), sum(one_time_lines.values()), sum(run_lines.values())
    storm_cash = sum(cash[k] for k in STORM_CASH_LINES)
    flows, flows_customer, spend = [], [], []
    for t, ramp in enumerate(RAMP[scenario]):
        m = storm_path[t] if storm_path else 1.0
        b = ramp * (cash_total - storm_cash + storm_cash * m)
        v = ramp * (customer[MAJOR_EVENT_LINE] * m + customer[ROUTINE_LINE])
        c = ONE_OFF_SCHEDULE[t] * one_time + RUN_SCHEDULE[t] * run_cost
        flows.append(b - c)
        flows_customer.append(b + v - c)
        spend.append(c)
    r = p["discount"]
    pv_costs = npv(spend, r)
    npv_cash, npv_customer = npv(flows, r), npv(flows_customer, r)
    return Result(
        scenario=scenario,
        cash_lines=cash,
        customer_lines=customer,
        one_time_lines=one_time_lines,
        run_lines=run_lines,
        one_time=one_time,
        run_cost=run_cost,
        cash_benefit=cash_total,
        customer_value=sum(customer.values()),
        cash_flows=flows,
        cash_flows_with_customer=flows_customer,
        spend=spend,
        npv_cash=npv_cash,
        npv_customer=npv_customer,
        irr_cash=irr(flows) if detail else None,
        irr_customer=irr(flows_customer) if detail else None,
        payback_cash=payback(flows) if detail else None,
        payback_cash_discounted=payback(flows, r) if detail else None,
        payback_customer=payback(flows_customer) if detail else None,
        pv_costs=pv_costs,
        bcr_cash=(npv_cash + pv_costs) / pv_costs,
        bcr_customer=(npv_customer + pv_costs) / pv_costs,
    )


def _quick(scenario: str, overrides: Mapping[str, float]) -> Result:
    return run(scenario, overrides, detail=False)


def metric(result: Result, name: str) -> float:
    return {"npv_cash": result.npv_cash, "npv_customer": result.npv_customer}[name]


def breakeven_multiple(
    scenario: str,
    keys: Sequence[str],
    metric_name: str,
    base_overrides: Mapping[str, float] | None = None,
) -> float | None:
    """Common multiple of the effect sizes in `keys` at which the metric crosses zero (bisection)."""
    fixed = dict(base_overrides or {})
    p = params(scenario, fixed)

    def at(m: float) -> float:
        return metric(_quick(scenario, {**fixed, **{k: p[k] * m for k in keys}}), metric_name)

    lo, hi = 0.0, 50.0
    if at(hi) <= 0:
        return None
    if at(0.0) > 0:
        return 0.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if at(mid) > 0:
            hi = mid
        else:
            lo = mid
    return hi


def solve_input(
    scenario: str, key: str, metric_name: str, overrides: Mapping[str, float] | None = None
) -> float:
    """Value of one input at which the metric is zero, other inputs fixed (bisection, monotone input)."""
    fixed = dict(overrides or {})
    lo, hi = 0.0, 1.0
    sign_lo = metric(_quick(scenario, {**fixed, key: lo}), metric_name) > 0
    for _ in range(80):
        mid = (lo + hi) / 2
        if (metric(_quick(scenario, {**fixed, key: mid}), metric_name) > 0) == sign_lo:
            lo = mid
        else:
            hi = mid
    return hi


@dataclass(frozen=True)
class Swing:
    key: str
    unit: str
    low: float
    base: float
    high: float
    at_low: float
    at_high: float
    label: str

    @property
    def width(self) -> float:
        return abs(self.at_high - self.at_low)


def tornado(metric_name: str) -> tuple[float, list[Swing]]:
    base = metric(run("base"), metric_name)
    out = []
    for k, v in inputs().items():
        if not v.varies:
            continue
        at_low = metric(run("base", {k: v.conservative}), metric_name)
        at_high = metric(run("base", {k: v.optimistic}), metric_name)
        out.append(Swing(k, v.unit, v.conservative, v.base, v.optimistic, at_low, at_high, v.label))
    return base, sorted(out, key=lambda s: -round(s.width, 1))


def structural_tests() -> list[tuple[str, Result]]:
    base = params("base")
    w = ice_weights(footprint().residential_share)
    cases: list[tuple[str, dict[str, float]]] = [
        ("Released staff time not counted as cash", {"fte_released": 0}),
        ("Vegetation line removed", {"vm_eff": 0}),
        ("No insurance line", {"insurance_saving": 0}),
        ("Storm O&M share 0.61", {"storm_om_share": 0.61}),
        ("Overhead miles per customer 0.03", {"oh_miles_per_cust": 0.03}),
        ("Water served 4.0 M", {"water_pop_m": 4.0}),
        ("Run cost x0.75", {k: base[k] * 0.75 for k in RUN_COST_KEYS}),
        ("Discount 5.5% real", {"discount": 0.055}),
        ("Average interruption cost (do not quote)", {"w_major": w["avg8"], "w_routine": w["avg2"]}),
        ("Major-event minutes at the median", {"saidi_med": inputs()["saidi_med"].conservative}),
        ("Strict cash (no staff time, vegetation, insurance)", dict(STRICT_CASH)),
    ]
    return [(name, run("base", o)) for name, o in cases]


def storm_year_spread(
    scenario: str = "base", n: int = 20000, p_severe: float = 0.30, low: float = 0.35, seed: int = 42
) -> dict[str, object]:
    """Spread of NPV across storm-year sequences. Describes spread only, never a probability of success."""
    rnd = random.Random(seed)  # noqa: S311
    high = (1 - (1 - p_severe) * low) / p_severe
    cash, customer = [], []
    for _ in range(n):
        path = [high if rnd.random() < p_severe else low for _ in range(len(RAMP[scenario]))]
        r = run(scenario, storm_path=path, detail=False)
        cash.append(r.npv_cash)
        customer.append(r.npv_customer)

    def q(x: list[float]) -> list[float]:
        d = st.quantiles(x, n=10)
        return [round(v, 1) for v in (d[0], st.median(x), d[8])]

    return {
        "p_severe": p_severe,
        "low_mult": low,
        "high_mult": round(high, 3),
        "n": n,
        "seed": seed,
        "cash_npv_p10_p50_p90": q(cash),
        "customer_npv_p10_p50_p90": q(customer),
        "share_cash_npv_positive": round(sum(v > 0 for v in cash) / n, 3),
    }


def all_scenarios() -> dict[str, Result]:
    return {s: run(s) for s in SCENARIOS}


def breakevens() -> dict[str, dict[str, float | None]]:
    return {
        "cash": {s: breakeven_multiple(s, EFFECT_KEYS, "npv_cash") for s in SCENARIOS},
        "cash_strict": {s: breakeven_multiple(s, EFFECT_KEYS, "npv_cash", STRICT_CASH) for s in SCENARIOS},
        "customer_all_effects": {
            s: breakeven_multiple(s, CUSTOMER_EFFECT_KEYS, "npv_customer") for s in SCENARIOS
        },
        "customer_major_event_only": {
            s: breakeven_multiple(s, ("cmi_rr_med",), "npv_customer") for s in SCENARIOS
        },
    }
