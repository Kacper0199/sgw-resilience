"""The ROI reproduction matches the R04 model outputs and the committed results file."""

from __future__ import annotations

import json

import pytest

from sgw.roi.__main__ import RESULTS_PATH, build, render
from sgw.roi.model import breakevens, run, storm_year_spread, structural_tests
from sgw.roi.stage1 import derive

R04_SCENARIOS = {
    "conservative": {"one_time": 52.0, "run_cost": 19.7, "npv_cash": -144.8, "npv_customer": -106.5},
    "base": {"one_time": 35.0, "run_cost": 12.7, "npv_cash": -17.6, "npv_customer": 220.1},
    "optimistic": {"one_time": 23.5, "run_cost": 8.6, "npv_cash": 173.4, "npv_customer": 1146.8},
}


@pytest.mark.parametrize("scenario", list(R04_SCENARIOS))
def test_scenarios_match_r04(scenario: str) -> None:
    r = run(scenario)
    for field, expected in R04_SCENARIOS[scenario].items():
        assert round(getattr(r, field), 1) == expected, field


def test_base_ratios_and_payback_match_r04() -> None:
    r = run("base")
    assert round(r.bcr_cash, 2) == 0.84
    assert round(r.bcr_customer, 2) == 2.99
    assert r.payback_cash is None
    assert r.payback_customer == 3.4
    assert round(r.cash_benefit, 1) == 20.4


def test_breakevens_match_r04() -> None:
    be = breakevens()
    assert round(be["cash"]["base"], 2) == 1.19
    assert round(be["cash_strict"]["base"], 2) == 1.99
    assert round(be["cash"]["conservative"], 2) == 7.05
    assert round(be["cash"]["optimistic"], 2) == 0.30
    assert be["customer_major_event_only"]["base"] == 0.0


def test_structural_range_matches_r04() -> None:
    cash = {name: round(r.npv_cash, 1) for name, r in structural_tests()}
    assert min(cash.values()) == -54.9
    assert max(cash.values()) == 4.7


def test_storm_year_spread_matches_r04() -> None:
    spread = storm_year_spread("base")
    assert spread["cash_npv_p10_p50_p90"] == [-30.8, -19.1, -3.1]
    assert spread["customer_npv_p10_p50_p90"] == [148.1, 212.0, 299.0]


def test_stage1_price_is_phase_sum_and_ordered() -> None:
    price = derive()["price_musd"]
    for s in price.values():
        assert s["stage1"] == pytest.approx(s["phase_0"] + s["phase_1"])
        assert s["stage1"] == pytest.approx(s["year_one_spend"] * 8 / 12)
    assert price["optimistic"]["stage1"] < price["base"]["stage1"] < price["conservative"]["stage1"]


def test_benefit_gate_is_cash_breakeven() -> None:
    gate = derive()["gate_benefit"]
    assert gate["breakeven_share"] > gate["base_assumption"]
    assert abs(run("base", {"storm_eff": gate["breakeven_share"]}).npv_cash) < 1e-6
    assert run("base", {"storm_eff": gate["breakeven_share"] * 0.99}).npv_cash < 0
    assert gate["breakeven_share_strict_cash"] > gate["breakeven_share"]


def test_committed_results_file_is_current() -> None:
    assert RESULTS_PATH.read_text(encoding="utf-8") == render(build())


def test_results_file_keeps_views_separate() -> None:
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    h = data["headline"]
    assert h["cash_npv_base"] < 0 < h["customer_npv_base"]
    assert {"npv_cash", "npv_customer"} <= set(data["tornado"])
