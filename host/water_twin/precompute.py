"""WNTR host precompute (spike S-AI-6): drain-to-floor times of every zone network under EPANET 2.2 with
pressure-dependent demand, over a grid of power-loss clock times, leak multipliers and demand scales.

Host only (WNTR is in the `host` dependency group); run it through `make water-precompute`:

    uv run --group host python host/water_twin/precompute.py

Writes `data/artefacts/water_twin/networks.json` and `wntr_drain_grid.json`. The reduced model is validated
against the grid by `uv run sgw water validate` (no WNTR needed there).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import wntr

from sgw.models.water.network import FT, GPM, PSI_PER_FT, band_networks
from sgw.models.water.params import ARTEFACT_DIR, twin_params
from sgw.models.water.twin import (
    EDT_OFFSET_H,
    GRID_DEMAND_SCALES,
    GRID_LEAKS,
    GRID_LOSS_MINUTES,
    load_networks,
    write_networks,
)

DURATION_H = 14
RETRY_DURATIONS_H = (14.0, 10.0, 7.0, 5.0, 3.5, 2.5)
STEP_S = 60


def build_wn(
    net: dict[str, Any],
    diurnal: list[float],
    total_mult: float,
    start_local_s: int,
    duration_h: float = DURATION_H,
) -> Any:
    wn = wntr.network.WaterNetworkModel()
    wn.add_pattern("DIURNAL", list(diurnal))
    wn.add_pattern("FLAT", [1.0])
    q_avg = net["avg_demand_gpm"] * GPM * total_mult
    for n in net["nodes"]:
        base = n["demand_share"] * q_avg
        wn.add_junction(
            n["id"],
            base_demand=base,
            demand_pattern=("FLAT" if n.get("pattern") == "flat" else "DIURNAL") if base > 0 else None,
            elevation=n["elevation_ft"] * FT,
        )
    wn.add_tank(
        net["tank"],
        elevation=net["tank_bottom_elevation_ft"] * FT,
        init_level=net["tank_max_level_ft"] * FT,
        min_level=0.0,
        max_level=net["tank_max_level_ft"] * FT,
        diameter=net["tank_diameter_ft"] * FT,
    )
    tp = net["tank_pipe"]
    wn.add_pipe(
        f"P-{net['tank']}",
        net["tank"],
        net["sensor_node"],
        length=tp["length_ft"] * FT,
        diameter=tp["diameter_in"] * 0.0254,
        roughness=tp["c"],
    )
    clearwell = f"RES-{net['station']}-CLEARWELL"
    wn.add_reservoir(clearwell, base_head=net["tank_bottom_elevation_ft"] * FT)
    head = (net["tank_max_level_ft"] + 40.0) * FT
    wn.add_curve(f"PC-{net['station']}", "HEAD", [(net["pump_capacity_gpm"] * GPM, head)])
    wn.add_pump(
        f"PMP-{net['station']}-1",
        clearwell,
        net["sensor_node"],
        pump_type="HEAD",
        pump_parameter=f"PC-{net['station']}",
        initial_status="CLOSED",
    )
    for p in net["pipes"]:
        wn.add_pipe(
            p["id"],
            p["from"],
            p["to"],
            length=p["length_ft"] * FT,
            diameter=p["diameter_in"] * 0.0254,
            roughness=p["c"],
        )
    o = wn.options
    o.time.duration = int(duration_h * 3600)
    o.time.hydraulic_timestep = STEP_S
    o.time.report_timestep = STEP_S
    o.time.pattern_timestep = 3600
    o.time.pattern_start = start_local_s
    o.hydraulic.demand_model = "PDD"
    o.hydraulic.minimum_pressure = 5.0 / PSI_PER_FT * FT
    o.hydraulic.required_pressure = 20.0 / PSI_PER_FT * FT
    o.hydraulic.pressure_exponent = 0.5
    return wn


def first_below(t_min: np.ndarray, psi: np.ndarray, floor: float) -> float | None:
    idx = np.flatnonzero(psi < floor)
    if not len(idx):
        return None
    i = int(idx[0])
    if i == 0:
        return 0.0
    p0, p1 = psi[i - 1], psi[i]
    return float(t_min[i - 1] + (p0 - floor) / (p0 - p1) * (t_min[i] - t_min[i - 1]))


def run_one(
    net: dict[str, Any], diurnal: list[float], mult: float, loss_min: int, workdir: Path
) -> dict[str, Any]:
    """EPANET is causal, so when PDD fails to converge late in a drain (tank near empty, far nodes at
    negative pressure) the run is repeated with a shorter duration; results before the cut are the same. A
    floor not crossed within a shortened run is reported as None with `duration_h`."""
    start_local_s = int(((loss_min / 60.0 + EDT_OFFSET_H) % 24) * 3600)
    last: Exception | None = None
    for duration in RETRY_DURATIONS_H:
        wn = build_wn(net, diurnal, mult, start_local_s, duration)
        draw = net.get("band", {}).get("draw", "n")
        prefix = f"{net['station']}-{draw}-{loss_min}-{mult:.3f}-{duration:g}"
        try:
            res = wntr.sim.EpanetSimulator(wn).run_sim(file_prefix=str(workdir / prefix))
            break
        except ValueError as exc:
            last = exc
    else:
        raise ValueError(f"no converged EPANET run down to {RETRY_DURATIONS_H[-1]} h: {last}")
    pressure = res.node["pressure"]
    t_min = pressure.index.to_numpy(dtype=float) / 60.0
    svc = [n["id"] for n in net["nodes"] if n["role"] != "station"]
    p_svc = pressure[svc].to_numpy() / FT * PSI_PER_FT
    crit = p_svc.min(axis=1)
    sensor = pressure[net["sensor_node"]].to_numpy() / FT * PSI_PER_FT
    out: dict[str, Any] = {"duration_h": duration}
    for floor in (25.0, 20.0):
        t = first_below(t_min, crit, floor)
        k = int(np.searchsorted(t_min, t)) if t is not None else None
        out[f"t_floor_{floor:g}_min"] = None if t is None else round(t, 2)
        out[f"critical_node_{floor:g}"] = (
            None if k is None else svc[int(np.argmin(p_svc[min(k, len(t_min) - 1)]))]
        )
        out[f"t_sensor_{floor:g}_min"] = (
            None if (s := first_below(t_min, sensor, floor)) is None else round(s, 2)
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ARTEFACT_DIR)
    ap.add_argument("--quick", action="store_true", help="one station, 6 loss times (smoke run)")
    args = ap.parse_args(argv)
    write_networks(args.out / "networks.json")
    nets, meta = load_networks(args.out / "networks.json")
    diurnal = meta["diurnal"]
    stations = sorted(nets)[:1] if args.quick else sorted(nets)
    losses = GRID_LOSS_MINUTES[::8] if args.quick else GRID_LOSS_MINUTES
    rows = []
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="wntr-") as tmp:
        for st in stations:
            for loss in losses:
                for leak in GRID_LEAKS:
                    for scale in GRID_DEMAND_SCALES:
                        row = {"station": st, "loss_minute_utc": loss, "leak": leak, "demand_scale": scale}
                        try:
                            row.update(run_one(nets[st], diurnal, leak * scale, loss, Path(tmp)))
                        except ValueError as exc:
                            row.update(
                                {"t_floor_25_min": None, "t_floor_20_min": None, "error": f"epanet: {exc}"}
                            )
                        rows.append(row)
        band_rows = []
        band_nets = {st: band_networks(nets[st], twin_params()) for st in stations}
        for st in stations:
            for b in band_nets[st]:
                for loss in losses[::4]:
                    row = {"station": st, "draw": b["band"]["draw"], "loss_minute_utc": loss, "leak": 1.3}
                    row["demand_scale"] = 1.0
                    try:
                        row.update(run_one(b, diurnal, 1.3, loss, Path(tmp)))
                    except ValueError as exc:
                        row.update(
                            {"t_floor_25_min": None, "t_floor_20_min": None, "error": f"epanet: {exc}"}
                        )
                    band_rows.append(row)
    elapsed = time.perf_counter() - t0
    (args.out / "wntr_band_grid.json").write_text(
        json.dumps({"label": "synthetic", "networks": band_nets, "rows": band_rows}, indent=1, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    sha = hashlib.sha256((args.out / "networks.json").read_bytes()).hexdigest()
    doc = {
        "label": "synthetic",
        "model_id": "water_twin.wntr_epanet22_pdd",
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": "make water-precompute",
        "wntr_version": wntr.__version__,
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.machine()}",
        "networks_sha256": sha,
        "settings": {
            "simulator": "EpanetSimulator 2.2",
            "demand_model": "PDD (Wagner, p_min 5 psi, p_req 20 psi, exponent 0.5)",
            "hydraulic_step_s": STEP_S,
            "duration_h": DURATION_H,
            "initial_tank": "full, pump closed at t=0 (power loss)",
            "loss_epoch_day": "2024-09-27 UTC, minutes after 00:00",
        },
        "runs": len(rows),
        "elapsed_s": round(elapsed, 1),
        "rows": rows,
    }
    (args.out / "wntr_drain_grid.json").write_text(
        json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wntr precompute: {len(rows)} runs in {elapsed:.1f} s -> {args.out / 'wntr_drain_grid.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
