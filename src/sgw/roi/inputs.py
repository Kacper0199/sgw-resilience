"""Inputs of the SGW platform ROI model for the footprint (South Carolina plus Georgia east of 83.6 W).

Reproduces the R04 model `sgw_roi_model_scga.py` input table. Every input has a conservative, base and
optimistic value and a label: S sourced, D derived from sourced values, A assumption. Money in million USD
of 2026, flat real.
"""

from __future__ import annotations

import json
import statistics as st
from dataclasses import dataclass
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FOOTPRINT_PATH = REPO_ROOT / "data" / "roi" / "footprint_inputs.json"
SCENARIOS = ("conservative", "base", "optimistic")

ICE_RESIDENTIAL = {0: 1.83, 2: 10.91, 8: 26.62, 24: 56.66}
ICE_NON_RESIDENTIAL = {0: 548, 2: 3571, 8: 7708, 24: 13878}


@dataclass(frozen=True)
class Input:
    conservative: float
    base: float
    optimistic: float
    unit: str
    label: str
    basis: str

    def value(self, scenario: str) -> float:
        return (self.conservative, self.base, self.optimistic)[SCENARIOS.index(scenario)]

    @property
    def varies(self) -> bool:
        return self.conservative != self.optimistic


@dataclass(frozen=True)
class Footprint:
    customers_m: float
    customers: int
    residents: int
    weight_sc: float
    residential_share: float
    georgia_power_customers_m: float
    years: tuple[int, ...]
    major_event_minutes: tuple[float, ...]
    routine_minutes: tuple[float, ...]

    @property
    def major_median(self) -> float:
        return st.median(self.major_event_minutes)

    @property
    def major_mean(self) -> float:
        return st.mean(self.major_event_minutes)

    @property
    def major_mean_without_worst(self) -> float:
        return st.mean(sorted(self.major_event_minutes)[:-1])

    @property
    def routine_mean(self) -> float:
        return st.mean(self.routine_minutes)


@cache
def footprint(path: Path = FOOTPRINT_PATH) -> Footprint:
    raw = json.loads(path.read_text(encoding="utf-8"))
    w = raw["weight_sc"]
    major = tuple(
        w * (sm - sn) + (1 - w) * (gm - gn)
        for sm, sn, gm, gn in zip(
            raw["saidi_with_med_sc"],
            raw["saidi_without_med_sc"],
            raw["saidi_with_med_ga"],
            raw["saidi_without_med_ga"],
            strict=True,
        )
    )
    routine = tuple(
        w * sn + (1 - w) * gn
        for sn, gn in zip(raw["saidi_without_med_sc"], raw["saidi_without_med_ga"], strict=True)
    )
    return Footprint(
        customers_m=raw["customers_footprint"] / 1e6,
        customers=raw["customers_footprint"],
        residents=raw["residents_footprint"],
        weight_sc=w,
        residential_share=raw["residential_share"],
        georgia_power_customers_m=raw["georgia_power_customers_m"],
        years=tuple(raw["saidi_years"]),
        major_event_minutes=major,
        routine_minutes=routine,
    )


def ice_weights(res: float) -> dict[str, float]:
    """Customer interruption cost per customer-minute (USD), ICE 2.0 Phase 2 national table."""

    def average(h: int) -> float:
        return res * ICE_RESIDENTIAL[h] / (60 * h) + (1 - res) * ICE_NON_RESIDENTIAL[h] / (60 * h)

    def marginal(a: int, b: int) -> float:
        r = ICE_RESIDENTIAL[b] - ICE_RESIDENTIAL[a]
        n = ICE_NON_RESIDENTIAL[b] - ICE_NON_RESIDENTIAL[a]
        return (res * r + (1 - res) * n) / (60 * (b - a))

    return {
        "avg8": average(8),
        "avg2": average(2),
        "m2_8": marginal(2, 8),
        "m8_24": marginal(8, 24),
        "m0_2": marginal(0, 2),
    }


def storm_cost_per_customer(fp: Footprint) -> tuple[float, float, float]:
    """Storm O&M per customer per year: Georgia Power accrual, a Helene-class event, under-recovery."""
    low = 101 / fp.georgia_power_customers_m
    base = low + 0.61 * 1150 / 2.9 / 10
    high = (912 + 3 * 63.5) / 3 / fp.georgia_power_customers_m
    return low, base, high


def _same(v: float, unit: str, label: str, basis: str) -> Input:
    return Input(v, v, v, unit, label, basis)


@cache
def inputs() -> dict[str, Input]:
    fp = footprint()
    w = ice_weights(fp.residential_share)
    s_low, s_base, s_high = storm_cost_per_customer(fp)
    accounts = round(fp.customers_m / (fp.residents / 1e6), 4)
    return {
        "residents_m": _same(8.14, "M residents", "S", "Census Vintage 2024, 46 SC and 77 GA counties"),
        "accounts_per_resident": _same(accounts, "accounts/resident", "S", "EAGLE-I modelled customers"),
        "water_pop_m": Input(1.5, 2.0, 2.5, "M residents on SGW water", "A", "No split given"),
        "storm_cost_per_cust": Input(
            round(s_low, 1),
            round(s_base, 1),
            round(s_high, 1),
            "USD/customer/yr, O&M",
            "D",
            "Georgia Power accrual; Duke Carolinas Helene cost; Georgia Power under-recovery",
        ),
        "storm_om_share": _same(1.0, "share", "D", "Storm base is already O&M"),
        "storm_eff": Input(0.01, 0.025, 0.04, "share of storm O&M", "A", "Pre-staging, crew allocation"),
        "disallow_rate": Input(0.005, 0.01, 0.015, "share of storm cost", "A", "Cost at risk in review"),
        "disallow_capture": Input(0.10, 0.25, 0.40, "share", "A", "Risk removed by an evidence trail"),
        "oh_miles_per_cust": _same(0.015, "OH miles/customer", "A", "Replace with SGW GIS"),
        "vm_cycle_yr": _same(4, "years", "A", "Typical trim cycle"),
        "vm_cost_per_mile": Input(11000, 12300, 13900, "USD/mile/cycle", "S", "Public filings, national"),
        "vm_eff": Input(0.01, 0.025, 0.04, "share of VM spend", "A", "Risk-based cycle optimisation"),
        "maint_per_cust": _same(103, "USD/customer/yr", "D", "EIA Table 8.3, national"),
        "maint_addressable": Input(0.20, 0.30, 0.40, "share", "A", "Condition-based share"),
        "maint_eff": Input(0.01, 0.02, 0.03, "share", "A", "Predictive maintenance effect"),
        "nrw_per_capita": _same(21.3, "USD/resident/yr", "D", "Bluefield, national"),
        "nrw_reduction": Input(0.02, 0.04, 0.06, "share of NRW value", "A", "Leak and pressure analytics"),
        "main_miles_per_1000": _same(7.33, "miles/1000 residents", "D", "Bluefield, national"),
        "break_rate": _same(11.1, "breaks/100 mi/yr", "S", "USU 2023 via ASCE, national"),
        "cost_per_break": _same(10000, "USD/break", "D", "USU, national"),
        "break_reduction": Input(0.02, 0.05, 0.08, "share", "A", "Risk-ranked renewal"),
        "fte_released": Input(10, 25, 40, "FTE-equivalent", "A", "Storm room, reporting, after-action"),
        "fte_value": _same(0.12, "MUSD/FTE", "A", "Loaded operations and analyst cost"),
        "insurance_base": Input(40, 60, 80, "MUSD/yr premium", "A", "SGW premium unknown"),
        "insurance_saving": Input(0.0, 0.005, 0.01, "share", "A", "Underwriter credit unproven"),
        "saidi_med": Input(
            round(fp.major_median, 1),
            round(fp.major_mean_without_worst, 1),
            round(fp.major_mean, 1),
            "major-event min/customer/yr",
            "D",
            "EIA Table 11.4 2015-2025, SC and GA weighted by customers",
        ),
        "saidi_blue": _same(round(fp.routine_mean, 1), "min/customer/yr", "D", "EIA Table 11.4 without MED"),
        "cmi_rr_med": Input(0.01, 0.03, 0.05, "share", "A", "Major-event customer minutes avoided"),
        "cmi_rr_blue": Input(0.005, 0.01, 0.02, "share", "A", "Routine customer minutes avoided"),
        "res_share": _same(round(fp.residential_share, 4), "share", "S", "EIA-861 2024"),
        "w_major": Input(
            round(w["m8_24"], 4),
            round(w["m8_24"], 4),
            round(w["m2_8"], 4),
            "USD/CMI",
            "D",
            "ICE 2.0 marginal",
        ),
        "w_routine": Input(
            round(w["m2_8"], 4), round(w["avg2"], 4), round(w["avg2"], 4), "USD/CMI", "D", "ICE 2.0"
        ),
        "build": Input(30, 20, 14, "MUSD one-time", "A", "Integrator and product build"),
        "data_integration": Input(12, 8, 5, "MUSD one-time", "A", "Connectors and data quality"),
        "security_oneoff": Input(6, 4, 2.5, "MUSD one-time", "A", "Segmentation, CIP boundary, pen tests"),
        "change_mgmt": Input(4, 3, 2, "MUSD one-time", "A", "Training, exercises, procedures"),
        "team_fte": Input(28, 20, 14, "FTE", "A", "Product, data, ML, SRE, security, governance"),
        "fte_cost": Input(0.20, 0.19, 0.18, "MUSD/FTE", "D", "BLS May 2024 medians, loaded"),
        "cloud": Input(5, 3, 2, "MUSD/yr", "A", "Compliant cloud, data platform, DR"),
        "licences": Input(3, 2, 1.5, "MUSD/yr", "A", "GIS, weather feeds, observability"),
        "llm_requests_m": Input(5, 2, 1, "M requests/yr", "A", "Assistant, summaries, retrieval"),
        "llm_input_tok": _same(30000, "tokens/request", "A", "Retrieved context"),
        "llm_output_tok": _same(1500, "tokens/request", "A", "Answer length"),
        "llm_in_price": _same(2, "USD/MTok", "S", "List price recorded in R01"),
        "llm_out_price": _same(10, "USD/MTok", "S", "List price recorded in R01"),
        "llm_overhead": _same(1.5, "multiplier", "A", "Retries, evaluation traffic"),
        "assurance": Input(1.0, 0.7, 0.4, "MUSD/yr", "A", "Model validation, audits, red team"),
        "support_rate": _same(0.15, "share of build/yr", "A", "Vendor and integrator support"),
        "discount": _same(0.08, "rate", "A", "Proxy for utility WACC on flat real flows"),
    }


RAMP = {
    "conservative": (0, 0, 0.2, 0.5, 0.8, 1, 1, 1, 1, 1),
    "base": (0, 0.2, 0.5, 0.8, 1, 1, 1, 1, 1, 1),
    "optimistic": (0, 0.3, 0.7, 1, 1, 1, 1, 1, 1, 1),
}
ONE_OFF_SCHEDULE = (0.5, 0.35, 0.15, 0, 0, 0, 0, 0, 0, 0)
RUN_SCHEDULE = (0.5, 1, 1, 1, 1, 1, 1, 1, 1, 1)
HORIZON_YEARS = len(RUN_SCHEDULE)
EFFECT_KEYS = (
    "storm_eff",
    "disallow_capture",
    "vm_eff",
    "maint_eff",
    "nrw_reduction",
    "break_reduction",
    "fte_released",
    "insurance_saving",
)
CUSTOMER_EFFECT_KEYS = (*EFFECT_KEYS, "cmi_rr_med", "cmi_rr_blue")
RUN_COST_KEYS = ("team_fte", "cloud", "licences", "assurance", "llm_requests_m")
STRICT_CASH = {"fte_released": 0.0, "vm_eff": 0.0, "insurance_saving": 0.0}
