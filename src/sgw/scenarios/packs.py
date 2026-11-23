"""Scenario packs (design R33 C3 step 2 option B): a scenario other than the Helene replay is a
declarative pack under `data/scenarios/<dir>/` (`pack.yaml`: period, moments, the real storm track, scripted
outages, critical facilities and crews; `msel.yaml`: the exercise injects in the `sgw.rules.injects` format).
The active scenario is the scenario clock's (`control_state.scenario_clock.scenario`); Helene is the default
and is never read from here. Every number a pack serves is scripted exercise data, labelled as such."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from sgw.rules import injects
from sgw.rules.zones import ZoneHit

REPO = Path(__file__).resolve().parents[3]
ROOT = REPO / "data" / "scenarios"
PACK_DIRS: Mapping[str, str] = {"ian": "ian-2022"}
ADVISORY_EVERY = timedelta(hours=6)
ADVISORY_HOURS = (3, 9, 15, 21)


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


@dataclass(frozen=True)
class Moment:
    moment_id: str
    label: str
    at: datetime


@dataclass(frozen=True)
class Fix:
    at: datetime
    lat: float
    lon: float
    vmax_kt: float


@dataclass(frozen=True)
class Facility:
    asset_id: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class CrewCounts:
    at: datetime
    counts: Mapping[str, int]


@dataclass(frozen=True)
class CrewGroup:
    prefix: str
    first: int
    count: int
    headcount: int
    region_id: str


@dataclass(frozen=True)
class RosterCrew:
    crew_id: str
    status: str
    headcount: int
    region_id: str
    location_id: str | None


@dataclass(frozen=True)
class Advisory:
    label: str
    issued: datetime
    next_issued: datetime | None


@dataclass(frozen=True)
class Pack:
    scenario: str
    title: str
    label: str
    incident_id: str
    proposal_prefix: str
    window_start: datetime
    window_end: datetime
    bookmarks: tuple[tuple[str, datetime], ...]
    moments: tuple[Moment, ...]
    track_source: str
    track: tuple[Fix, ...]
    outage_total: tuple[tuple[datetime, int], ...]
    county_share: Mapping[str, float]
    facilities: tuple[Facility, ...]
    crews: tuple[CrewCounts, ...]
    crew_groups: tuple[CrewGroup, ...]
    crew_yards: tuple[str, ...]
    msel: injects.Injects
    source_dir: str

    @property
    def landfall(self) -> datetime:
        return dict(self.bookmarks)["landfall"]

    @property
    def asset_ids(self) -> frozenset[str]:
        return frozenset(a.asset_id for a in self.msel.assets)

    def owns(self, proposal_id: str) -> bool:
        return proposal_id.startswith(self.proposal_prefix)

    def owns_case(self, decision_case_id: str) -> bool:
        return f"-{self.scenario.upper()}-" in decision_case_id

    def owns_audit(self, subject: str | None, payload: Any) -> bool:
        """An audit record belongs to the pack unless it names a proposal of another scenario."""
        text = f"{subject or ''} {json.dumps(payload, default=str)}"
        return "PRP-" not in text.replace(self.proposal_prefix, "")

    def customers_out(self, at: datetime) -> int:
        pts = self.outage_total
        if not pts or at < pts[0][0]:
            return 0
        for (t0, v0), (t1, v1) in zip(pts, pts[1:], strict=False):
            if t0 <= at <= t1:
                share = (at - t0) / (t1 - t0) if t1 > t0 else 1.0
                return round(v0 + (v1 - v0) * share)
        return pts[-1][1]

    def counties_out(self, at: datetime) -> dict[str, int]:
        """The total split by county share, largest remainder first, so the counties add up to the total."""
        total = self.customers_out(at)
        exact = {fips: total * share for fips, share in self.county_share.items()}
        out = {fips: int(v) for fips, v in exact.items()}
        short = total - sum(out.values())
        for fips in sorted(exact, key=lambda f: (out[f] - exact[f], f))[:short]:
            out[fips] += 1
        return {fips: n for fips, n in sorted(out.items()) if n > 0}

    def feed_hour(self, at: datetime) -> datetime | None:
        first = self.outage_total[0][0] if self.outage_total else None
        if first is None or at < first:
            return None
        return at.replace(minute=0, second=0, microsecond=0)

    def peak(self) -> tuple[datetime, int]:
        return max(self.outage_total, key=lambda p: p[1])

    def facilities_out(self, at: datetime) -> list[str]:
        return [f.asset_id for f in self.facilities if f.start <= at < f.end]

    def crew_counts(self, at: datetime) -> dict[str, int]:
        current: Mapping[str, int] = {}
        for row in self.crews:
            if row.at <= at:
                current = row.counts
        return dict(current)

    def roster(self, at: datetime) -> list[RosterCrew]:
        """Named crews whose statuses add up to the scripted counts at `at`: onsite first, then en route,
        staged and available; staged crews sit at the pack's yards in turn, working crews in the counties
        with outages, largest first."""
        counts = self.crew_counts(at)
        order = ("onsite", "enroute", "staged", "available")
        statuses = [s for s in order for _ in range(counts.get(s, 0))]
        crews = [
            (f"{g.prefix}-{i:04d}", g.headcount, g.region_id)
            for g in self.crew_groups
            for i in range(g.first, g.first + g.count)
        ]
        counties = [f"SC-{fips}" for fips, _ in sorted(self.county_share.items(), key=lambda kv: -kv[1])]
        out: list[RosterCrew] = []
        for i, ((crew_id, heads, home), status) in enumerate(zip(crews, statuses, strict=False)):
            yard = (
                self.crew_yards[i % len(self.crew_yards)] if status == "staged" and self.crew_yards else None
            )
            region = counties[i % len(counties)] if status in ("onsite", "enroute") and counties else home
            out.append(RosterCrew(crew_id, status, heads, region, yard))
        return out

    def position(self, at: datetime) -> Fix | None:
        fixes = self.track
        if not fixes or at < fixes[0].at:
            return None
        for a, b in zip(fixes, fixes[1:], strict=False):
            if a.at <= at <= b.at:
                s = (at - a.at) / (b.at - a.at) if b.at > a.at else 0.0
                return Fix(
                    at,
                    round(a.lat + (b.lat - a.lat) * s, 2),
                    round(a.lon + (b.lon - a.lon) * s, 2),
                    round(a.vmax_kt + (b.vmax_kt - a.vmax_kt) * s),
                )
        return None

    def advisories(self) -> tuple[Advisory, ...]:
        """Six-hourly positions on the best track while the storm is on it (NHC issue hours), the last one
        naming no next advisory."""
        start = self.window_start.replace(minute=0, second=0, microsecond=0)
        times: list[datetime] = []
        t = start
        while t <= self.track[-1].at:
            if t.hour in ADVISORY_HOURS and t >= self.window_start and self.position(t) is not None:
                times.append(t)
            t += timedelta(hours=1)
        return tuple(
            Advisory(f"{self.scenario.upper()}-{i:02d}", at, times[i] if i < len(times) else None)
            for i, at in enumerate(times, start=1)
        )


def _proposer(raw: Mapping[str, Any], default: str) -> str:
    return str(raw.get("proposer") or default)


def _msel(path: Path, prefix: str) -> injects.Injects:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    base = injects.parse({**raw, "injects": [i for i in raw["injects"] if not i.get("proposer")]})
    label = str(raw["label"])
    own: list[ZoneHit] = [
        injects._hit(i, _proposer(i, str(raw["proposer"])), label)  # noqa: SLF001
        for i in raw["injects"]
        if i.get("proposer")
    ]
    regions = {f"DC-{i['step']}-{i['id']}": str(i["region"]) for i in raw["injects"]}
    hits = tuple(sorted((*base.hits, *own), key=lambda h: (h.known_at, h.key)))
    keys = [h.key for h in hits]
    if len(set(keys)) != len(keys):
        raise ValueError(f"{path}: duplicate inject ids")
    if not prefix:
        raise ValueError(f"{path}: a pack needs its own proposal prefix")
    return injects.Injects(
        version=base.version,
        proposer=base.proposer,
        incident_id=base.incident_id,
        label=label,
        assets=base.assets,
        hits=hits,
        regions=regions,
    )


def parse(raw: Mapping[str, Any], msel: injects.Injects, source_dir: str) -> Pack:
    window = raw["window"]
    moments = tuple(Moment(str(m["id"]), str(m["label"]), _utc(str(m["at"]))) for m in raw["moments"])
    start, end = _utc(str(window["start"])), _utc(str(window["end"]))
    if not all(start <= m.at <= end for m in moments):
        raise ValueError(f"{source_dir}: every moment must lie inside the window")
    bookmarks = tuple((str(k), _utc(str(v))) for k, v in dict(raw["bookmarks"]).items())
    if "landfall" not in dict(bookmarks):
        raise ValueError(f"{source_dir}: the pack needs a landfall bookmark")
    share = {str(k): float(v) for k, v in dict(raw["outages"]["county_share"]).items()}
    if abs(sum(share.values()) - 1.0) > 1e-6:
        raise ValueError(f"{source_dir}: county shares must add up to 1")
    return Pack(
        scenario=str(raw["id"]),
        title=str(raw["title"]),
        label=str(raw["label"]),
        incident_id=str(raw["incident_id"]),
        proposal_prefix=str(raw["proposal_prefix"]),
        window_start=start,
        window_end=end,
        bookmarks=bookmarks,
        moments=moments,
        track_source=str(raw["track_source"]),
        track=tuple(Fix(_utc(str(r[0])), float(r[1]), float(r[2]), float(r[3])) for r in raw["track"]),
        outage_total=tuple((_utc(str(r[0])), int(r[1])) for r in raw["outages"]["total"]),
        county_share=share,
        facilities=tuple(
            Facility(str(f["asset"]), _utc(str(f["from"])), _utc(str(f["to"])))
            for f in raw["critical_facilities"]
        ),
        crews=tuple(
            CrewCounts(_utc(str(c["at"])), {k: int(v) for k, v in c.items() if k != "at"})
            for c in raw["crews"]
        ),
        crew_groups=tuple(
            CrewGroup(
                str(g["prefix"]), int(g["first"]), int(g["count"]), int(g["headcount"]), str(g["region"])
            )
            for g in raw.get("crew_groups") or ()
        ),
        crew_yards=tuple(str(y) for y in raw.get("crew_yards") or ()),
        msel=msel,
        source_dir=source_dir,
    )


def is_pack(scenario: str) -> bool:
    return scenario in PACK_DIRS


def names() -> tuple[str, ...]:
    return tuple(PACK_DIRS)


@cache
def load(scenario: str) -> Pack:
    folder = ROOT / PACK_DIRS[scenario]
    raw = yaml.safe_load((folder / "pack.yaml").read_text(encoding="utf-8"))
    if str(raw["id"]) != scenario:
        raise ValueError(f"{folder}: pack id {raw['id']!r} is not {scenario!r}")
    msel = _msel(folder / "msel.yaml", str(raw["proposal_prefix"]))
    return parse(raw, msel, f"data/scenarios/{PACK_DIRS[scenario]}")


def get(scenario: str) -> Pack | None:
    return load(scenario) if is_pack(scenario) else None


def visible[T](scenario: str, items: Sequence[T], key: Any) -> list[T]:
    """The items of the active pack only (by proposal id); Helene's list is returned as it is."""
    pack = get(scenario)
    if pack is None:
        return list(items)
    return [i for i in items if pack.owns(str(key(i)))]
