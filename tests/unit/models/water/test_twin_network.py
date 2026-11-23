from __future__ import annotations

import json

import numpy as np
import pytest

from sgw.models.water import network as netmod
from sgw.models.water.params import ARTEFACT_DIR
from sgw.models.water.twin import STATIONS, ZoneTwin, build_networks, load_networks, zone_twins

T0 = 1727409600.0


@pytest.fixture(scope="module")
def stored() -> tuple[dict, dict]:
    return load_networks()


def test_committed_networks_are_the_seeded_layout(stored: tuple[dict, dict]) -> None:
    nets, meta = build_networks()
    assert netmod.same_within(json.loads(json.dumps(nets)), stored[0])
    assert netmod.same_within(meta["diurnal"], stored[1]["diurnal"])


def test_layout_uses_only_os_stable_draws_and_is_quantised() -> None:
    import inspect

    src = inspect.getsource(netmod)
    for draw in ("dirichlet", "r.normal", "gamma(", "standard_normal"):
        assert draw not in src
    nets, _ = build_networks()
    for net in nets.values():
        for n in net["nodes"]:
            assert n["demand_share"] == round(n["demand_share"], netmod.QUANTUM_DECIMALS)
    assert not netmod.same_within(1.0, 1.0 + 2e-6)


def test_every_zone_is_connected_and_ids_unique(stored: tuple[dict, dict]) -> None:
    for st in STATIONS:
        net = stored[0][st]
        ids = [n["id"] for n in net["nodes"]]
        assert len(ids) == len(set(ids))
        tree = [p for p in net["pipes"] if p["tree"]]
        assert len(tree) == len(ids) - 1
        reach = {net["sensor_node"]}
        for _ in ids:
            reach |= {p["to"] for p in tree if p["from"] in reach}
        assert reach == set(ids)
        assert sum(n["demand_share"] for n in net["nodes"]) == pytest.approx(1.0, abs=1e-5)


def test_hospital_node_sits_on_the_wp06_offset_and_is_critical_at_night(stored: tuple[dict, dict]) -> None:
    net = stored[0]["PS-17"]
    hosp = next(n for n in net["nodes"] if n["role"] == "hospital")
    assert hosp["asset_id"] == "HSP-AIK-TALLOWBRANCH"
    pm = netmod.path_model(net)
    station = pm.sensor_psi(np.array(124.0), np.array(0.0))
    hosp_psi = pm.node_psi(np.array(124.0), np.array(0.0))[pm.node_ids.index(hosp["id"])]
    assert float(station - hosp_psi) == pytest.approx(4.0, abs=0.01)
    night = pm.node_psi(np.array(60.0), np.array(700.0))
    assert pm.node_ids[int(np.argmin(night))] == hosp["id"]


@pytest.mark.parametrize("station", STATIONS)
def test_head_loss_is_homogeneous_in_total_demand(stored: tuple[dict, dict], station: str) -> None:
    net = stored[0][station]
    base = netmod.looped_head_loss_si(net, {n["id"]: 0.0 for n in net["nodes"]})
    old = netmod.Q_REF_SI
    try:
        netmod.Q_REF_SI = 0.37
        scaled = netmod.looped_head_loss_si(net, {n["id"]: 0.0 for n in net["nodes"]})
    finally:
        netmod.Q_REF_SI = old
    for nid, k in base.items():
        assert scaled[nid] == pytest.approx(k, rel=1e-6)


def test_drain_matches_the_closed_form_for_constant_demand(stored: tuple[dict, dict]) -> None:
    net = json.loads(json.dumps(stored[0]["PS-23"]))
    for p in net["pipes"]:
        p["diameter_in"] = 200.0
    net["tank_pipe"]["diameter_in"] = 200.0
    twin = ZoneTwin(net, [1.0] * 24)
    floor = 25.0
    crit_static = float(twin.pm.static_psi.min())
    floor_level = (floor - crit_static) / netmod.PSI_PER_FT
    expected = (twin.pm.max_level_ft - floor_level) * twin.pm.gal_per_ft / twin.avg_gpm
    got = float(twin.drain_to_floor_min(T0, 1.0, floor))
    assert got == pytest.approx(expected, abs=0.05)


def test_drain_is_monotone_in_demand_floor_and_start_level() -> None:
    twin = zone_twins()["PS-17"]
    mult = np.array([1.0, 1.2, 1.5, 2.0])
    d = twin.drain_to_floor_min(np.full(4, T0), mult, 25.0)
    assert np.all(np.diff(d) < 0)
    assert float(twin.drain_to_floor_min(T0, 1.3, 20.0)) > float(twin.drain_to_floor_min(T0, 1.3, 25.0))
    assert float(twin.drain_to_floor_min(T0, 1.3, 25.0, level0_ft=90.0)) < float(
        twin.drain_to_floor_min(T0, 1.3, 25.0)
    )


def test_artefacts_belong_together() -> None:
    import hashlib

    grid = json.loads((ARTEFACT_DIR / "wntr_drain_grid.json").read_text())
    sha = hashlib.sha256((ARTEFACT_DIR / "networks.json").read_bytes()).hexdigest()
    assert grid["networks_sha256"] == sha
    assert grid["runs"] == len(grid["rows"]) == 4 * 48 * 4 * 3
