from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from sgw.common import numbers as numbers_mod
from sgw.contracts.vocab import ClockKind
from sgw.models.water.floors import FlowCondition, State, floors_for, pre_landfall_advisory, service_floor
from sgw.models.water.params import ARTEFACT_DIR
from sgw.models.water.validate import TOLERANCE_MIN, compare


@pytest.fixture(scope="module")
def report() -> dict:
    return compare()


def test_reduced_twin_meets_the_wntr_tolerance(report: dict) -> None:
    s = report["floors"]["25_psi"]["variants"]["twin_looped"]
    assert report["passed"]
    assert s["median_abs_min"] <= TOLERANCE_MIN
    grid = json.loads((ARTEFACT_DIR / "wntr_drain_grid.json").read_text())
    converged = [r for r in grid["rows"] if r["t_floor_25_min"] is not None]
    assert s["n"] == len(converged) >= 0.99 * 4 * 48 * 4 * 3


def test_reduced_twin_regression_guard(report: dict) -> None:
    for floor in ("25_psi", "20_psi"):
        s = report["floors"][floor]["variants"]["twin_looped"]
        assert s["median_abs_min"] < 0.5
        assert s["max_abs_min"] < 2.0


def test_station_sensor_floor_is_late_against_the_hydraulic_solver(report: dict) -> None:
    s = report["floors"]["25_psi"]["variants"]["station_sensor_floor"]
    assert s["mean_signed_min"] > 5.0


def test_tree_reduction_is_conservative_on_average(report: dict) -> None:
    assert report["floors"]["25_psi"]["variants"]["twin_tree"]["mean_signed_min"] < 0.0


def test_floors_come_from_numbers() -> None:
    assert service_floor(State.SC).psi == numbers_mod.value("sc_pressure_floor_psi")
    assert service_floor(State.SC, FlowCondition.HEAVY).psi == numbers_mod.value(
        "sc_pressure_floor_heavy_flow_psi"
    )
    assert service_floor(State.GA).psi == numbers_mod.value("ga_pressure_floor_psi")
    assert service_floor(State.GA, FlowCondition.HEAVY).psi == numbers_mod.value("ga_pressure_floor_psi")
    assert floors_for(State.SC)[0].psi > floors_for(State.SC)[1].psi
    assert len(floors_for(State.GA)) == 1
    assert "R.61-58.7.E(7)" in service_floor(State.SC).citation
    assert "391-3-5-.10" in service_floor(State.GA).citation


def test_pre_landfall_advisory_is_sc_only_and_thresholded() -> None:
    landfall = datetime(2024, 9, 27, 3, 10, tzinfo=UTC)
    kw = {"zone_id": "WZ-PS17-CEDARFALL", "landfall_utc": landfall, "on_backup_or_exposed": True}
    sc = pre_landfall_advisory(state=State.SC, breach_p=0.5, **kw)
    assert sc is not None and sc.due_utc == landfall
    assert sc.basis.kind is ClockKind.RULE_DEADLINE
    assert sc.basis.basis_id == "rule.sc_bwa_pre_landfall"
    assert pre_landfall_advisory(state=State.GA, breach_p=0.5, **kw) is None
    assert pre_landfall_advisory(state=State.SC, breach_p=0.01, **kw) is None
    kw["on_backup_or_exposed"] = False
    assert pre_landfall_advisory(state=State.SC, breach_p=0.9, **kw) is None


def test_structural_band_is_reported_and_the_reduction_holds_on_it(report: dict) -> None:
    band = report["structural_band"]
    assert set(band["stations"]) == {"PS-17", "PS-23", "PS-38", "PS-52"}
    assert band["twin_vs_wntr_on_band_networks"]["median_abs_min"] < 0.5
    ps17 = band["stations"]["PS-17"]["drain_delta_vs_nominal_min"]
    assert ps17["min"] <= 0.0 <= ps17["max"]
    assert report["kind"].startswith("verification")
