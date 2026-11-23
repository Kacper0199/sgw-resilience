from __future__ import annotations

import dataclasses
import json
from datetime import datetime

import numpy as np
import pytest

from sgw.contracts.clocks import ClockBasis
from sgw.generator.config import rng
from sgw.models.clocks.ps17 import CASE_POWER, ps17_specs
from sgw.models.clocks.service import compute_queue
from sgw.models.water.basis import drain_basis, generator_runtime_basis
from sgw.models.water.params import family, twin_params
from sgw.models.water.ps17_members import OUT_PATH, STATION
from sgw.models.water.survival import StationCase, burn_gph, demand_multipliers, onsite_tank_gal, simulate
from sgw.models.water.telemetry import epoch
from sgw.models.water.twin import zone_twins

LOSS = epoch("2024-09-27T05:30:00Z")
WP06_TABLE = "tests/unit/models/clocks/data/wp06_helene_ps17_members.json"


def run(case: StationCase, **kw: object) -> object:
    return simulate(zone_twins()[case.station], case, 25.0, family(), twin_params(), **kw)


def test_no_backup_always_breaches_once_the_tank_drains() -> None:
    res = run(StationCase("PS-23", LOSS, None, "none"), samples=200, horizon_h=12)
    assert res.p_breach == 1.0
    assert set(res.cause) == {"no_backup"}
    q = res.breach_quantiles_min(LOSS)
    assert q is not None and 60 < q[1] < 400


def test_grid_back_before_the_drain_leaves_only_demand_breaches() -> None:
    res = run(StationCase("PS-23", LOSS, LOSS + 30 * 60, "none"), samples=200, horizon_h=12)
    assert set(res.cause[~np.isnan(res.breach_t)]) <= {"demand"}
    assert res.p_breach < 0.2


def test_runs_are_exactly_repeatable_and_seeded() -> None:
    fam = family()
    case = StationCase("PS-52", LOSS, None, "onsite", 350.0, onsite_tank_gal(350.0, fam))
    a = run(case, samples=300, horizon_h=24)
    b = run(case, samples=300, horizon_h=24)
    c = run(case, samples=300, horizon_h=24, seed=7)
    np.testing.assert_array_equal(a.breach_t, b.breach_t)
    np.testing.assert_array_equal(a.minutes_below, b.minutes_below)
    assert not np.array_equal(a.minutes_below, c.minutes_below)


def test_a_starved_tank_breaches_more_often_and_runs_out_of_fuel() -> None:
    fam = family()
    full = StationCase("PS-38", LOSS, None, "onsite", 350.0, onsite_tank_gal(350.0, fam), gen_class="good")
    tank = burn_gph(350.0, fam) * 6.0
    starved = StationCase("PS-38", LOSS, None, "onsite", 350.0, tank, gen_class="good")
    a = run(full, samples=400, horizon_h=48)
    b = run(starved, samples=400, horizon_h=48)
    assert b.p_breach > a.p_breach
    assert np.mean(b.cause == "out_of_fuel") > 0.0
    assert b.deliveries.mean() >= 1.0


def test_later_hookup_never_lowers_the_breach_probability_before_hookup() -> None:
    fam = family()
    probs, total = [], []
    for delay in (0, 120, 180, 300):
        case = StationCase(
            "PS-17",
            LOSS,
            None,
            "portable",
            500.0,
            fam.f("generator.portable_tank_gal"),
            hookup_epoch=LOSS + delay * 60,
        )
        res = run(case, samples=300, horizon_h=12)
        probs.append(float(np.mean(res.cause == "awaiting_hookup")))
        total.append(res.p_breach)
    assert probs == sorted(probs)
    assert probs[0] == 0.0
    assert total[-1] == 1.0


def test_demand_multipliers_follow_the_labelled_ranges() -> None:
    tp = twin_params()
    m = demand_multipliers(tp, rng(1, "t"), 20000)
    lo, mode, hi = tp["demand.leak_multiplier_triangular"]
    assert np.median(m) == pytest.approx((lo + mode + hi) / 3, rel=0.08)
    strat = demand_multipliers(tp, rng(1, "t"), 40, stratified=True)
    assert len(np.unique(strat)) == 40


@pytest.fixture(scope="module")
def table() -> dict:
    return json.loads(OUT_PATH.read_text())


def test_member_table_drains_recompute_from_the_twin(table: dict) -> None:
    twin = zone_twins()[STATION]
    floor = table["water_twin"]["floor_psi"]
    for adv in table["advisories"].values():
        for m in adv["members"]:
            if m["exposure_utc"] is None:
                assert m["drain_to_floor_min"] is None
                continue
            d = float(
                twin.drain_to_floor_min(
                    epoch(m["exposure_utc"]), m["demand_multiplier"], floor, adv["tank_level0_ft"]
                )
            )
            assert d == pytest.approx(m["drain_to_floor_min"], abs=0.06)


def test_member_demand_uses_common_random_numbers_across_advisories(table: dict) -> None:
    n, n1 = (table["advisories"][k]["members"] for k in ("N", "N+1"))
    for a, b in zip(n, n1, strict=True):
        if a["demand_multiplier"] is not None and b["demand_multiplier"] is not None:
            assert a["demand_multiplier"] == b["demand_multiplier"]


def test_twin_basis_keeps_the_hinge_and_moves_the_clock_earlier(table: dict) -> None:
    with open(WP06_TABLE, encoding="utf-8") as fh:
        wp06 = json.load(fh)

    def effective(t: dict, label: str) -> datetime:
        adv = t["advisories"][label]
        now = datetime.fromisoformat(adv["issued_utc"].replace("Z", "+00:00"))
        return compute_queue(ps17_specs(adv, t), now=now).cases[CASE_POWER].case.effective_decide_by_utc

    old = {k: effective(wp06, k) for k in ("N", "N+1")}
    new = {k: effective(table, k) for k in ("N", "N+1")}
    shift_old = (old["N+1"] - old["N"]).total_seconds() / 60
    shift_new = (new["N+1"] - new["N"]).total_seconds() / 60
    assert shift_new < 0 and abs(shift_new - shift_old) <= 15
    for k in ("N", "N+1"):
        assert new[k] < old[k]
    basis = ClockBasis.model_validate(table["water_twin"]["drain_basis"])
    assert basis == drain_basis()
    assert basis.basis_id == "water_twin.zone_drain_critical_node"
    assert basis.basis_version == "1.2-synthetic"
    assert "R.61-58.7.E(7)" in (basis.citation or "")
    assert (
        ClockBasis.model_validate(table["water_twin"]["generator_runtime_basis"]) == generator_runtime_basis()
    )
    assert "R.61-58.7.E(7)" in table["water_twin"]["floor_citation"]


def test_demand_above_pump_capacity_drains_the_tank_on_grid_power() -> None:
    twin = zone_twins()["PS-23"]
    tp = twin_params()
    start = epoch("2024-09-27T10:00:00Z")
    assert float(twin.demand_gpm(np.array(start + 3 * 3600.0), 2.0)) > twin.pump_gpm
    raw = dict(tp.raw)
    raw["demand.leak_multiplier_triangular"] = {
        **raw["demand.leak_multiplier_triangular"],
        "value": [1.999, 2.0, 2.001],
    }
    raw["demand.base_scale_lognormal_sigma"] = {**raw["demand.base_scale_lognormal_sigma"], "value": 1e-9}
    leak2 = dataclasses.replace(tp, raw=raw)
    grid_on = StationCase("PS-23", start, start, "none")
    res = simulate(twin, grid_on, 25.0, family(), leak2, samples=20, horizon_h=14)
    assert res.p_breach == 1.0
    calm = simulate(twin, grid_on, 25.0, family(), tp, samples=200, horizon_h=14)
    assert calm.p_breach < res.p_breach


def test_critical_node_is_reported_from_the_hydraulics_not_assumed(table: dict) -> None:
    meta = table["water_twin"]
    assert set(meta["critical_node_counts_wntr"]) >= {"J-CF-TALLOWBRANCH", "J-CF-14"}
    assert sum(meta["critical_node_counts_wntr"].values()) >= 0.95 * 48 * 4 * 3
    members = [
        m for a in table["advisories"].values() for m in a["members"] if m["drain_to_floor_min"] is not None
    ]
    assert all(m["critical_node"] for m in members)
