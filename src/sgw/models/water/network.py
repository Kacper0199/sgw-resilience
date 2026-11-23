"""Zone distribution networks (one per pump station) and their reduced path model.

Each zone: a standpipe tank beside the pump station node (the discharge-pressure sensor), a trunk main, branch
laterals, two loop-closing cross connections and lumped service nodes. The layout is seeded per station and
stored in `data/artefacts/water_twin/networks.json`; WNTR (host precompute) and the reduced model read the
same file, so the WNTR comparison checks the reduction, not two different networks.

Reduced model: every service node follows one demand pattern, so all nodal demands scale with the zone total
Q. Hazen-Williams head loss is homogeneous (h = r q^1.852), so if the looped steady state at a reference total
Q_ref has flows q_p, the state at Q has flows q_p Q/Q_ref and head losses scaled by (Q/Q_ref)^1.852: one
looped solve gives an exact coefficient K_n with head loss tank -> n = K_n Q^1.852 at every Q (EPANET 2.2 SI
coefficient). The node pressure is `0.433 * (H_tank - K_n Q^1.852 - z_n)` psi with heads in ft. The hospital
node runs a flat 24-h pattern (WNTR models it), so the zone is not exactly homogeneous: the twin keeps the
mass balance exact (total demand from both patterns) and uses the homogeneous K_n for head loss; the WNTR
grid measures that reduction. The spanning-tree version (loops dropped) is kept for comparison: it overstates
head loss and so floors early.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from sgw.generator.config import Family, rng
from sgw.models.water.params import TwinParams

PSI_PER_FT = 0.433
FT = 0.3048
INCH = 0.0254
GPM = 6.30901964e-05
HW_SI = 10.667
HW_Q_EXP = 1.852
HW_D_EXP = 4.871
SENSOR_ELEVATION_FT = 420.0
NETWORK_SEED = 4417
ZONE_CODES = {"PS-17": "CF", "PS-23": "LS", "PS-38": "CL", "PS-52": "DW"}


QUANTUM_DECIMALS = 6


def quantise(obj: Any, decimals: int = QUANTUM_DECIMALS) -> Any:
    """Round every float to `decimals` places before serialisation, so a network built on any OS serialises to
    the same JSON (the draws are uniform-only, which numpy produces bit-identically; the rounding guards the
    remaining arithmetic)."""
    if isinstance(obj, float):
        return round(obj, decimals)
    if isinstance(obj, dict):
        return {k: quantise(v, decimals) for k, v in obj.items()}
    if isinstance(obj, list):
        return [quantise(v, decimals) for v in obj]
    return obj


def same_within(a: Any, b: Any, tol: float = 10.0**-QUANTUM_DECIMALS) -> bool:
    if isinstance(a, float | int) and isinstance(b, float | int) and not isinstance(a, bool):
        return abs(float(a) - float(b)) <= tol
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same_within(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same_within(x, y, tol) for x, y in zip(a, b, strict=True))
    return bool(a == b)


def hw_resistance_si(length_ft: float, diameter_in: float, c: float) -> float:
    """EPANET 2.2 Hazen-Williams resistance r in h_L[m] = r * q[m3/s]^1.852."""
    return float(HW_SI * c**-HW_Q_EXP * (diameter_in * INCH) ** -HW_D_EXP * (length_ft * FT))


def build_zone_network(
    station: str, named: dict[str, Any], fam: Family, tp: TwinParams, hospital: dict[str, Any] | None
) -> dict[str, Any]:
    ps = named["pump_stations"][station]
    code = ZONE_CODES[station]
    r = rng(NETWORK_SEED, "water_network", station)
    n_service = int(tp["network.service_nodes"])
    lo, hi = tp["network.elevation_spread_ft"]
    c = float(tp["network.hazen_williams_c"])
    length_lo, length_hi = tp["network.pipe_length_ft"]
    station_node = f"J-{code}-STATION"
    nodes: list[dict[str, Any]] = [
        {"id": station_node, "elevation_ft": SENSOR_ELEVATION_FT, "demand_share": 0.0, "role": "station"}
    ]
    pipes: list[dict[str, Any]] = []

    def pipe(a: str, b: str, d_in: float, tree: bool, length: float | None = None) -> None:
        pipes.append(
            {
                "id": f"P-{code}-{len(pipes) + 1:02d}",
                "from": a,
                "to": b,
                "length_ft": round(
                    float(length if length is not None else r.uniform(length_lo, length_hi)), 1
                ),
                "diameter_in": float(d_in),
                "c": c,
                "tree": tree,
            }
        )

    trunk_d = list(tp["network.trunk_diameter_in"])
    prev = station_node
    service: list[str] = []
    for k, d in enumerate(trunk_d, start=1):
        nid = f"J-{code}-{k:02d}"
        nodes.append({"id": nid, "elevation_ft": None, "demand_share": None, "role": "service"})
        pipe(prev, nid, d, True)
        service.append(nid)
        prev = nid
    branch_d = list(tp["network.branch_diameter_in"])
    depth = {station_node: 0, **{s: i + 1 for i, s in enumerate(service)}}
    while len(service) < n_service:
        k = len(service) + 1
        parent = (
            service[int(r.integers(0, len(service)))]
            if r.uniform() < 0.4
            else service[: len(trunk_d)][int(r.integers(0, len(trunk_d)))]
        )
        nid = f"J-{code}-{k:02d}"
        nodes.append({"id": nid, "elevation_ft": None, "demand_share": None, "role": "service"})
        d = branch_d[min(len(branch_d) - 1, max(0, 2 - depth[parent] // 2))]
        pipe(parent, nid, d, True)
        depth[nid] = depth[parent] + 1
        service.append(nid)
    elevations = r.uniform(lo, hi, len(service))
    weights = [0.5 + float(u) for u in r.uniform(size=len(service))]
    total_w = math.fsum(weights)
    shares = [w / total_w for w in weights]
    for node, z, s in zip(nodes[1:], elevations, shares, strict=True):
        node["elevation_ft"] = round(SENSOR_ELEVATION_FT + float(z), 2)
        node["demand_share"] = s
    if hospital is not None and hospital["zone"] == ps["zone"]:
        h = next(n for n in nodes if n["id"] == f"J-{code}-{len(trunk_d) + 2:02d}")
        new_id = f"J-{code}-{hospital['id'].split('-')[-1]}"
        for p in pipes:
            p["from"] = new_id if p["from"] == h["id"] else p["from"]
            p["to"] = new_id if p["to"] == h["id"] else p["to"]
        h["id"] = new_id
        h["role"] = "hospital"
        h["pattern"] = str(tp["network.hospital_pattern"])
        h["asset_id"] = hospital["id"]
        h["elevation_ft"] = round(
            SENSOR_ELEVATION_FT + fam.f("water.hospital_pressure_offset_psi") / PSI_PER_FT, 2
        )
        share = float(tp["network.hospital_demand_share"])
        others = [n for n in nodes[1:] if n is not h]
        total = math.fsum(n["demand_share"] for n in others)
        for n in others:
            n["demand_share"] = n["demand_share"] / total * (1.0 - share)
        h["demand_share"] = share
    ids = [n["id"] for n in nodes[1:]]
    leaves = [i for i in ids if sum(1 for p in pipes if p["from"] == i) == 0]
    loop_d = float(tp["network.loop_diameter_in"])
    made = 0
    for a_idx in r.permutation(len(leaves)):
        if made == 2:
            break
        a = leaves[int(a_idx)]
        b = ids[int(r.integers(0, len(ids)))]
        linked = any({p["from"], p["to"]} == {a, b} for p in pipes)
        if b != a and not linked:
            pipe(a, b, loop_d, False)
            made += 1
    tank_bottom = SENSOR_ELEVATION_FT + fam.f("water.empty_residual_psi") / PSI_PER_FT
    net: dict[str, Any] = quantise(
        {
            "station": station,
            "zone": ps["zone"],
            "tank": ps["tank"],
            "sensor_node": station_node,
            "tank_pipe": {"length_ft": 60.0, "diameter_in": 24.0, "c": c},
            "tank_bottom_elevation_ft": round(tank_bottom, 3),
            "tank_diameter_ft": fam.f("water.standpipe_diameter_ft"),
            "tank_max_level_ft": fam.f("water.level_full_ft"),
            "avg_demand_gpm": fam.f("water.avg_demand_mgd") * 1e6 / 1440.0,
            "pump_capacity_gpm": fam.f("water.pump_capacity_mgd") * 1e6 / 1440.0,
            "nodes": nodes,
            "pipes": pipes,
        }
    )
    return net


def band_networks(net: dict[str, Any], tp: TwinParams) -> list[dict[str, Any]]:
    """Structural band: copies of a zone with Hazen-Williams C spread over the labelled range and node
    elevations perturbed by a seeded normal error (one draw per C value)."""
    import copy

    lo, hi = tp["band.hazen_williams_c"]
    draws = int(tp["band.draws"])
    sigma = tp.f("band.elevation_sigma_ft")
    out = []
    for k, c in enumerate(np.linspace(lo, hi, draws)):
        r = rng(NETWORK_SEED, "water_band", net["station"], k)
        b = copy.deepcopy(net)
        b["band"] = {"draw": k, "hazen_williams_c": float(c), "elevation_sigma_ft": sigma}
        for p in b["pipes"]:
            p["c"] = float(c)
        b["tank_pipe"]["c"] = float(c)
        for n in b["nodes"]:
            if n["role"] != "station":
                n["elevation_ft"] = round(
                    n["elevation_ft"] + float(r.uniform(-1.0, 1.0)) * sigma * math.sqrt(3.0), 2
                )
        out.append(quantise(b))
    return out


@dataclass(frozen=True)
class PathModel:
    """Reduced pressure model of one zone: node pressure = a_n + 0.433 * level - b_n * Q^1.852 (psi, gpm)."""

    station: str
    node_ids: tuple[str, ...]
    static_psi: np.ndarray
    loss_psi_per_gpm185: np.ndarray
    sensor_static_psi: float
    sensor_loss: float
    gal_per_ft: float
    max_level_ft: float
    critical_role: dict[str, str]

    def node_psi(self, level_ft: np.ndarray, q_gpm: np.ndarray) -> np.ndarray:
        level = np.asarray(level_ft, dtype=float)[..., None]
        q = np.maximum(np.asarray(q_gpm, dtype=float), 0.0)[..., None] ** HW_Q_EXP
        return np.asarray(self.static_psi + PSI_PER_FT * level - self.loss_psi_per_gpm185 * q)

    def critical_psi(self, level_ft: np.ndarray, q_gpm: np.ndarray) -> np.ndarray:
        return np.asarray(self.node_psi(level_ft, q_gpm).min(axis=-1))

    def sensor_psi(self, level_ft: np.ndarray, q_gpm: np.ndarray) -> np.ndarray:
        q = np.maximum(np.asarray(q_gpm, dtype=float), 0.0) ** HW_Q_EXP
        return np.asarray(self.sensor_static_psi + PSI_PER_FT * np.asarray(level_ft) - self.sensor_loss * q)


Q_REF_SI = 0.1


def looped_head_loss_si(net: dict[str, Any], tree_k: dict[str, float]) -> dict[str, float]:
    """K_n (SI) from one steady looped solve at Q_REF_SI (tank head fixed), started from the tree heads."""
    from scipy.optimize import root

    ids = [n["id"] for n in net["nodes"]]
    index = {nid: i for i, nid in enumerate(ids)}
    demand = np.array([n["demand_share"] * Q_REF_SI for n in net["nodes"]])
    tp = net["tank_pipe"]
    links = [(-1, index[net["sensor_node"]], hw_resistance_si(tp["length_ft"], tp["diameter_in"], tp["c"]))]
    links += [
        (index[p["from"]], index[p["to"]], hw_resistance_si(p["length_ft"], p["diameter_in"], p["c"]))
        for p in net["pipes"]
    ]
    h_tank = 0.0

    def flows(h: np.ndarray) -> np.ndarray:
        ha = np.array([h_tank if a < 0 else h[a] for a, _, _ in links])
        hb = np.array([h[b] for _, b, _ in links])
        r = np.array([lr for _, _, lr in links])
        dh = ha - hb
        return np.asarray(np.sign(dh) * (np.abs(dh) / r) ** (1.0 / HW_Q_EXP))

    def balance(h: np.ndarray) -> np.ndarray:
        q = flows(h)
        net_in = np.zeros(len(ids))
        for (a, b, _), qp in zip(links, q, strict=True):
            net_in[b] += qp
            if a >= 0:
                net_in[a] -= qp
        return np.asarray(net_in - demand)

    h0 = np.array([-tree_k[nid] * Q_REF_SI**HW_Q_EXP for nid in ids])
    sol = root(balance, h0, method="hybr", tol=1e-12)
    if not sol.success or np.max(np.abs(balance(sol.x))) > 1e-9:
        raise RuntimeError(f"{net['station']}: looped steady solve did not converge ({sol.message})")
    return {nid: float(-sol.x[i] / Q_REF_SI**HW_Q_EXP) for i, nid in enumerate(ids)}


def path_model(net: dict[str, Any], looped: bool = True) -> PathModel:
    nodes = {n["id"]: n for n in net["nodes"]}
    children: dict[str, list[tuple[str, dict[str, Any]]]] = {k: [] for k in nodes}
    for p in net["pipes"]:
        if p["tree"]:
            children[p["from"]].append((p["to"], p))
    root = net["sensor_node"]

    def subtree_share(nid: str) -> float:
        return float(nodes[nid]["demand_share"]) + sum(subtree_share(c) for c, _ in children[nid])

    gpm_si = GPM**HW_Q_EXP
    k_si: dict[str, float] = {root: 0.0}
    stack = [root]
    while stack:
        nid = stack.pop()
        for child, p in children[nid]:
            r_si = hw_resistance_si(p["length_ft"], p["diameter_in"], p["c"])
            k_si[child] = k_si[nid] + r_si * subtree_share(child) ** HW_Q_EXP
            stack.append(child)
    tp = net["tank_pipe"]
    k_tank = hw_resistance_si(tp["length_ft"], tp["diameter_in"], tp["c"])
    k_total = {nid: k_tank + k for nid, k in k_si.items()}
    if looped:
        k_total = looped_head_loss_si(net, k_total)
    svc = [n for n in net["nodes"] if n["role"] != "station"]
    ids = tuple(n["id"] for n in svc)
    to_psi = PSI_PER_FT / FT
    static = np.array([PSI_PER_FT * (net["tank_bottom_elevation_ft"] - n["elevation_ft"]) for n in svc])
    loss = np.array([k_total[n["id"]] * gpm_si * to_psi for n in svc])
    d = net["tank_diameter_ft"]
    roles = {n["id"]: n["role"] for n in svc}
    return PathModel(
        station=net["station"],
        node_ids=ids,
        static_psi=static,
        loss_psi_per_gpm185=loss,
        sensor_static_psi=PSI_PER_FT * (net["tank_bottom_elevation_ft"] - nodes[root]["elevation_ft"]),
        sensor_loss=k_total[root] * gpm_si * to_psi,
        gal_per_ft=float(np.pi * d * d / 4.0 * 7.48052),
        max_level_ft=float(net["tank_max_level_ft"]),
        critical_role=roles,
    )
