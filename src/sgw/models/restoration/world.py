"""The storm's damage as the restoration process sees it, taken from a generator truth run.

The generator supplies sections, faults, damage states, access (wind hold + debris), crews and the Hazus
work per section. Restoration itself is re-run by `process.py`, which adds what the generator lacks
(secondary jobs, crew shifts, storm-level productivity), so the generator's own restore times are unused.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Any

import numpy as np

from sgw.generator import restoration as gen_rs
from sgw.generator.config import load_family, load_scenario, parse_utc
from sgw.generator.truth import Truth, access_delay_h, run_truth
from sgw.generator.wind import epoch


@dataclass(frozen=True)
class World:
    scenario: str
    seed: int
    section_id: np.ndarray
    fips: np.ndarray
    feeder: np.ndarray
    trunk_of: np.ndarray
    is_trunk: np.ndarray
    region: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    customers: np.ndarray
    weight: np.ndarray
    critical: np.ndarray
    fault_t: np.ndarray
    base_t: np.ndarray
    work_ok: np.ndarray
    ds: np.ndarray
    hazus_h: np.ndarray
    peak_gust: np.ndarray
    region_ids: tuple[str, ...]
    yard_lat: np.ndarray
    yard_lon: np.ndarray
    crew_id: tuple[str, ...]
    crew_region: np.ndarray
    crew_headcount: np.ndarray
    crew_available: np.ndarray
    crew_mutual_aid: np.ndarray
    request_t: float
    start_t: float
    mutual_aid_median_h: float
    mutual_aid_sigma: float
    travel_kmh: float
    min_repair_h: float

    @property
    def failed(self) -> np.ndarray:
        return ~np.isnan(self.fault_t)


def region_code(yard_id: str) -> str:
    """`STG-AIK-SANDHILL-YARD` -> `OPA-AIK-SANDHILL` (operating area served by one crew yard)."""
    core = yard_id.removeprefix("STG-").removesuffix("-YARD")
    return f"OPA-{core}"


def world_from_truth(truth: Truth) -> World:
    net = truth.net
    fam = truth.family
    sc = truth.scenario
    idx = net.section_index()
    trunk_of = np.array([idx[f"{f}-S1"] for f in net.sections["feeder"]])
    trunk = np.asarray(net.sections["trunk"], dtype=bool)
    customers = np.asarray(net.sections["customers"], dtype=float)
    feeder_customers = dict(zip(net.feeders["id"], net.feeders["customers"], strict=True))
    weight = np.array(
        [
            float(feeder_customers[f]) if t else c
            for f, t, c in zip(net.sections["feeder"], trunk, customers, strict=True)
        ]
    )
    access_h = access_delay_h(net, truth.section_gust_peak, fam, sc, truth.seed)
    yards = net.yards
    return World(
        scenario=str(sc["scenario"]),
        seed=truth.seed,
        section_id=np.asarray(net.sections["id"]),
        fips=np.asarray(net.sections["fips"]),
        feeder=np.asarray(net.sections["feeder"]),
        trunk_of=trunk_of,
        is_trunk=trunk,
        region=gen_rs.section_yards(net)[trunk_of],
        lat=np.asarray(net.sections["lat"], dtype=float),
        lon=np.asarray(net.sections["lon"], dtype=float),
        customers=customers,
        weight=weight,
        critical=np.array([bool(c) for c in net.sections["critical"]]),
        fault_t=truth.fault_t.copy(),
        base_t=truth.work_ok - access_h * 3600.0,
        work_ok=truth.work_ok.copy(),
        ds=truth.ds.copy(),
        hazus_h=truth.repair_h.copy(),
        peak_gust=truth.section_gust_peak.copy(),
        region_ids=tuple(region_code(y["id"]) for y in yards),
        yard_lat=np.array([y["lat"] for y in yards], dtype=float),
        yard_lon=np.array([y["lon"] for y in yards], dtype=float),
        crew_id=tuple(c.id for c in truth.crews),
        crew_region=np.array([c.yard for c in truth.crews], dtype=int),
        crew_headcount=np.array([c.headcount for c in truth.crews], dtype=float),
        crew_available=np.array([c.available_utc for c in truth.crews], dtype=float),
        crew_mutual_aid=np.array([c.mutual_aid for c in truth.crews], dtype=bool),
        request_t=epoch(parse_utc(sc["detail"]["mutual_aid_request_utc"])),
        start_t=epoch(parse_utc(sc["window"]["start_utc"])),
        mutual_aid_median_h=fam.f("restoration.mutual_aid_median_h"),
        mutual_aid_sigma=fam.f("restoration.mutual_aid_sigma"),
        travel_kmh=fam.f("restoration.travel_kmh"),
        min_repair_h=fam.f("restoration.min_repair_h"),
    )


@cache
def family_a_world(seed: int, scenario: str = "helene") -> World:
    """Family-A damage for one seed (the scenario's own seed is the story of record)."""
    sc = load_scenario(scenario)
    fam = load_family(str(sc.get("family", "A")))
    if fam.name != "A":
        raise ValueError("WP-17 calibrates and evaluates on family A only")
    return world_from_truth(run_truth(sc, fam, seed=seed))


def story_seed(scenario: str = "helene") -> int:
    sc: dict[str, Any] = load_scenario(scenario)
    return int(sc["seed"])
