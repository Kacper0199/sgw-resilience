"""Run the ROI model and write `data/roi/roi_results.json`.

uv run python -m sgw.roi            # write the results file
uv run python -m sgw.roi --check    # exit 1 if the committed file differs from a fresh run
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from sgw.roi.inputs import HORIZON_YEARS, REPO_ROOT, SCENARIOS, footprint, ice_weights, inputs
from sgw.roi.model import all_scenarios, breakevens, storm_year_spread, structural_tests, tornado
from sgw.roi.stage1 import derive

RESULTS_PATH = REPO_ROOT / "data" / "roi" / "roi_results.json"
TOP_SWINGS = 12


def _r(x: object, nd: int = 4) -> object:
    if isinstance(x, float):
        return round(x, nd)
    if isinstance(x, dict):
        return {k: _r(v, nd) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_r(v, nd) for v in x]
    return x


def headline(results: dict, be: dict, struct: list, stage: dict) -> dict[str, float]:
    base, cons, opt = results["base"], results["conservative"], results["optimistic"]
    cash_struct = [r.npv_cash for name, r in struct if not name.startswith("Average")]
    customer_tornado = [s for s in tornado("npv_customer")[1]]
    price = stage["price_musd"]
    gate = stage["gate_benefit"]
    return {
        "cash_npv_base": round(base.npv_cash, 1),
        "cash_npv_conservative": round(cons.npv_cash, 1),
        "cash_npv_optimistic": round(opt.npv_cash, 1),
        "cash_npv_structural_low": round(min(cash_struct), 1),
        "cash_npv_structural_high": round(max(cash_struct), 1),
        "cash_bcr_base": round(base.bcr_cash, 2),
        "customer_npv_base": round(base.npv_customer, 1),
        "customer_npv_conservative": round(cons.npv_customer, 1),
        "customer_npv_one_at_a_time_low": round(min(min(s.at_low, s.at_high) for s in customer_tornado), 1),
        "customer_npv_one_at_a_time_high": round(max(max(s.at_low, s.at_high) for s in customer_tornado), 1),
        "customer_bcr_base": round(base.bcr_customer, 2),
        "customer_payback_years_base": base.payback_customer,
        "breakeven_effect_multiple_base": round(be["cash"]["base"], 2),
        "breakeven_effect_multiple_strict": round(be["cash_strict"]["base"], 2),
        "one_time_cost_base": round(base.one_time, 1),
        "one_time_cost_conservative": round(cons.one_time, 1),
        "one_time_cost_optimistic": round(opt.one_time, 1),
        "run_cost_base": round(base.run_cost, 1),
        "run_cost_conservative": round(cons.run_cost, 1),
        "run_cost_optimistic": round(opt.run_cost, 1),
        "cash_benefit_steady_base": round(base.cash_benefit, 1),
        "customer_value_steady_base": round(base.customer_value, 1),
        "stage1_price_base": round(price["base"]["stage1"], 1),
        "stage1_price_low": round(price["optimistic"]["stage1"], 1),
        "stage1_price_high": round(price["conservative"]["stage1"], 1),
        "phase0_price_base": round(price["base"]["phase_0"], 1),
        "phase1_price_base": round(price["base"]["phase_1"], 1),
        "gate_storm_reduction_pct": round(100 * gate["breakeven_share"], 1),
        "gate_storm_reduction_base_assumption_pct": round(100 * gate["base_assumption"], 1),
        "gate_storm_reduction_strict_pct": round(100 * gate["breakeven_share_strict_cash"], 1),
        "gate_storm_reduction_low_storm_cost_pct": round(100 * gate["breakeven_share_at_low_storm_cost"], 1),
    }


def build() -> dict[str, object]:
    results = all_scenarios()
    be = breakevens()
    struct = structural_tests()
    stage = derive(results)
    fp = footprint()
    torn = {}
    for m in ("npv_cash", "npv_customer"):
        base_value, swings = tornado(m)
        torn[m] = {
            "base": base_value,
            "swings": [{**asdict(s), "width": s.width} for s in swings[:TOP_SWINGS]],
        }
    scenarios = {}
    for s in SCENARIOS:
        r = asdict(results[s])
        r.pop("scenario")
        scenarios[s] = r
    data = _r(
        {
            "about": (
                "SGW platform ROI, South Carolina plus Georgia east of 83.6 W. Reproduces the R04 model "
                "(roi-sc-ga) in code. Million USD 2026, flat real. Cash and customer value are separate "
                "views. Every effect size and platform cost is an assumption."
            ),
            "generator": "uv run python -m sgw.roi",
            "horizon_years": HORIZON_YEARS,
            "discount_rate": inputs()["discount"].base,
            "headline": headline(results, be, struct, stage),
            "scenarios": scenarios,
            "breakeven": be,
            "structural_tests": [
                {
                    "change": name,
                    "cash_benefit": r.cash_benefit,
                    "npv_cash": r.npv_cash,
                    "bcr_cash": r.bcr_cash,
                    "npv_customer": r.npv_customer,
                    "bcr_customer": r.bcr_customer,
                }
                for name, r in struct
            ],
            "tornado": torn,
            "storm_year_spread": {s: storm_year_spread(s) for s in SCENARIOS},
            "stage1": stage,
            "ice_weights": ice_weights(fp.residential_share),
            "footprint_major_event_minutes": dict(
                zip([str(y) for y in fp.years], fp.major_event_minutes, strict=True)
            ),
            "inputs": {k: asdict(v) for k, v in inputs().items()},
        }
    )
    assert isinstance(data, dict)
    return data


def render(data: dict[str, object]) -> str:
    return json.dumps(data, indent=1, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the SGW ROI model")
    parser.add_argument("--check", action="store_true", help="compare with the committed results file")
    parser.add_argument("--out", type=Path, default=RESULTS_PATH)
    args = parser.parse_args(argv)
    text = render(build())
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != text:
            print(f"{args.out} is out of date: run uv run python -m sgw.roi", file=sys.stderr)
            return 1
        print(f"{args.out} matches a fresh run")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(json.dumps(json.loads(text)["headline"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
