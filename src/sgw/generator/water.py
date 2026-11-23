"""Pump-station zones: power source, generators, fuel and a standpipe tank, 1-min explicit step.

State per zone: tank volume V (gal), pump power source (grid, onsite generator, portable generator, none),
generator fuel (gal). dV/dt = Q_pump - Q_demand, V clipped to [0, V_full]; the pump fills the tank at its
capacity and then follows demand. Pressure at the station sensor p = p_residual + 0.433 * level_ft (psi).
Demand = average * diurnal(local hour, EDT) * storm leak multiplier (from the zone's peak-wind time) * seeded
leak. Generators: onsite units start on grid loss after the ATS delay unless the start fails (Bernoulli),
run until grid return, a run failure (exponential, or the seeded hour) or empty tank; burn
0.07*kW*(0.25+0.75*LF) gal/h; a fuel truck is called at the refuel trigger and arrives after its lead time
(plus a seeded blockage). PS-17 has no onsite unit: the portable generator is dispatched reactively after the
low-pressure alarm once sustained wind at the site is below tropical-storm force, and runs after the hookup
lead time. Validity: one tank per zone, no hydraulics between zones (WNTR in WP-13 checks this).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from sgw.generator.config import Family, parse_utc, rng
from sgw.generator.wind import epoch

PSI_PER_FT = 0.433
GAL_PER_FT3 = 7.48052
EDT_OFFSET_H = -4
MIN = 60.0


@dataclass
class ZoneSpec:
    station: str
    zone: str
    tank: str
    feeder: str
    onsite_generator: str | None
    portable: bool
    grid_loss_t: float | None
    grid_restore_t: float | None
    storm_from_t: float
    calm_t: float | None
    gen_fail_after_h: float | None = None
    gen_tank_h: float | None = None
    refuel_blocked_h: float = 0.0
    pump_trip: tuple[float, float] | None = None
    leak: tuple[float, float] | None = None


@dataclass
class ZoneRun:
    spec: ZoneSpec
    t: np.ndarray
    volume: np.ndarray
    pressure: np.ndarray
    pump_on: np.ndarray
    source: list[str]
    gen_events: list[tuple[float, str, str]] = field(default_factory=list)
    fuel: dict[str, np.ndarray] = field(default_factory=dict)

    def first_below(self, psi: float, after: float | None = None) -> float | None:
        mask = self.pressure < psi
        if after is not None:
            mask &= self.t >= after
        idx = np.flatnonzero(mask)
        return float(self.t[idx[0]]) if len(idx) else None

    def first_at_or_above(self, psi: float, after: float) -> float | None:
        idx = np.flatnonzero((self.pressure >= psi) & (self.t > after))
        return float(self.t[idx[0]]) if len(idx) else None


def tank_geometry(fam: Family) -> tuple[float, float]:
    d = fam.f("water.standpipe_diameter_ft")
    gal_per_ft = np.pi * d * d / 4.0 * GAL_PER_FT3
    return gal_per_ft, gal_per_ft * fam.f("water.level_full_ft")


def demand_gpm(t: np.ndarray, fam: Family) -> np.ndarray:
    hours = ((t / 3600.0 + EDT_OFFSET_H) % 24).astype(int)
    return fam.f("water.avg_demand_mgd") * 1e6 / 1440.0 * fam.arr("water.diurnal_factor")[hours]


def pressure_of(volume: np.ndarray, fam: Family) -> np.ndarray:
    gal_per_ft, _ = tank_geometry(fam)
    return fam.f("water.empty_residual_psi") + PSI_PER_FT * volume / gal_per_ft


def minutes_to_floor(start_t: float, fam: Family, storm: bool = True) -> float:
    """Minutes from a full tank with no inflow until the zone pressure drops below the state floor."""
    gal_per_ft, v_full = tank_geometry(fam)
    floor_ft = (fam.f("water.floor_psi") - fam.f("water.empty_residual_psi")) / PSI_PER_FT
    usable = v_full - floor_ft * gal_per_ft
    t = start_t + np.arange(0, 48 * 60) * MIN
    use = demand_gpm(t, fam) * (fam.f("water.storm_leak_multiplier") if storm else 1.0)
    idx = int(np.searchsorted(np.cumsum(use), usable))
    return float(idx)


def burn_gph(kw: float, fam: Family) -> float:
    lf = fam.f("generator.load_fraction")
    return fam.f("generator.burn_coeff") * kw * (0.25 + 0.75 * lf)


def simulate_zone(spec: ZoneSpec, fam: Family, t0: float, t1: float, seed: int) -> ZoneRun:
    t = np.arange(t0, t1 + 1.0, MIN)
    n = len(t)
    gal_per_ft, v_full = tank_geometry(fam)
    pump_gpm = fam.f("water.pump_capacity_mgd") * 1e6 / 1440.0
    base = demand_gpm(t, fam)
    mult = np.where(t >= spec.storm_from_t, fam.f("water.storm_leak_multiplier"), 1.0)
    if spec.leak:
        mult = mult * np.where(t >= spec.leak[0], spec.leak[1], 1.0)
    dem = base * mult
    vol = np.empty(n)
    on = np.zeros(n, dtype=bool)
    src: list[str] = []
    v = v_full
    kw = fam.f("generator.onsite_kw") if spec.onsite_generator else 0.0
    gen_id = spec.onsite_generator
    events: list[tuple[float, str, str]] = []
    fuel_series = np.full(n, np.nan)
    r = rng(seed, "water", spec.station)
    fts = r.uniform() < fam.f("generator.fail_to_start_good")
    run_fail_h = (
        spec.gen_fail_after_h
        if spec.gen_fail_after_h is not None
        else float(r.exponential(fam.f("generator.run_mttf_good_h")))
    )
    if spec.portable:
        kw = 500.0
        tank = fam.f("generator.portable_tank_gal")
    else:
        tank_h = spec.gen_tank_h if spec.gen_tank_h is not None else 24.0 * 5
        tank = fam.f("generator.burn_coeff") * kw * fam.f("generator.load_fraction") * tank_h if kw else 0.0
    fuel = tank
    burn = burn_gph(kw, fam) / 60.0 if kw else 0.0
    state = "standby"
    run_min = 0.0
    truck_eta: float | None = None
    truck_calls = 0
    gen_start_t: float | None = None
    alarm_t: float | None = None
    for i in range(n):
        ti = t[i]
        grid = not (
            spec.grid_loss_t is not None
            and spec.grid_loss_t <= ti
            and (spec.grid_restore_t is None or ti < spec.grid_restore_t)
        )
        if spec.portable and gen_start_t is None and not grid and alarm_t is not None:
            dispatch = max(alarm_t, spec.calm_t or alarm_t)
            gen_start_t = dispatch + fam.f("generator.hookup_lead_min") * MIN
            events.append((dispatch, "MGEN-HALBERD-500", "dispatched"))
        if gen_id or spec.portable:
            label = gen_id or "MGEN-HALBERD-500"
            if grid and state in ("running", "out_of_fuel", "failed_run"):
                state = "standby" if not spec.portable else "demobilised"
                events.append((ti, label, state))
            elif not grid and state == "standby":
                ready = (
                    spec.grid_loss_t + fam.f("generator.ats_delay_s") if not spec.portable else gen_start_t
                )
                if ready is not None and ti >= ready:
                    state = "failed_start" if (fts and not spec.portable) else "running"
                    events.append((ti, label, state))
            if state == "running":
                fuel -= burn
                run_min += 1.0
                if fuel <= fam.f("fuel.refuel_trigger_frac") * tank and truck_eta is None:
                    lead = fam.f("fuel.truck_lead_min") * MIN
                    blocked = spec.refuel_blocked_h * 3600.0 if truck_calls == 0 else 0.0
                    truck_eta = ti + lead + blocked
                    truck_calls += 1
                    events.append((ti, "FTK-WREN-3", f"requested:{label}"))
                if run_min / 60.0 >= run_fail_h:
                    state = "failed_run"
                    events.append((ti, label, state))
                elif fuel <= 0.0:
                    fuel = 0.0
                    state = "out_of_fuel"
                    events.append((ti, label, state))
            if truck_eta is not None and ti >= truck_eta:
                fuel = tank
                truck_eta = None
                events.append((ti, "FTK-WREN-3", f"delivered:{label}"))
                if state == "out_of_fuel":
                    state = "running"
                    events.append((ti, label, state))
            fuel_series[i] = fuel if kw else np.nan
        powered = grid or state == "running"
        tripped = spec.pump_trip is not None and spec.pump_trip[0] <= ti < spec.pump_trip[1]
        pump = powered and not tripped
        q_in = min(pump_gpm, dem[i] + (v_full - v)) if pump else 0.0
        v = min(max(v + q_in - dem[i], 0.0), v_full)
        vol[i] = v
        on[i] = pump
        src.append("grid" if grid else ("generator" if state == "running" else "none"))
        if (
            alarm_t is None
            and not grid
            and pressure_of(np.array([v]), fam)[0] < fam.f("water.low_pressure_alarm_psi")
        ):
            alarm_t = ti
    run = ZoneRun(spec, t, vol, pressure_of(vol, fam), on, src, events)
    run.fuel[gen_id or ("MGEN-HALBERD-500" if spec.portable else "")] = fuel_series
    return run


def zone_specs(
    scenario: dict[str, Any],
    section_fault: dict[str, float | None],
    section_restore: dict[str, float | None],
    peak_t: dict[str, float],
    calm_t: dict[str, float | None],
) -> list[ZoneSpec]:
    named = scenario["named"]
    pins = {c["id"]: c["pin"] for c in scenario["seeded"] if isinstance(c.get("pin"), dict)}
    specs = []
    for ps_id, ps in named["pump_stations"].items():
        sec = f"{ps['feeder']}-S1"
        spec = ZoneSpec(
            station=ps_id,
            zone=ps["zone"],
            tank=ps["tank"],
            feeder=ps["feeder"],
            onsite_generator=ps.get("onsite_generator"),
            portable=ps.get("onsite_generator") is None and ps_id == "PS-17",
            grid_loss_t=section_fault.get(sec),
            grid_restore_t=section_restore.get(sec),
            storm_from_t=peak_t[sec],
            calm_t=calm_t.get(sec),
        )
        for pin in pins.values():
            if pin.get("generator") and pin["generator"] == spec.onsite_generator:
                spec.gen_fail_after_h = pin.get("fail_after_run_h")
                spec.gen_tank_h = pin.get("tank_h")
                spec.refuel_blocked_h = float(pin.get("refuel_blocked_h", 0.0))
        for case_id, pin in pins.items():
            if case_id == f"FAULT-{ps_id.replace('-', '')}-PUMP-TRIP":
                start = epoch(parse_utc(pin["from_utc"]))
                spec.pump_trip = (start, start + float(pin["duration_h"]) * 3600.0)
            if case_id == f"FAULT-{ps_id.replace('-', '')}-LEAK":
                spec.leak = (epoch(parse_utc(pin["from_utc"])), float(pin["demand_multiplier"]))
        specs.append(spec)
    return specs
