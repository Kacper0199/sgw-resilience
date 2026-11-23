"""Reduced zone twin: tank drain to the service-pressure floor at the critical service node.

State per zone: tank level L (ft). With the pump unpowered, dL/dt = -Q(t) / A, Q(t) = Q_avg * diurnal(local
hour) * m, where m is the storm leak multiplier times the demand scale. Pressure at service node n is the path
model of `network.py`; the floor is crossed when the lowest service-node pressure falls below the state floor.
Explicit 1-min step (the drain is smooth and slow: about 0.5 ft/min at peak, far inside stability), crossing
time interpolated linearly inside the step. Validity: one tank per zone, pump off for the whole drain, demand
fully served (Wagner pressure-dependent demand only bites below the 20 psi required pressure, which is at or
below every floor used here), no inter-zone transfer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from sgw.models.water.network import PathModel, build_zone_network, path_model
from sgw.models.water.params import ARTEFACT_DIR, family, scenario, twin_params

EDT_OFFSET_H = -4
GRID_DAY_UTC = datetime(2024, 9, 27, tzinfo=UTC)
GRID_LOSS_MINUTES = list(range(0, 24 * 60, 30))
GRID_LEAKS = [1.1, 1.3, 1.6, 2.0]
GRID_DEMAND_SCALES = [0.9, 1.0, 1.1]
STATIONS = ("PS-17", "PS-23", "PS-38", "PS-52")
STEP_MIN = 1.0


def build_networks() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    sc = scenario()
    fam = family()
    tp = twin_params()
    nets = {
        st: build_zone_network(st, sc["named"], fam, tp, sc["named"]["hospital"])
        for st in sc["named"]["pump_stations"]
    }
    meta = {
        "label": "synthetic",
        "version": tp.version,
        "diurnal": [float(x) for x in fam.arr("water.diurnal_factor")],
        "diurnal_clock": "local EDT hour 0-23 (UTC-4)",
        "source": "sgw.models.water.network.build_zone_network, family A plant data, water_twin.yaml layout",
    }
    return nets, meta


def write_networks(path: Path = ARTEFACT_DIR / "networks.json") -> None:
    nets, meta = build_networks()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"meta": meta, "networks": nets}, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_networks(
    path: Path = ARTEFACT_DIR / "networks.json",
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["networks"], data["meta"]


class ZoneTwin:
    def __init__(self, net: dict[str, Any], diurnal: list[float]) -> None:
        self.net = net
        self.pm: PathModel = path_model(net)
        self.diurnal = np.asarray(diurnal, dtype=float)
        self.avg_gpm = float(net["avg_demand_gpm"])
        flat = sum(n["demand_share"] for n in net["nodes"] if n.get("pattern") == "flat")
        self.hourly = (1.0 - flat) * self.diurnal + flat
        self.pump_gpm = float(net["pump_capacity_gpm"])

    def demand_gpm(self, t_epoch: np.ndarray, mult: np.ndarray | float) -> np.ndarray:
        hour = ((np.asarray(t_epoch, dtype=float) / 3600.0 + EDT_OFFSET_H) % 24).astype(int)
        return np.asarray(self.avg_gpm * self.hourly[hour] * mult)

    def drain_to_floor_min(
        self,
        t0_epoch: np.ndarray | float,
        mult: np.ndarray | float,
        floor_psi: float,
        level0_ft: np.ndarray | float | None = None,
        horizon_min: float = 24 * 60,
        nodes_out: list[np.ndarray] | None = None,
    ) -> np.ndarray:
        """Minutes from power loss at `t0_epoch` until the critical service node falls below `floor_psi` (NaN
        when not within the horizon); vectorised over `t0_epoch`, `mult` and `level0_ft`. When `nodes_out` is
        a list, the index of the critical node at each crossing (-1 when none) is appended to it."""
        t0, m, lvl = np.broadcast_arrays(
            np.asarray(t0_epoch, dtype=float),
            np.asarray(mult, dtype=float),
            np.asarray(self.pm.max_level_ft if level0_ft is None else level0_ft, dtype=float),
        )
        level = np.minimum(lvl.astype(float).copy(), self.pm.max_level_ft)
        out = np.full(level.shape, np.nan)
        node = np.full(level.shape, -1)
        prev_p = None
        for k in range(int(horizon_min / STEP_MIN) + 1):
            t = t0 + k * STEP_MIN * 60.0
            q = self.demand_gpm(t, m)
            p = self.pm.critical_psi(level, q)
            hit = np.isnan(out) & (p < floor_psi)
            if hit.any():
                node[hit] = np.argmin(self.pm.node_psi(level, q), axis=-1)[hit]
                if prev_p is None:
                    out[hit] = 0.0
                else:
                    frac = (prev_p[hit] - floor_psi) / np.maximum(prev_p[hit] - p[hit], 1e-12)
                    out[hit] = (k - 1 + frac) * STEP_MIN
            if not np.isnan(out).any():
                break
            prev_p = p
            level = np.maximum(level - q * STEP_MIN / self.pm.gal_per_ft, 0.0)
        if nodes_out is not None:
            nodes_out.append(node)
        return out


def zone_twins(path: Path = ARTEFACT_DIR / "networks.json") -> dict[str, ZoneTwin]:
    nets, meta = load_networks(path)
    return {st: ZoneTwin(net, meta["diurnal"]) for st, net in nets.items()}
