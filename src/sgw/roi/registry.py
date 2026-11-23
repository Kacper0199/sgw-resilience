"""Which numbers.yaml key carries which value of `data/roi/roi_results.json`, and at what precision.

The test in `tests/unit/roi/` asserts every pair is equal, so a model change that is not carried into the
numbers file (and from there into the documents) fails the build.
"""

from __future__ import annotations

from typing import Any

# numbers.yaml key -> (path in roi_results.json, decimals; scale applied before rounding)
REGISTRY: dict[str, tuple[str, int, float]] = {
    "roi_utility_npv_musd": ("headline.cash_npv_base", 1, 1),
    "roi_utility_bcr": ("headline.cash_bcr_base", 2, 1),
    "roi_customer_npv_musd": ("headline.customer_npv_base", 1, 1),
    "roi_customer_bcr": ("headline.customer_bcr_base", 2, 1),
    "roi_customer_payback_years": ("headline.customer_payback_years_base", 1, 1),
    "roi_breakeven_effect_multiple": ("headline.breakeven_effect_multiple_base", 2, 1),
    "platform_cost_one_time_musd": ("headline.one_time_cost_base", 1, 1),
    "platform_run_cost_musd_per_year": ("headline.run_cost_base", 1, 1),
    "roi_cash_npv_conservative_musd": ("headline.cash_npv_conservative", 1, 1),
    "roi_cash_npv_optimistic_musd": ("headline.cash_npv_optimistic", 1, 1),
    "roi_cash_npv_structural_low_musd": ("headline.cash_npv_structural_low", 1, 1),
    "roi_cash_npv_structural_high_musd": ("headline.cash_npv_structural_high", 1, 1),
    "roi_customer_npv_conservative_musd": ("headline.customer_npv_conservative", 1, 1),
    "roi_customer_npv_range_low_musd": ("headline.customer_npv_one_at_a_time_low", 0, 1),
    "roi_customer_npv_range_high_musd": ("headline.customer_npv_one_at_a_time_high", 0, 1),
    "roi_breakeven_strict_multiple": ("headline.breakeven_effect_multiple_strict", 2, 1),
    "roi_cash_benefit_steady_musd": ("headline.cash_benefit_steady_base", 1, 1),
    "roi_customer_value_steady_musd": ("headline.customer_value_steady_base", 1, 1),
    "roi_cash_npv_storm_spread_low_musd": ("storm_year_spread.base.cash_npv_p10_p50_p90.0", 1, 1),
    "roi_cash_npv_storm_spread_high_musd": ("storm_year_spread.base.cash_npv_p10_p50_p90.2", 1, 1),
    "platform_cost_one_time_conservative_musd": ("headline.one_time_cost_conservative", 1, 1),
    "platform_cost_one_time_optimistic_musd": ("headline.one_time_cost_optimistic", 1, 1),
    "platform_run_cost_conservative_musd": ("headline.run_cost_conservative", 1, 1),
    "platform_run_cost_optimistic_musd": ("headline.run_cost_optimistic", 1, 1),
    "cost_build_musd": ("scenarios.base.one_time_lines.Integrator and product build", 1, 1),
    "cost_data_integration_musd": ("scenarios.base.one_time_lines.Data integration and quality", 1, 1),
    "cost_security_setup_musd": ("scenarios.base.one_time_lines.Security and compliance set-up", 1, 1),
    "cost_change_management_musd": ("scenarios.base.one_time_lines.Change management and exercises", 1, 1),
    "cost_run_team_musd": ("scenarios.base.run_lines.Platform team", 1, 1),
    "cost_run_cloud_musd": ("scenarios.base.run_lines.Cloud and data platform", 1, 1),
    "cost_run_licences_musd": ("scenarios.base.run_lines.Licences and data feeds", 1, 1),
    "cost_run_ai_usage_musd": ("scenarios.base.run_lines.AI model usage", 1, 1),
    "cost_run_assurance_musd": ("scenarios.base.run_lines.Assurance and audits", 1, 1),
    "cost_run_vendor_support_musd": ("scenarios.base.run_lines.Vendor support", 1, 1),
    "cost_run_team_fte": ("inputs.team_fte.base", 0, 1),
    "benefit_storm_restoration_musd": ("scenarios.base.cash_lines.Storm restoration efficiency", 1, 1),
    "benefit_vegetation_musd": ("scenarios.base.cash_lines.Vegetation programme optimisation", 1, 1),
    "benefit_staff_time_musd": ("scenarios.base.cash_lines.Analyst and reporting time", 1, 1),
    "benefit_maintenance_musd": ("scenarios.base.cash_lines.Predictive T&D maintenance", 1, 1),
    "stage_one_price_musd": ("headline.stage1_price_base", 1, 1),
    "stage_one_price_low_musd": ("headline.stage1_price_low", 1, 1),
    "stage_one_price_high_musd": ("headline.stage1_price_high", 1, 1),
    "stage_one_phase_zero_price_musd": ("headline.phase0_price_base", 1, 1),
    "stage_one_phase_one_price_musd": ("headline.phase1_price_base", 1, 1),
    "stage_one_months": ("stage1.phase_months", 0, 1),
    "gate_storm_cost_reduction_pct": ("headline.gate_storm_reduction_pct", 1, 1),
    "gate_storm_cost_reduction_assumed_pct": ("headline.gate_storm_reduction_base_assumption_pct", 1, 1),
    "gate_storm_cost_reduction_strict_pct": ("headline.gate_storm_reduction_strict_pct", 1, 1),
    "gate_storm_cost_reduction_low_cost_pct": ("headline.gate_storm_reduction_low_storm_cost_pct", 1, 1),
    "roi_struct_staff_time_cash_musd": ("structural_tests.0.npv_cash", 1, 1),
    "roi_struct_staff_time_customer_musd": ("structural_tests.0.npv_customer", 1, 1),
    "roi_struct_vegetation_cash_musd": ("structural_tests.1.npv_cash", 1, 1),
    "roi_struct_vegetation_customer_musd": ("structural_tests.1.npv_customer", 1, 1),
    "roi_struct_om_share_cash_musd": ("structural_tests.3.npv_cash", 1, 1),
    "roi_struct_om_share_customer_musd": ("structural_tests.3.npv_customer", 1, 1),
    "roi_struct_run_cost_cash_musd": ("structural_tests.6.npv_cash", 1, 1),
    "roi_struct_run_cost_customer_musd": ("structural_tests.6.npv_customer", 1, 1),
    "roi_struct_discount_cash_musd": ("structural_tests.7.npv_cash", 1, 1),
    "roi_struct_discount_customer_musd": ("structural_tests.7.npv_customer", 1, 1),
    "roi_struct_median_minutes_customer_musd": ("structural_tests.9.npv_customer", 1, 1),
    "roi_struct_strict_customer_musd": ("structural_tests.10.npv_customer", 1, 1),
    "roi_struct_oh_miles_customer_musd": ("structural_tests.4.npv_customer", 1, 1),
    "input_storm_saving_low_pct": ("inputs.storm_eff.conservative", 1, 100),
    "input_storm_saving_high_pct": ("inputs.storm_eff.optimistic", 1, 100),
    "input_major_minutes_avoided_pct": ("inputs.cmi_rr_med.base", 1, 100),
    "input_major_minutes_avoided_low_pct": ("inputs.cmi_rr_med.conservative", 1, 100),
    "input_major_minutes_avoided_high_pct": ("inputs.cmi_rr_med.optimistic", 1, 100),
    "input_routine_minutes_avoided_pct": ("inputs.cmi_rr_blue.base", 1, 100),
    "input_routine_minutes_avoided_low_pct": ("inputs.cmi_rr_blue.conservative", 1, 100),
    "input_routine_minutes_avoided_high_pct": ("inputs.cmi_rr_blue.optimistic", 1, 100),
    "input_staff_released_fte": ("inputs.fte_released.base", 0, 1),
    "input_vegetation_saving_pct": ("inputs.vm_eff.base", 1, 100),
    "input_insurance_premium_musd": ("inputs.insurance_base.base", 0, 1),
    "input_insurance_saving_pct": ("inputs.insurance_saving.base", 1, 100),
}


def lookup(data: Any, path: str) -> Any:
    node = data
    for part in path.split("."):
        node = node[int(part)] if isinstance(node, list) else node[part]
    if isinstance(node, dict):
        return sum(node.values())
    return node
