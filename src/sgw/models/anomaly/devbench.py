"""Seeded dev bench for A7/A8 (dev split, family A only): station runs from the WP-06 zone simulator with
random power events, generator troubles, physical faults (pump trip, leak) and sensor faults (frozen level,
pressure drift, pressure replay, level replay), emitted with the family's sensor noise, resolution and
sampling.

Fault parameters are drawn from ranges around the seeded helene cases, never from family B. Each run is one
station over four days; its truth lists every fault window and every physical low-pressure episode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from sgw.generator import water as wt
from sgw.generator.config import rng
from sgw.models.anomaly.streams import StationStreams
from sgw.models.water.params import family

BENCH_SEED = 20260
T0 = 1727308800.0
DAYS = 4
SENSOR_FAULTS = ("stuck_level", "drift_pressure", "replay_pressure", "replay_level")
PHYSICAL_FAULTS = ("pump_trip", "leak")


@dataclass
class TruthWindow:
    kind: str
    family: str
    start: float
    end: float
    device: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchRun:
    run_id: str
    streams: StationStreams
    truth: list[TruthWindow]


def _spec(r: np.random.Generator, station: str) -> tuple[wt.ZoneSpec, list[TruthWindow]]:
    t_end = T0 + DAYS * 86400.0
    loss = restore = None
    storm = T0 + r.uniform(20, 60) * 3600.0
    if r.uniform() < 0.6:
        loss = storm + r.uniform(-2, 4) * 3600.0
        restore = min(loss + r.lognormal(np.log(14.0), 0.6) * 3600.0, t_end - 3600.0)
    gen = f"GEN-{station.replace('-', '')}-BENCH" if r.uniform() < 0.5 else None
    spec = wt.ZoneSpec(
        station=station,
        zone=f"WZ-{station}",
        tank=f"TNK-{station}",
        feeder=f"FDR-{station}",
        onsite_generator=gen,
        portable=False,
        grid_loss_t=loss,
        grid_restore_t=restore,
        storm_from_t=storm,
        calm_t=None,
    )
    truth: list[TruthWindow] = []
    if gen and loss is not None:
        u = r.uniform()
        if u < 0.2:
            spec.gen_fail_after_h = float(r.uniform(3, 30))
        elif u < 0.4:
            spec.gen_tank_h = float(r.uniform(8, 24))
            spec.refuel_blocked_h = float(r.uniform(2, 12))
    n_faults = int(r.choice([0, 1, 1, 2]))
    kinds = [str(k) for k in r.choice(SENSOR_FAULTS + PHYSICAL_FAULTS, size=n_faults, replace=False)]
    for kind in kinds:
        if kind == "pump_trip":
            grid_up = [(T0 + 6 * 3600.0, (loss or t_end) - 6 * 3600.0)]
            if restore is not None:
                grid_up.append((restore + 6 * 3600.0, t_end - 6 * 3600.0))
            grid_up = [w for w in grid_up if w[1] - w[0] > 3600.0]
            if not grid_up:
                continue
            a, b = grid_up[int(r.integers(0, len(grid_up)))]
            start = float(np.floor(r.uniform(a, b) / 60.0) * 60.0)
            dur = float(r.uniform(1.0, 4.0)) * 3600.0
            spec.pump_trip = (start, start + dur)
            truth.append(TruthWindow("pump_trip", "A7", start, start + dur))
        elif kind == "leak":
            start = float(np.floor(r.uniform(T0 + 36 * 3600.0, t_end - 12 * 3600.0) / 900.0) * 900.0)
            spec.leak = (start, float(r.uniform(1.1, 1.3)))
            truth.append(TruthWindow("leak", "A7", start, t_end, detail={"multiplier": spec.leak[1]}))
        else:
            start = float(np.floor(r.uniform(T0 + 30 * 3600.0, t_end - 20 * 3600.0) / 1800.0) * 1800.0)
            dur = (
                float(
                    r.uniform(6, 18)
                    if kind == "stuck_level"
                    else r.uniform(12, 24)
                    if kind == "drift_pressure"
                    else r.uniform(1.5, 3.0)
                )
                * 3600.0
            )
            detail: dict[str, Any] = {}
            if kind == "drift_pressure":
                detail["psi_per_h"] = float(r.choice([-1, 1]) * r.uniform(0.1, 0.3))
            if kind.startswith("replay"):
                detail["lag_h"] = float(r.choice([24.0, float(np.round(r.uniform(12, 30) * 2) / 2)]))
            truth.append(TruthWindow(kind, "A8", start, start + dur, detail=detail))
    return spec, truth


def _inject(t: np.ndarray, pt: np.ndarray, lt: np.ndarray, truth: list[TruthWindow]) -> None:
    for w in truth:
        if w.family != "A8":
            continue
        win = (t >= w.start) & (t < w.end)
        if not win.any():
            continue
        if w.kind == "stuck_level":
            lt[win] = lt[np.argmax(win)]
        elif w.kind == "drift_pressure":
            pt[win] = np.round(pt[win] + (t[win] - w.start) / 3600.0 * w.detail["psi_per_h"], 1)
        else:
            shift = int(round(w.detail["lag_h"] * 4))
            k = np.flatnonzero(win)
            k = k[k - shift >= 0]
            target = pt if w.kind == "replay_pressure" else lt
            target[k] = target[k - shift]


def _observability(run: wt.ZoneRun, truth: list[TruthWindow], gal_per_ft: float, fam: Any) -> None:
    """Physics-only flags (from the true state, not the detector): a leak is `observable` when the tank
    leaves its full level with steady pump state in at least 4 half-hour windows before and 2 after the onset
    (with the tank held full, demand within pump capacity changes neither pressure nor level); a replay is
    `consequential` when the true signal moves by more than three noise sigmas against the replayed copy."""
    t30 = run.t[::30]
    level = run.volume[::30] / gal_per_ft
    pump = run.pump_on[::30]
    full = level.max() if len(level) else 0.0
    informative = np.zeros(len(t30), dtype=bool)
    informative[1:] = (
        (level[1:] > 0.5) & (level[:-1] > 0.5) & (level[1:] < full - 1.5) & (level[:-1] < full - 1.5)
    )
    informative[1:] &= pump[1:] == pump[:-1]
    for w in truth:
        if w.kind == "leak":
            before = int(np.sum(informative & (t30 < w.start)))
            after = int(np.sum(informative & (t30 >= w.start)))
            w.detail["observable"] = before >= 4 and after >= 2
        elif w.kind.startswith("replay"):
            lag = w.detail["lag_h"] * 3600.0
            win = (run.t >= w.start) & (run.t < w.end)
            src = np.clip(np.searchsorted(run.t, run.t[win] - lag), 0, len(run.t) - 1)
            if w.kind == "replay_pressure":
                move = np.abs(run.pressure[win] - run.pressure[src])
                sigma = fam.f("water.pressure_noise_psi")
            else:
                move = np.abs(run.volume[win] - run.volume[src]) / gal_per_ft
                sigma = fam.f("water.level_noise_ft")
            w.detail["consequential"] = bool(len(move) and move.max() > 3.0 * sigma * np.sqrt(2.0))


def bench_run(i: int, station: str = "PS-52") -> BenchRun:
    fam = family()
    r = rng(BENCH_SEED, "anomaly_bench", i)
    spec, truth = _spec(r, station)
    run = wt.simulate_zone(spec, fam, T0, T0 + DAYS * 86400.0, BENCH_SEED + i)
    sample = np.arange(0, len(run.t), 15)
    t15 = run.t[sample]
    gal_per_ft, _ = wt.tank_geometry(fam)
    pt = np.round(run.pressure[sample] + r.normal(0.0, fam.f("water.pressure_noise_psi"), len(sample)), 1)
    lt = np.round(
        run.volume[sample] / gal_per_ft + r.normal(0.0, fam.f("water.level_noise_ft"), len(sample)), 1
    )
    for w in truth:
        if w.family == "A8":
            w.device = f"PT-BENCH-{i:04d}" if w.kind.endswith("pressure") else f"LT-BENCH-{i:04d}"
    _inject(t15, pt, lt, truth)
    _observability(run, truth, gal_per_ft, fam)
    lt = np.maximum(lt, 0.0)
    keep = np.arange(len(t15)) % 2 == 0
    pump = []
    prev = None
    for k in range(len(run.t)):
        if run.pump_on[k] != prev:
            pump.append((float(run.t[k]), bool(run.pump_on[k])))
            prev = run.pump_on[k]
    breaker = [(T0, "closed")]
    if spec.grid_loss_t is not None:
        breaker.append((spec.grid_loss_t, "open"))
        if spec.grid_restore_t is not None:
            breaker.append((spec.grid_restore_t, "closed"))
    gens = sorted((float(t), s) for t, d, s in run.gen_events if d == spec.onsite_generator)
    alarm = fam.f("water.low_pressure_alarm_psi")
    low = run.pressure < alarm
    if low.any():
        idx = np.flatnonzero(low)
        cuts = np.flatnonzero(np.diff(idx) > 1)
        starts = np.r_[idx[0], idx[cuts + 1]]
        ends = np.r_[idx[cuts], idx[-1]]
        for a, b in zip(starts, ends, strict=True):
            truth.append(
                TruthWindow("low_pressure_episode", "A7", float(run.t[a]), float(run.t[b]) + 2 * 3600.0)
            )
    streams = StationStreams(
        station=f"BENCH-{i:04d}",
        pressure_id=f"PT-BENCH-{i:04d}",
        level_id=f"LT-BENCH-{i:04d}",
        p_t=t15,
        p=pt,
        l_t=t15[keep],
        level=lt[keep],
        pump=pump,
        breaker=breaker,
        generator=gens,
        meta={"twin_station": station},
    )
    return BenchRun(f"BENCH-{i:04d}", streams, truth)
