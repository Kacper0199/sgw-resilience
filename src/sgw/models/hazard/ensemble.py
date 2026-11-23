"""A1 hazard ensemble for a replay scenario: per advisory, the official forecast and its members as tracks,
and the hazard features of every decision point per member.

Members are the WP-06 forecast members (`sgw.generator.forecast.member_tracks`: NHC-cone errors, common random
numbers across advisories), rebuilt deterministically from the scenario file rather than read back from
`ensemble.json`, because the outage model needs the full wind time series, not only the peak gust. Each member
track is spliced after the analysis track up to the issue time (what an operator knows at issue), so a county
already hit keeps its observed wind. `forecast_window_peak_gust` reproduces WP-06's `ensemble.json` peak gusts
(parity test).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sgw.generator.config import Family, load_counties, load_family, load_scenario, parse_utc
from sgw.generator.forecast import Advisory, advisories, member_tracks
from sgw.generator.wind import Track, epoch
from sgw.models.hazard.field import STEP_S, Points, point_features, splice, time_grid
from sgw.models.hazard.hurdat2 import REPO_ROOT

FIXTURES = REPO_ROOT / "data" / "fixtures"
DETAIL_FIPS = "45003"


@dataclass(frozen=True)
class DecisionPoints:
    points: Points
    kinds: tuple[str, ...]

    def index(self, point_id: str) -> int:
        return self.points.ids.index(point_id)


@dataclass(frozen=True)
class ScenarioHazard:
    name: str
    scenario: dict[str, Any]
    family: Family
    seed: int
    analysis: Track
    advisories: tuple[Advisory, ...]
    decision_points: DecisionPoints

    def advisory(self, label: str) -> Advisory:
        for adv in self.advisories:
            if adv.label == label:
                return adv
        raise KeyError(f"no advisory {label!r} in scenario {self.name}")

    def advisory_at(self, when: Any) -> Advisory | None:
        known = [a for a in self.advisories if a.issued <= when]
        return known[-1] if known else None

    def previous(self, adv: Advisory) -> Advisory | None:
        i = self.advisories.index(adv)
        return self.advisories[i - 1] if i > 0 else None


def _feeder_points(fixtures: Path) -> list[tuple[str, float, float]]:
    with (fixtures / "sections.csv").open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["fips"] == DETAIL_FIPS and r["trunk"] == "1"]
    return [(r["feeder_id"], float(r["lat"]), float(r["lon"])) for r in rows]


def build_points(fixtures: Path) -> DecisionPoints:
    ids: list[str] = []
    kinds: list[str] = []
    lat: list[float] = []
    lon: list[float] = []
    for c in load_counties():
        ids.append(c.fips)
        kinds.append("county")
        lat.append(c.lat)
        lon.append(c.lon)
    for fid, la, lo in _feeder_points(fixtures):
        ids.append(fid)
        kinds.append("feeder")
        lat.append(la)
        lon.append(lo)
    network = json.loads((fixtures / "network.json").read_text(encoding="utf-8"))
    for y in network["yards"]:
        ids.append(y["id"])
        kinds.append("yard")
        lat.append(float(y["lat"]))
        lon.append(float(y["lon"]))
    return DecisionPoints(Points(tuple(ids), np.array(lat), np.array(lon)), tuple(kinds))


@cache
def scenario_hazard(name: str = "helene") -> ScenarioHazard:
    scenario = load_scenario(name)
    fam = load_family(str(scenario.get("family", "A")))
    analysis = Track.from_rows(scenario["storm"]["track"], parse_utc)
    return ScenarioHazard(
        name=name,
        scenario=scenario,
        family=fam,
        seed=int(scenario["seed"]),
        analysis=analysis,
        advisories=tuple(advisories(scenario)),
        decision_points=build_points(FIXTURES / name),
    )


@dataclass(frozen=True)
class MemberHazard:
    member: int
    track: Track
    features: pd.DataFrame
    forecast_peak_gust: np.ndarray


@cache
def advisory_members(name: str, label: str) -> tuple[MemberHazard, ...]:
    """Member 0 is the official forecast; members 1..M the ensemble. Features per decision point."""
    hz = scenario_hazard(name)
    adv = hz.advisory(label)
    official, members, _ = member_tracks(hz.analysis, adv, hz.scenario, hz.family, hz.seed)
    window = _forecast_window(hz, adv)
    out = []
    for m, track in enumerate([official, *members]):
        full = splice(hz.analysis, track)
        feats = point_features(full, hz.decision_points.points, hz.family, time_grid(full))
        ahead = point_features(track, hz.decision_points.points, hz.family, window)["peak_gust_ms"].to_numpy()
        out.append(MemberHazard(m, full, feats, ahead))
    return tuple(out)


def _forecast_window(hz: ScenarioHazard, adv: Advisory) -> np.ndarray:
    start = epoch(adv.issued)
    return np.arange(start, start + hz.family.f("forecast.horizon_h") * 3600.0 + 1.0, STEP_S)


def forecast_window_peak_gust(name: str, label: str) -> np.ndarray:
    """Peak gust per member and decision point over issue .. issue + horizon (WP-06 `ensemble.json` view);
    shape (members, points), official forecast excluded."""
    return np.stack([m.forecast_peak_gust for m in advisory_members(name, label)[1:]])
