"""Verification of the reduction: reduced twin vs the WNTR precompute grid (drain-to-floor minutes at the
critical service node). Both read the same networks, so this verifies the reduction and its numerics, not that
the networks resemble a real zone; the structural band (Hazen-Williams C and node elevations perturbed) shows
how far the drain time moves when the assumed network does, and re-verifies the reduction on each perturbed
network.

Variants compared with WNTR (EPANET 2.2, PDD, looped network, flat hospital pattern):
- `twin_looped`: production reduced model (one looped steady solve, homogeneous head-loss coefficients).
- `twin_tree`: loops dropped (spanning-tree head loss), the cruder reduction.
- `station_sensor_floor`: the WP-06 reference basis, floor read at the pump-station sensor (no head loss, no
  elevation of the service nodes); shows what checking the floor at the station instead of at the service
  connection does to the consequence time.
No parameter is fitted to the grid: the reduced models read only `networks.json`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from sgw.models.water.network import path_model
from sgw.models.water.params import ARTEFACT_DIR
from sgw.models.water.twin import GRID_DAY_UTC, ZoneTwin, load_networks

TOLERANCE_MIN = 60.0


def _stats(err: np.ndarray) -> dict[str, float | int]:
    a = np.abs(err)
    return {
        "n": int(len(err)),
        "median_abs_min": round(float(np.median(a)), 3),
        "p90_abs_min": round(float(np.percentile(a, 90)), 3),
        "max_abs_min": round(float(a.max()), 3),
        "mean_signed_min": round(float(err.mean()), 3),
    }


def compare(
    grid_path: Path = ARTEFACT_DIR / "wntr_drain_grid.json",
    networks_path: Path = ARTEFACT_DIR / "networks.json",
) -> dict[str, Any]:
    grid = json.loads(grid_path.read_text(encoding="utf-8"))
    nets, meta = load_networks(networks_path)
    base = GRID_DAY_UTC.timestamp()
    report: dict[str, Any] = {
        "label": "synthetic",
        "kind": "verification of the reduced model against WNTR on the same networks; not a validation",
        "reference": "WNTR EpanetSimulator 2.2, PDD, host precompute",
        "wntr_runs": grid["runs"],
        "networks_sha256": grid["networks_sha256"],
        "tolerance_median_abs_min": TOLERANCE_MIN,
        "floors": {},
    }
    for floor in (25.0, 20.0):
        errs: dict[str, list[float]] = {"twin_looped": [], "twin_tree": [], "station_sensor_floor": []}
        per_station: dict[str, list[float]] = {}
        for st in sorted(nets):
            rows = [r for r in grid["rows"] if r["station"] == st and r[f"t_floor_{floor:g}_min"] is not None]
            if not rows:
                continue
            t0 = np.array([base + r["loss_minute_utc"] * 60.0 for r in rows])
            mult = np.array([r["leak"] * r["demand_scale"] for r in rows])
            ref = np.array([r[f"t_floor_{floor:g}_min"] for r in rows])
            looped = ZoneTwin(nets[st], meta["diurnal"])
            tree = ZoneTwin(nets[st], meta["diurnal"])
            tree.pm = path_model(nets[st], looped=False)
            e_loop = looped.drain_to_floor_min(t0, mult, floor) - ref
            e_tree = tree.drain_to_floor_min(t0, mult, floor) - ref
            sensor = np.array([r[f"t_sensor_{floor:g}_min"] for r in rows], dtype=float) - ref
            errs["twin_looped"] += e_loop.tolist()
            errs["twin_tree"] += e_tree.tolist()
            errs["station_sensor_floor"] += sensor.tolist()
            per_station[st] = e_loop.tolist()
        report["floors"][f"{floor:g}_psi"] = {
            "variants": {k: _stats(np.asarray(v)) for k, v in errs.items()},
            "twin_looped_by_station": {k: _stats(np.asarray(v)) for k, v in per_station.items()},
        }
    band_path = grid_path.with_name("wntr_band_grid.json")
    if band_path.is_file():
        report["structural_band"] = structural_band(band_path, grid, nets, meta["diurnal"])
    main = report["floors"]["25_psi"]["variants"]["twin_looped"]
    report["passed"] = bool(main["median_abs_min"] <= TOLERANCE_MIN)
    return report


def structural_band(
    band_path: Path, grid: dict[str, Any], nets: dict[str, Any], diurnal: list[float]
) -> dict[str, Any]:
    band = json.loads(band_path.read_text(encoding="utf-8"))
    base = GRID_DAY_UTC.timestamp()
    nominal = {
        (r["station"], r["loss_minute_utc"]): r["t_floor_25_min"]
        for r in grid["rows"]
        if r["leak"] == 1.3 and r["demand_scale"] == 1.0
    }
    out: dict[str, Any] = {"floor_psi": 25.0, "leak": 1.3, "stations": {}}
    errs: list[float] = []
    for st, draws in band["networks"].items():
        rows = [r for r in band["rows"] if r["station"] == st and r["t_floor_25_min"] is not None]
        deltas = []
        for b in draws:
            mine = [r for r in rows if r["draw"] == b["band"]["draw"]]
            twin = ZoneTwin(b, diurnal)
            t0 = np.array([base + r["loss_minute_utc"] * 60.0 for r in mine])
            ref = np.array([r["t_floor_25_min"] for r in mine])
            errs += (twin.drain_to_floor_min(t0, 1.3, 25.0) - ref).tolist()
            deltas += [r["t_floor_25_min"] - nominal[(st, r["loss_minute_utc"])] for r in mine]
        d = np.asarray(deltas)
        out["stations"][st] = {
            "runs": len(rows),
            "drain_delta_vs_nominal_min": {
                "min": round(float(d.min()), 1),
                "p10": round(float(np.percentile(d, 10)), 1),
                "median": round(float(np.median(d)), 1),
                "p90": round(float(np.percentile(d, 90)), 1),
                "max": round(float(d.max()), 1),
            },
        }
    out["twin_vs_wntr_on_band_networks"] = _stats(np.asarray(errs))
    return out
