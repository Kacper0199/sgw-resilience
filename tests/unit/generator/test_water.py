"""Water zone model: mass balance, bounds, burn rate and the seeded generator cases."""

from __future__ import annotations

import numpy as np
import pytest

from sgw.generator import water as wt
from sgw.generator.config import Family, parse_utc
from sgw.generator.scenario import GenerationResult
from sgw.generator.wind import epoch

T0 = epoch(parse_utc("2024-09-27T00:00:00Z"))


def _spec(**kw: object) -> wt.ZoneSpec:
    base = dict(
        station="PS-99",
        zone="WZ-PS99-TEST",
        tank="TNK-PS99-TEST",
        feeder="FDR-X-1",
        onsite_generator=None,
        portable=False,
        grid_loss_t=T0 + 3600.0,
        grid_restore_t=None,
        storm_from_t=T0,
        calm_t=None,
    )
    base.update(kw)
    return wt.ZoneSpec(**base)  # type: ignore[arg-type]


def test_mass_balance_without_power(fam_a: Family) -> None:
    run = wt.simulate_zone(_spec(), fam_a, T0, T0 + 6 * 3600.0, 1)
    _, v_full = wt.tank_geometry(fam_a)
    k0 = int(np.argmax(run.t >= T0 + 3600.0))
    steps = slice(k0 + 1, len(run.t))
    t = run.t[steps]
    demand = wt.demand_gpm(t, fam_a) * fam_a.f("water.storm_leak_multiplier")
    expected = np.maximum(run.volume[k0] - np.cumsum(demand), 0.0)
    assert np.allclose(run.volume[steps], expected, rtol=1e-9, atol=1e-6)
    assert run.volume[k0 - 1] == pytest.approx(v_full)


def test_tank_stays_within_bounds_and_refills_when_powered(fam_a: Family) -> None:
    run = wt.simulate_zone(_spec(grid_restore_t=T0 + 8 * 3600.0), fam_a, T0, T0 + 20 * 3600.0, 1)
    _, v_full = wt.tank_geometry(fam_a)
    assert run.volume.min() >= 0.0 and run.volume.max() <= v_full + 1e-9
    assert run.pressure[-1] == pytest.approx(wt.pressure_of(np.array([v_full]), fam_a)[0], abs=0.5)


def test_minutes_to_floor_matches_the_simulated_crossing(fam_a: Family) -> None:
    start = T0 + 3600.0
    run = wt.simulate_zone(_spec(grid_loss_t=start), fam_a, T0, T0 + 12 * 3600.0, 1)
    crossing = run.first_below(fam_a.f("water.floor_psi"))
    assert crossing is not None
    assert (crossing - start) / 60.0 == pytest.approx(wt.minutes_to_floor(start + 60.0, fam_a), abs=2.0)


def test_burn_rate_matches_the_handoff_example(fam_a: Family) -> None:
    assert wt.burn_gph(500.0, fam_a) == pytest.approx(27.125)


def test_seeded_generator_failure_and_fuel_blockage_manifest(generated: GenerationResult) -> None:
    water = generated.truth_table["water"]
    ps52 = [e[2] for e in water["PS-52"]["generator_events"]]
    assert "failed_run" in ps52
    run_t = parse_utc(water["PS-52"]["generator_events"][0][0])
    fail_t = parse_utc(next(e[0] for e in water["PS-52"]["generator_events"] if e[2] == "failed_run"))
    assert (fail_t - run_t).total_seconds() / 3600.0 == pytest.approx(30.0, abs=0.05)
    ps38 = [e[2] for e in water["PS-38"]["generator_events"]]
    assert "out_of_fuel" in ps38 and ps38.index("out_of_fuel") < ps38.index("running", 1)
    assert water["PS-38"]["below_floor_utc"] is not None


def test_hospital_zone_loses_pressure_while_the_hospital_keeps_power(generated: GenerationResult) -> None:
    ps17 = generated.truth_table["water"]["PS-17"]
    assert ps17["below_floor_utc"] is not None and ps17["back_above_floor_utc"] is not None
    assert parse_utc(ps17["below_floor_utc"]) > parse_utc(ps17["grid_loss_utc"])
    hospital = generated.truth_table["water"]["hospital"]
    assert hospital["grid_loss_utc"] is None or hospital["generator"] == "GEN-HSP-TALLOWBRANCH"
