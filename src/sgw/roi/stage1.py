"""Stage 1 price and the two gate criteria, derived from the ROI model.

Stage 1 is phase 0 (discovery, baselines, backtest on past storms) plus phase 1 (read-only pilot in one
South Carolina area, tabletop and functional exercises), as on the shared roadmap: gate G0 at month 2,
gate G1 at month 8. Its price is the model's programme spend in those months: year-one spend (half the
one-time cost plus half a year of run cost) spread evenly over twelve months. The range is the optimistic
and conservative cost scenarios.

The gate criteria are the two largest assumed drivers of the cash view that a first stage can measure:
- benefit: the storm restoration cost reduction at which the cash view breaks even with every other input
  at base (solved from the model);
- price: the full-programme quote stays within the base cost (one-time and run), because the benefit bar
  above is computed at that cost and leaves no headroom.
"""

from __future__ import annotations

from dataclasses import dataclass

from sgw.roi.inputs import SCENARIOS, STRICT_CASH, inputs
from sgw.roi.model import Result, all_scenarios, run, solve_input

PHASE_MONTHS = {"phase_0": 2, "phase_1": 6}
STAGE1_MONTHS = sum(PHASE_MONTHS.values())


@dataclass(frozen=True)
class StagePrice:
    scenario: str
    year_one_spend: float
    phase_0: float
    phase_1: float

    @property
    def stage1(self) -> float:
        return self.phase_0 + self.phase_1


def stage_price(result: Result) -> StagePrice:
    per_month = result.spend[0] / 12
    return StagePrice(
        scenario=result.scenario,
        year_one_spend=result.spend[0],
        phase_0=per_month * PHASE_MONTHS["phase_0"],
        phase_1=per_month * PHASE_MONTHS["phase_1"],
    )


def derive(results: dict[str, Result] | None = None) -> dict[str, object]:
    results = results or all_scenarios()
    prices = {s: stage_price(results[s]) for s in SCENARIOS}
    base_storm_eff = inputs()["storm_eff"].base
    gate_storm_eff = solve_input("base", "storm_eff", "npv_cash")
    gate_storm_eff_strict = solve_input("base", "storm_eff", "npv_cash", STRICT_CASH)
    low_storm_cost = inputs()["storm_cost_per_cust"].conservative
    gate_storm_eff_low_cost = solve_input(
        "base", "storm_eff", "npv_cash", {"storm_cost_per_cust": low_storm_cost}
    )
    at_gate = run("base", {"storm_eff": gate_storm_eff})
    base = results["base"]
    return {
        "method": (
            "Stage 1 = phase 0 + phase 1 = the first "
            f"{STAGE1_MONTHS} months of programme spend in the cost model; year-one spend spread evenly "
            "over twelve months. Range = optimistic and conservative cost scenarios."
        ),
        "phase_months": PHASE_MONTHS,
        "price_musd": {
            s: {
                "year_one_spend": prices[s].year_one_spend,
                "phase_0": prices[s].phase_0,
                "phase_1": prices[s].phase_1,
                "stage1": prices[s].stage1,
            }
            for s in SCENARIOS
        },
        "downside_full_commitment_conservative_npv_cash": results["conservative"].npv_cash,
        "gate_benefit": {
            "what": "storm restoration cost reduction shown in the backtest, as a share of storm O&M",
            "base_assumption": base_storm_eff,
            "breakeven_share": gate_storm_eff,
            "breakeven_multiple_of_base": gate_storm_eff / base_storm_eff,
            "breakeven_share_strict_cash": gate_storm_eff_strict,
            "breakeven_share_at_low_storm_cost": gate_storm_eff_low_cost,
            "low_storm_cost_usd_per_customer": low_storm_cost,
            "cash_npv_at_gate": at_gate.npv_cash,
            "storm_line_at_gate_musd_per_year": at_gate.cash_lines["Storm restoration efficiency"],
        },
        "gate_price": {
            "what": "quoted full-programme cost within the base case",
            "one_time_max_musd": base.one_time,
            "run_max_musd_per_year": base.run_cost,
        },
    }
