from __future__ import annotations

import hashlib
import json
import math

import pytest

from sgw.generator.config import load_family, load_scenario
from sgw.models.whatif import grid as g


@pytest.fixture(scope="module")
def stored() -> dict:
    return g.load_grid()


def test_grid_is_complete_and_hash_checked(stored: dict) -> None:
    assert stored["mode"] == "what_if" and stored["tier"] == "T0"
    assert len(stored["cells"]) == math.prod(len(v) for v in g.LEVERS.values()) == 81
    body = json.dumps(stored["cells"], sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(body.encode()).hexdigest() == stored["cells_sha256"]


def test_baseline_levers_leave_the_world_unchanged() -> None:
    sc = load_scenario("helene")
    fam = load_family(sc["family"])
    s, f = g.apply_levers(sc, fam, g.BASELINE)
    assert s == sc
    assert {k: p.value for k, p in f.params.items()} == {k: p.value for k, p in fam.params.items()}


def test_track_shift_moves_every_fix_east_by_the_distance() -> None:
    sc = load_scenario("helene")
    fam = load_family(sc["family"])
    s, _ = g.apply_levers(sc, fam, {"track_shift_km": 40.0})
    for a, b in zip(sc["storm"]["track"], s["storm"]["track"], strict=True):
        dx = (b[2] - a[2]) * g.KM_PER_DEG_LAT * math.cos(math.radians(a[1]))
        assert dx == pytest.approx(40.0)
        assert b[1] == a[1]


def test_baseline_cell_recomputes_exactly(stored: dict) -> None:
    assert g.run_cell(g.BASELINE).__dict__ == {
        k: v for k, v in g.lookup({}, stored).items() if k != "delta_customer_hours_pct"
    }


def test_a_corner_cell_recomputes_exactly(stored: dict) -> None:
    corner = {
        "track_shift_km": 40.0,
        "gust_scale": 1.1,
        "mutual_aid_scale": 0.75,
        "mutual_aid_request_shift_h": 12.0,
    }
    assert g.run_cell(corner).__dict__ == {
        k: v for k, v in g.lookup(corner, stored).items() if k != "delta_customer_hours_pct"
    }


def test_physical_direction_of_each_lever(stored: dict) -> None:
    ch = {k: [g.lookup({k: v}, stored)["customer_hours"] for v in vals] for k, vals in g.LEVERS.items()}
    assert ch["gust_scale"][0] < ch["gust_scale"][1] < ch["gust_scale"][2]
    assert ch["mutual_aid_scale"][0] > ch["mutual_aid_scale"][1] > ch["mutual_aid_scale"][2]
    assert ch["mutual_aid_request_shift_h"][2] > ch["mutual_aid_request_shift_h"][1]


def test_lookup_refuses_levels_that_were_not_precomputed(stored: dict) -> None:
    with pytest.raises(KeyError):
        g.lookup({"gust_scale": 1.05}, stored)
    with pytest.raises(KeyError):
        g.lookup({"crew_count": 1.0}, stored)
