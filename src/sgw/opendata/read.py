"""Time-gated reads of the derived open-data files (`sgw.opendata.build`): at a view time only what had been
observed, issued or declared by then. Gauges and stations carry the peak so far, never a later one."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from sgw.contracts.api_models import (
    DisasterDeclaration,
    FloodCategory,
    GaugeObserved,
    ObservedHazard,
    OfficialRecord,
    StormEventCount,
    StormEventItem,
    WarningArea,
    WindStationObserved,
)
from sgw.opendata.build import (
    GAP_MIN,
    KT_TO_MPH,
    OUT_ROOT,
    OUTPUTS,
    WIND_DATA_END,
    WINDOW_START,
    simplified_multipolygon,
)

TOP_EVENTS = 8
EVENT_URL = "https://www.ncdc.noaa.gov/stormevents/eventdetails.jsp?id={}"
OBSERVED_SOURCES = [
    "USGS NWIS river gauges (public domain); NWS flood stages from NOAA NWPS",
    "Iowa Environmental Mesonet ASOS archive (NWS/FAA observations)",
    "Iowa Environmental Mesonet archive of NWS warnings (VTEC)",
]
RECORD_ATTRIBUTION = [
    "This product uses the FEMA OpenFEMA API, but is not endorsed by FEMA. The Federal Government or FEMA"
    " cannot vouch for the data or analyses derived from these data after the data have been retrieved from"
    " the Agency's website(s).",
    "NOAA National Centers for Environmental Information, Storm Events Database.",
]
PATHS = {key: rel for rel, key in OUTPUTS.items()}


@cache
def load(key: str, root: Path = OUT_ROOT) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((root / PATHS[key]).read_text(encoding="utf-8"))
    return data


def _at(minute: int) -> datetime:
    return WINDOW_START + timedelta(minutes=minute)


def _minute(t: datetime) -> float:
    return (t.astimezone(UTC) - WINDOW_START).total_seconds() / 60


def last_at_or_before(rise: list[list[Any]], t: float) -> list[Any] | None:
    """The last point of a time-ordered rise series at or before minute `t`."""
    found = None
    for p in rise:
        if p[0] > t:
            break
        found = p
    return found


def category(peak: float | None, stages: dict[str, float | None]) -> FloodCategory:
    if peak is None:
        return "below"
    for name in ("major", "moderate", "minor"):
        stage = stages.get(name)
        if stage is not None and peak >= stage:
            return name  # type: ignore[return-value]
    return "below"


def silent_since(periods: list[list[int]], m: float) -> int | None:
    """Start of the silence running at minute `m`: a period counts once it is longer than an hour; the last
    period of a file runs on past its end, since no later report exists."""
    for i, (a, b) in enumerate(periods):
        open_ended = i == len(periods) - 1 and b >= WIND_DATA_END
        if a + GAP_MIN <= m and (m < b or open_ended):
            return int(a)
    return None


def gauges_at(t: datetime) -> list[GaugeObserved]:
    out = []
    m = _minute(t)
    for g in load("gauges")["gauges"]:
        point = last_at_or_before(g["rise"], m)
        stages = g["stages_ft"]
        peak = float(point[1]) if point else None
        out.append(
            GaugeObserved(
                gauge_id=g["id"],
                nws_id=g["lid"],
                name=g["name"],
                state=g["state"],
                county=g["county"],
                lon=g["lon"],
                lat=g["lat"],
                flood_ft=stages["minor"],
                moderate_ft=stages["moderate"],
                major_ft=stages["major"],
                peak_ft=peak,
                peak_utc=_at(point[0]) if point else None,
                category=category(peak, stages),
            )
        )
    return out


def stations_at(t: datetime) -> list[WindStationObserved]:
    out = []
    m = _minute(t)
    for s in load("wind")["stations"]:
        point = last_at_or_before(s["rise"], m)
        silent = silent_since(s["silent"], m)
        out.append(
            WindStationObserved(
                station=s["id"],
                name=s["name"],
                lon=s["lon"],
                lat=s["lat"],
                gust_mph=round(point[1] * KT_TO_MPH) if point else None,
                from_deg=point[2] if point and point[2] >= 0 else None,
                gust_utc=_at(point[0]) if point else None,
                silent_since_utc=_at(silent) if silent is not None else None,
            )
        )
    return out


SEAM_DEG = 0.002
KIND_ORDER = {"tropical_storm": 0, "hurricane": 1, "flood": 2, "flash_flood": 3, "tornado": 4}


def warnings_at(t: datetime) -> list[WarningArea]:
    """Warnings in force at `t`; zones of one warning with the same valid time are merged into one area."""
    return list(_warnings_at_minute(int(_minute(t))))


@lru_cache(maxsize=512)
def _warnings_at_minute(m: int) -> tuple[WarningArea, ...]:
    from shapely.geometry import shape
    from shapely.ops import unary_union

    doc = load("warnings")
    groups: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    for w in doc["warnings"]:
        if w["from"] <= m < w["to"]:
            groups.setdefault((w["id"], w["from"], w["to"]), []).append(w)
    out = []
    for (wid, start, stop), items in groups.items():
        parts = [doc["zones"][w["zone"]] if "zone" in w else w["geometry"] for w in items]
        geometry = (
            parts[0]
            if len(parts) == 1
            else simplified_multipolygon(
                unary_union([shape(g).buffer(SEAM_DEG) for g in parts]).buffer(-SEAM_DEG)
            )
        )
        if geometry is None:
            continue
        first = items[0]
        out.append(
            WarningArea(
                warning_id=f"{wid}.{start}.{stop}",
                kind=first["kind"],
                office=first["office"],
                issued_utc=_at(start),
                expires_utc=_at(stop),
                geometry=geometry,
            )
        )
    out.sort(key=lambda w: (KIND_ORDER[w.kind], w.issued_utc, w.warning_id))
    return tuple(out)


def observed(t: datetime) -> ObservedHazard:
    return ObservedHazard(
        as_of=t,
        gauges=gauges_at(t),
        stations=stations_at(t),
        warnings=warnings_at(t),
        sources=OBSERVED_SOURCES,
    )


@cache
def county_names() -> dict[str, tuple[str, str]]:
    from sgw.reference.load import COUNTIES_PATH

    data = json.loads(COUNTIES_PATH.read_text(encoding="utf-8"))
    return {
        str(f["properties"]["fips"]): (f["properties"]["name"], f["properties"]["state"])
        for f in data["features"]
    }


def official_record(t: datetime) -> OfficialRecord:
    day = t.astimezone(UTC).date().isoformat()
    declarations = [
        DisasterDeclaration(
            declaration_id=d["id"],
            state=d["state"],
            title=d["title"],
            declared_on=d["declared"],
            incident_begin=d["incident_begin"],
            incident_end=d["incident_end"],
            programs=d["programs"],
            counties_total=d["counties_total"],
            footprint_counties=d["footprint_fips"],
        )
        for d in load("declarations")["declarations"]
        if d["declared"] <= day
    ]
    names = county_names()
    events = [
        e for e in load("events")["events"] if datetime.fromisoformat(e["begin"].replace("Z", "+00:00")) <= t
    ]
    by_type = Counter(e["type"] for e in events)
    severe = sorted(events, key=lambda e: (-e["deaths"], -e["damage_usd"], -e["injuries"], e["begin"]))
    return OfficialRecord(
        as_of=t,
        declarations=declarations,
        events_total=len(events),
        events_by_type=[
            StormEventCount(event_type=k, count=v)
            for k, v in sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        deaths=sum(e["deaths"] for e in events),
        injuries=sum(e["injuries"] for e in events),
        damage_usd=sum(e["damage_usd"] for e in events),
        top_events=[
            StormEventItem(
                event_id=e["id"],
                event_type=e["type"],
                county=names.get(e["fips"], ("", ""))[0],
                state=names.get(e["fips"], ("", ""))[1],
                begin_utc=datetime.fromisoformat(e["begin"].replace("Z", "+00:00")),
                deaths=e["deaths"],
                injuries=e["injuries"],
                damage_usd=e["damage_usd"],
                url=EVENT_URL.format(e["id"]),
            )
            for e in severe[:TOP_EVENTS]
            if e["deaths"] or e["damage_usd"] or e["injuries"]
        ],
        attribution=RECORD_ATTRIBUTION,
    )
