"""Precomputed what-if grid (W10, mode `what_if`, T0: no side effects) on the Helene truth model.

Four levers, three levels each (81 cells), each cell one deterministic `run_truth` with the scenario seed:

- track shift: every HURDAT2 fix moved east (+) or west (-) by the given km (a zonal shift; Helene ran north,
  so this is close to a cross-track shift);
- gust scale: the WMO gust factor (1.49) times the level;
- mutual-aid crews: personnel per 1,000 outages (13.3, project fact base) times the level;
- mutual-aid request: the request time moved earlier (-) or later (+) by the given hours (staging decision).
  The truth model sizes mutual aid on the outages known at the request, so an earlier request is also a
  smaller one:
  the -12 h cells show the cost of an under-sized early request, not the benefit of earlier arrival.

Headlines per cell: footprint customer-hours out over the scenario window, peak customers out, and hours from
the peak to 90 % restored (customers out at or below 10 % of the peak, the handoff proxy). The UI reads the
grid; nothing is simulated live (PLAN s6: W10 what-if precomputed). Synthetic outputs throughout.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from sgw.generator.config import Family, load_family, load_scenario, parse_utc
from sgw.generator.truth import Truth, run_truth

GRID_PATH = Path(__file__).with_name("helene_grid.json")
SCENARIO = "helene"
STEP_H = 0.25
LEVERS: dict[str, tuple[float, ...]] = {
    "track_shift_km": (-40.0, 0.0, 40.0),
    "gust_scale": (0.9, 1.0, 1.1),
    "mutual_aid_scale": (0.75, 1.0, 1.25),
    "mutual_aid_request_shift_h": (-12.0, 0.0, 12.0),
}
BASELINE = {
    "track_shift_km": 0.0,
    "gust_scale": 1.0,
    "mutual_aid_scale": 1.0,
    "mutual_aid_request_shift_h": 0.0,
}
KM_PER_DEG_LAT = 111.32


@dataclass(frozen=True)
class Cell:
    levers: dict[str, float]
    customer_hours: float
    peak_customers_out: int
    peak_utc: str
    hours_peak_to_90pct: float | None
    customers_affected: int


def _with(fam: Family, key: str, factor: float) -> Family:
    params = dict(fam.params)
    params[key] = replace(params[key], value=float(params[key].value) * factor)
    return Family(fam.name, fam.path, params)


def apply_levers(
    sc: Mapping[str, Any], fam: Family, levers: Mapping[str, float]
) -> tuple[dict[str, Any], Family]:
    unknown = set(levers) - set(LEVERS)
    if unknown:
        raise KeyError(f"unknown levers {sorted(unknown)}")
    s = copy.deepcopy(dict(sc))
    shift = float(levers.get("track_shift_km", 0.0))
    if shift:
        for row in s["storm"]["track"]:
            row[2] = float(row[2]) + shift / (KM_PER_DEG_LAT * math.cos(math.radians(float(row[1]))))
    req_h = float(levers.get("mutual_aid_request_shift_h", 0.0))
    if req_h:
        t = parse_utc(s["detail"]["mutual_aid_request_utc"]) + timedelta(hours=req_h)
        s["detail"]["mutual_aid_request_utc"] = t.strftime("%Y-%m-%dT%H:%M:%SZ")
    f = _with(fam, "wind.gust_factor", float(levers.get("gust_scale", 1.0)))
    f = _with(f, "restoration.personnel_per_1000_outages", float(levers.get("mutual_aid_scale", 1.0)))
    return s, f


def headline(truth: Truth) -> tuple[float, int, str, float | None, int]:
    customers = np.asarray(truth.net.sections["customers"], dtype=float)
    series = truth.out.astype(float) @ customers
    i_peak = int(np.argmax(series))
    peak = float(series[i_peak])
    after = np.nonzero(series[i_peak:] <= 0.1 * peak)[0]
    t90 = float(after[0]) * STEP_H if peak > 0 and after.size else None
    affected = int(customers[np.asarray(truth.out).any(axis=0)].sum())
    peak_utc = datetime.fromtimestamp(float(truth.times[i_peak]), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return float(series.sum() * STEP_H), int(round(peak)), peak_utc, t90, affected


def run_cell(
    levers: Mapping[str, float], sc: Mapping[str, Any] | None = None, fam: Family | None = None
) -> Cell:
    base_sc = sc if sc is not None else load_scenario(SCENARIO)
    base_fam = fam if fam is not None else load_family(base_sc["family"])
    s, f = apply_levers(base_sc, base_fam, levers)
    ch, peak, peak_utc, t90, affected = headline(run_truth(s, f))
    return Cell(dict(levers), round(ch, 1), peak, peak_utc, None if t90 is None else round(t90, 2), affected)


def cells() -> list[dict[str, float]]:
    keys = list(LEVERS)
    return [dict(zip(keys, combo, strict=True)) for combo in itertools.product(*(LEVERS[k] for k in keys))]


def build(path: Path = GRID_PATH, levels: Sequence[Mapping[str, float]] | None = None) -> dict[str, Any]:
    sc = load_scenario(SCENARIO)
    fam = load_family(sc["family"])
    rows = [run_cell(lv, sc, fam).__dict__ for lv in (levels or cells())]
    base = next(r for r in rows if r["levers"] == BASELINE)
    for r in rows:
        r["delta_customer_hours_pct"] = round(100.0 * (r["customer_hours"] / base["customer_hours"] - 1.0), 2)
    body = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    grid = {
        "scenario": SCENARIO,
        "seed": int(sc["seed"]),
        "mode": "what_if",
        "tier": "T0",
        "label": "synthetic",
        "levers": {k: list(v) for k, v in LEVERS.items()},
        "baseline": BASELINE,
        "headline": "customer_hours",
        "metric_notes": {
            "customer_hours": "sum over the scenario window of customers out x 0.25 h, footprint",
            "hours_peak_to_90pct": "hours from the footprint peak until customers out <= 10 % of the peak",
            "mutual_aid_request_shift_h": "mutual aid is sized on outages known at the time of the request, "
            "so an earlier request is smaller; read -12 h as an under-sized early request",
        },
        "cells": rows,
        "cells_sha256": hashlib.sha256(body.encode()).hexdigest(),
    }
    path.write_text(json.dumps(grid, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return grid


def load_grid(path: Path = GRID_PATH) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def lookup(levers: Mapping[str, float], grid: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The precomputed cell for exactly these lever levels (missing levers take the baseline)."""
    g = grid if grid is not None else load_grid()
    want = {**BASELINE, **{k: float(v) for k, v in levers.items()}}
    for k, v in want.items():
        if k not in LEVERS or v not in LEVERS[k]:
            raise KeyError(f"{k}={v} is not a precomputed level (have {LEVERS.get(k)})")
    for c in g["cells"]:
        if c["levers"] == want:
            out: dict[str, Any] = c
            return out
    raise KeyError(f"no cell for {want}")
