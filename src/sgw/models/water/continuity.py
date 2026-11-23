"""Station continuity report for a scenario: survival Monte Carlo per station, PS-17 hookup curve, SC
pre-landfall advisory flags, and the realised outcome of the synthetic truth beside each forecast.

Power events (grid loss and restore) are scenario inputs; in the platform they come from the outage
forecast and restoration. The onsite fuel state is nowcast from SCADA: the first `fuel_gal` reading of
a generator (known within an hour of start) sets its tank; without a reading the tank is sized for five days
at 70 percent load. The as-of time of each station forecast is stated in its row.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import numpy as np

from sgw.common.telemetry import sgw_span
from sgw.contracts.vocab import Classification, RunMode
from sgw.models.water.floors import State, pre_landfall_advisory, service_floor
from sgw.models.water.params import ARTEFACT_DIR, family, scenario, twin_params
from sgw.models.water.survival import StationCase, burn_gph, onsite_tank_gal, simulate
from sgw.models.water.telemetry import epoch, load_water_series
from sgw.models.water.twin import zone_twins

OUT_PATH = ARTEFACT_DIR / "continuity_helene.json"
HOOKUP_DELAYS_MIN = (0, 60, 120, 150, 180, 240, 300, 360)


def _iso(t: float | None) -> str | None:
    from sgw.models.water.ps17_members import iso

    return None if t is None else iso(t)


def station_cases(fixture: str = "helene") -> list[tuple[StationCase, float]]:
    sc = scenario()
    fam = family()
    truth = json.loads((ARTEFACT_DIR.parents[1] / "fixtures" / fixture / "truth_table.json").read_text())[
        "water"
    ]
    series = load_water_series(fixture)
    port = sc["named"]["portable_generator"]
    out = []
    for st, ps in sc["named"]["pump_stations"].items():
        w = truth[st]
        if w["grid_loss_utc"] is None:
            continue
        loss = epoch(w["grid_loss_utc"])
        restore = None if w["grid_restore_utc"] is None else epoch(w["grid_restore_utc"])
        gen = ps.get("onsite_generator")
        if gen:
            kw = fam.f("generator.onsite_kw")
            fuel = series.get(f"{gen}:fuel_gal")
            first = None if fuel is None else int(np.argmax(fuel.t >= loss))
            if fuel is not None and first is not None and fuel.t[first] >= loss:
                tank = float(fuel.value[first]) + burn_gph(kw, fam) * (fuel.t[first] - loss) / 3600.0
                as_of = float(fuel.known_t[first])
            else:
                tank, as_of = onsite_tank_gal(kw, fam), loss
            case = StationCase(st, loss, restore, "onsite", kw, tank)
        elif st == "PS-17":
            kw = float(port["kw"])
            case = StationCase(
                st, loss, restore, "portable", kw, fam.f("generator.portable_tank_gal"), hookup_epoch=None
            )
            as_of = loss
        else:
            case = StationCase(st, loss, restore, "none")
            as_of = loss
        out.append((case, as_of))
    return out


def continuity_report(fixture: str = "helene", samples: int | None = None) -> dict[str, Any]:
    sc = scenario()
    fam = family()
    tp = twin_params()
    twins = zone_twins()
    floor = service_floor(State.SC)
    truth = json.loads((ARTEFACT_DIR.parents[1] / "fixtures" / fixture / "truth_table.json").read_text())[
        "water"
    ]
    landfall = epoch(sc["storm"]["landfall_utc"])
    rows = []
    with sgw_span(
        "water.continuity",
        run_id=f"water-continuity-{fixture}",
        classification=Classification.C1,
        user_role="system",
        run_mode=RunMode.REPLAY,
        node="water_twin",
        region_id="SC-45003",
    ):
        for case, as_of in station_cases(fixture):
            run_case = case
            if case.generator == "portable":
                run_case = StationCase(
                    case.station,
                    case.loss_epoch,
                    case.restore_epoch,
                    "portable",
                    case.gen_kw,
                    case.tank_gal,
                    hookup_epoch=case.loss_epoch + fam.f("generator.hookup_lead_min") * 60.0,
                )
            res = simulate(twins[case.station], run_case, floor.psi, fam, tp, samples=samples)
            w = truth[case.station]
            flag = pre_landfall_advisory(
                zone_id=sc["named"]["pump_stations"][case.station]["zone"],
                state=State.SC,
                landfall_utc=datetime.fromtimestamp(landfall, tz=UTC),
                breach_p=res.p_breach,
                on_backup_or_exposed=True,
            )
            rows.append(
                {
                    **res.summary(case.loss_epoch),
                    "generator": case.generator,
                    "tank_gal": round(case.tank_gal, 1),
                    "as_of_utc": _iso(as_of),
                    "grid_loss_utc": w["grid_loss_utc"],
                    "grid_restore_utc": w["grid_restore_utc"],
                    "assumed_hookup_after_loss_min": fam.f("generator.hookup_lead_min")
                    if case.generator == "portable"
                    else None,
                    "realised_below_floor_utc_station_sensor": w["below_floor_utc"],
                    "pre_landfall_advisory_due_utc": None if flag is None else _iso(flag.due_utc.timestamp()),
                }
            )
        ps17 = next(c for c, _ in station_cases(fixture) if c.station == "PS-17")
        curve = []
        for delay in HOOKUP_DELAYS_MIN:
            case = StationCase(
                ps17.station,
                ps17.loss_epoch,
                ps17.restore_epoch,
                "portable",
                ps17.gen_kw,
                ps17.tank_gal,
                hookup_epoch=ps17.loss_epoch + delay * 60.0,
            )
            res = simulate(twins["PS-17"], case, floor.psi, fam, tp, samples=samples)
            curve.append(
                {
                    "hookup_after_loss_min": delay,
                    "p_breach": round(res.p_breach, 4),
                    "mean_minutes_below_floor": round(float(res.minutes_below.mean()), 1),
                }
            )
    return {
        "label": "synthetic",
        "model_id": tp.model_ids["survival"],
        "version": tp.version,
        "floor": {"psi": floor.psi, "rule_id": floor.rule_id, "citation": floor.citation},
        "samples": int(samples if samples is not None else tp["mc.samples"]),
        "seed": int(tp["mc.seed"]),
        "stations": rows,
        "ps17_hookup_curve": curve,
    }
