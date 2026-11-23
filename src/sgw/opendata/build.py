"""Build the small derived open-data files of the Helene replay from the raw downloads in `raw/data/` (never
committed). Outputs go to `data/open/<source>/helene_*.json` and are read by `sgw.opendata.read`:

- USGS NWIS gage height of the footprint gauges with NWS flood stages (NWPS), kept as the rise of the running
  maximum (one point per 0.1 ft gained), so any view time gets the peak observed so far and nothing later;
- IEM ASOS wind of the six SGW-area airports as the rise of the running maximum gust, with the direction of
  the wind at that report and the silent periods of each station;
- IEM VTEC hurricane, tropical-storm, flood, flash-flood and tornado warnings clipped to the footprint;
- OpenFEMA declarations DR-4829-SC and DR-4830-GA with their footprint counties;
- NCEI Storm Events of 25-28 Sep 2024 in the footprint counties.

Run: `uv run python -I scripts/build_open_data.py [RAW] [OUT]` (defaults: `raw/data`, `data/open`).
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import re
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_ROOT = REPO_ROOT / "raw" / "data"
OUT_ROOT = REPO_ROOT / "data" / "open"
COUNTIES = REPO_ROOT / "data" / "reference" / "counties.geo.json"

WINDOW_START = datetime(2024, 9, 25, tzinfo=UTC)
WINDOW_END = datetime(2024, 10, 3, tzinfo=UTC)
STAGE_STEP_FT = 0.1
GAP_MIN = 60
MISSING_STAGE = -999.0
ELEVATION_STAGE_FT = 100.0
WIND_DATA_END = int((datetime(2024, 9, 30, tzinfo=UTC) - WINDOW_START).total_seconds() // 60)
KT_TO_MPH = 1.15078
SIMPLIFY_DEG = 0.004
COORD_DIGITS = 4

ASOS_STATIONS: dict[str, str] = {
    "AGS": "Augusta",
    "CAE": "Columbia",
    "CHS": "Charleston",
    "GSP": "Greenville-Spartanburg",
    "SAV": "Savannah",
    "VLD": "Valdosta",
}

WARNING_KINDS: dict[str, str] = {
    "HU": "hurricane",
    "TR": "tropical_storm",
    "FL": "flood",
    "FA": "flood",
    "FF": "flash_flood",
    "TO": "tornado",
}
ZONE_KINDS = {"HU", "TR"}
DECLARATIONS = (4829, 4830)
EVENTS_FROM = datetime(2024, 9, 25, tzinfo=UTC)
EVENTS_TO = datetime(2024, 9, 29, tzinfo=UTC)
STATE_NAMES = {"GEORGIA": "GA", "SOUTH CAROLINA": "SC"}
STATE_FIPS = {"GA": "13", "SC": "45"}
ZONE_NAME_NOISE = re.compile(
    r"\b(COASTAL|INLAND|TIDAL|GREATER|MOUNTAINS|NORTHERN|SOUTHERN|EASTERN|WESTERN|CENTRAL|NORTH|SOUTH)\b|"
    r"^(NORTH|SOUTH|EAST|WEST)(?=[A-Z]{4})"
)


def minutes(t: datetime) -> int:
    return int((t - WINDOW_START).total_seconds() // 60)


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def running_max_rise(points: Iterable[tuple[int, float]], step: float) -> list[tuple[int, float]]:
    """The running maximum of a time-ordered series, kept only where it gains at least `step` over the last
    kept point (the first point is always kept). `peak so far at t` is the last kept value at or before t,
    rounded down to `step` at most."""
    kept: list[tuple[int, float]] = []
    for t, v in sorted(points):
        if not kept or v >= kept[-1][1] + step - 1e-9:
            kept.append((t, v))
    return kept


def silent_periods(times: Sequence[int], end: int, gap_min: int = GAP_MIN) -> list[tuple[int, int]]:
    """Intervals longer than `gap_min` without a report, the last one running to `end`."""
    out: list[tuple[int, int]] = []
    ordered = sorted(set(times))
    for a, b in zip(ordered, ordered[1:], strict=False):
        if b - a > gap_min:
            out.append((a, b))
    if ordered and end - ordered[-1] > gap_min:
        out.append((ordered[-1], end))
    return out


def footprint() -> tuple[Any, dict[str, dict[str, str]]]:
    from shapely.geometry import shape
    from shapely.ops import unary_union

    data = json.loads(COUNTIES.read_text(encoding="utf-8"))
    shapes = [shape(f["geometry"]) for f in data["features"]]
    meta = {str(f["properties"]["fips"]): dict(f["properties"]) for f in data["features"]}
    return unary_union(shapes), meta


def _num(text: str | None) -> float | None:
    try:
        value = float(text) if text not in (None, "", "M") else None
    except ValueError:
        return None
    return None if value is None or value <= MISSING_STAGE else value


def gauge_problem(g: GaugeRow, observed_max: float | None) -> str | None:
    """Why a gauge cannot be compared with its flood stages, or None: no series, a tidal datum (MHHW) that the
    USGS gage height does not share, flood stages given as elevations, or stages out of order."""
    if observed_max is None:
        return "no gage height in the window"
    if "MHHW" in g.name.upper():
        return "flood stages in MHHW, gage height in another datum"
    if g.minor is not None and g.minor >= ELEVATION_STAGE_FT and observed_max < g.minor / 2:
        return "flood stages are elevations, not gage height"
    ordered = [v for v in (g.minor, g.moderate, g.major) if v is not None]
    if ordered != sorted(ordered):
        return "flood stages out of order"
    return None


@dataclass(frozen=True)
class GaugeRow:
    usgs: str
    lid: str
    name: str
    state: str
    county: str
    lon: float
    lat: float
    action: float | None
    minor: float | None
    moderate: float | None
    major: float | None


def gauge_rows(raw: Path, area: Any) -> list[GaugeRow]:
    from shapely.geometry import Point

    rows: list[GaugeRow] = []
    with (raw / "nwis" / "storm_peak_vs_flood_stage_GA_SC.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["storm"] != "Helene":
                continue
            lon, lat = float(r["lon"]), float(r["lat"])
            minor = _num(r["minor"])
            if minor is None or not area.contains(Point(lon, lat)):
                continue
            rows.append(
                GaugeRow(
                    r["usgs"],
                    r["lid"],
                    r["name"],
                    r["state"],
                    r["county"],
                    lon,
                    lat,
                    _num(r["action"]),
                    minor,
                    _num(r["moderate"]),
                    _num(r["major"]),
                )
            )
    return sorted(rows, key=lambda g: g.usgs)


def stage_series(raw: Path) -> dict[str, list[tuple[int, float]]]:
    series: dict[str, list[tuple[int, float]]] = {}
    for path in sorted((raw / "nwis" / "iv_footprint").glob("iv_stage_helene_part*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for ts in doc["value"]["timeSeries"]:
            site = ts["sourceInfo"]["siteCode"][0]["value"]
            nodata = float(ts["variable"]["noDataValue"])
            pts = series.setdefault(site, [])
            for block in ts["values"]:
                for v in block["value"]:
                    value = float(v["value"])
                    t = utc(v["dateTime"])
                    if value != nodata and WINDOW_START <= t < WINDOW_END:
                        pts.append((minutes(t), value))
    return series


def build_gauges(raw: Path, area: Any) -> dict[str, Any]:
    series = stage_series(raw)
    gauges = []
    excluded = []
    for g in gauge_rows(raw, area):
        pts = series.get(g.usgs, [])
        problem = gauge_problem(g, max((v for _, v in pts), default=None))
        if problem:
            excluded.append({"id": g.usgs, "name": g.name, "reason": problem})
            continue
        rise = running_max_rise(pts, STAGE_STEP_FT)
        gauges.append(
            {
                "id": g.usgs,
                "lid": g.lid,
                "name": g.name,
                "state": g.state,
                "county": g.county,
                "lon": round(g.lon, 5),
                "lat": round(g.lat, 5),
                "stages_ft": {"action": g.action, "minor": g.minor, "moderate": g.moderate, "major": g.major},
                "rise": [[t, round(v, 2)] for t, v in rise],
                "last": max((t for t, _ in pts), default=None),
            }
        )
    return {
        "meta": _meta(
            "USGS NWIS instantaneous gage height (00065); flood stages from NOAA NWPS",
            "https://waterservices.usgs.gov/ ; https://api.water.noaa.gov/nwps/v1/",
            "public domain (US federal work)",
            "rise = [minutes since window_start, ft]: the running maximum, one point per 0.1 ft gained",
        ),
        "gauges": gauges,
        "excluded": excluded,
    }


def _bearing_mean(values: Sequence[float]) -> float:
    s = sum(math.sin(math.radians(v)) for v in values)
    c = sum(math.cos(math.radians(v)) for v in values)
    return (math.degrees(math.atan2(s, c)) + 360) % 360


def direction_before(reports: Sequence[tuple[int, float]], t: int) -> int:
    """Mean direction (degrees the wind blows from) of the reports in the 30 minutes up to `t`, else of the
    90 minutes up to `t`; -1 when none reported one. Never looks past `t`."""
    for window in (30, 90):
        near = [d for tt, d in reports if t - window <= tt <= t]
        if near:
            return round(_bearing_mean(near)) % 360
    return -1


def build_wind(raw: Path) -> dict[str, Any]:
    stations = []
    end = WIND_DATA_END
    for sid, name in ASOS_STATIONS.items():
        path = raw / "iem_asos" / f"asos_{sid}_2024-09-25_29.csv"
        reports: list[tuple[int, float | None, float | None]] = []
        lon = lat = 0.0
        with path.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                valid = datetime.strptime(r["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
                lon, lat = float(r["lon"]), float(r["lat"])
                speeds = [v for v in (_num(r["gust"]), _num(r["peak_wind_gust"]), _num(r["sknt"])) if v]
                reports.append((minutes(valid), max(speeds) if speeds else None, _num(r["drct"])))
        reports.sort(key=lambda x: x[0])
        rise: list[list[int]] = []
        best = 0.0
        recent_dir: list[tuple[int, float]] = []
        for t, kt, drct in reports:
            if drct is not None:
                recent_dir.append((t, drct))
            if kt is None or kt < best + 1:
                continue
            best = kt
            rise.append([t, round(kt), direction_before(recent_dir, t)])
        stations.append(
            {
                "id": sid,
                "name": name,
                "lon": round(lon, 4),
                "lat": round(lat, 4),
                "rise": rise,
                "silent": [list(p) for p in silent_periods([r[0] for r in reports], end)],
            }
        )
    return {
        "meta": _meta(
            "IEM ASOS archive (NWS/FAA METAR and 5-minute ASOS)",
            "https://mesonet.agron.iastate.edu/request/download.phtml",
            "public domain (IEM disclaimer); attribution to IEM",
            "rise = [minutes since window_start, gust kt, direction the wind blows from in degrees or -1]:"
            " the running maximum of gust, peak gust and sustained speed, one point per 1 kt gained;"
            " direction is the mean of the reports of the previous 30 minutes; silent = [from, to] minutes"
            " with no report for more than 60 minutes",
        ),
        "stations": stations,
    }


def _vtec_time(text: str | None) -> datetime | None:
    return datetime.strptime(text, "%Y%m%d%H%M").replace(tzinfo=UTC) if text else None


def _ring(ring: Any) -> list[list[float]]:
    return [[round(x, COORD_DIGITS), round(y, COORD_DIGITS)] for x, y in ring.coords]


def _polygons(geom: Any) -> list[Any]:
    if geom.geom_type == "Polygon":
        return [geom]
    return [p for g in getattr(geom, "geoms", []) for p in _polygons(g)]


def simplified_multipolygon(geom: Any) -> dict[str, Any] | None:
    """GeoJSON MultiPolygon of the polygon parts of `geom`, simplified and rounded; slivers dropped."""
    if geom.is_empty:
        return None
    simple = geom.simplify(SIMPLIFY_DEG, preserve_topology=True)
    polys = [p for p in _polygons(simple) if p.area > 1e-6]
    if not polys:
        return None
    return {
        "type": "MultiPolygon",
        "coordinates": [[_ring(p.exterior), *(_ring(i) for i in p.interiors)] for p in polys],
    }


def warning_window(row: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """Valid time of one IEM VTEC row: storm-based polygons by their polygon times when those are a real span,
    zones and river-flood polygons by issue and expiry; a row that expires before it starts never shows."""
    start, end = _vtec_time(row.get("ISSUED")), _vtec_time(row.get("EXPIRED"))
    if row.get("GTYPE") == "P" and row.get("PHENOM") != "FL":
        pb, pe = _vtec_time(row.get("POLY_BEG")), _vtec_time(row.get("POLY_END"))
        if pb and pe and pe > pb:
            start, end = pb, pe
    if start is None or end is None or end <= start:
        return None
    return start, end


def build_warnings(raw: Path, area: Any) -> dict[str, Any]:
    import geopandas as gpd

    zip_path = raw / "iem_vtec" / "watchwarn_2024-09-25_29.zip"
    with zipfile.ZipFile(zip_path) as zf:
        shp = next(n for n in zf.namelist() if n.endswith(".shp"))
    frame = gpd.read_file(f"zip://{zip_path}!{shp}")
    frame = frame[frame["SIG"].eq("W") & frame["PHENOM"].isin(list(WARNING_KINDS))]
    zone_rows = frame["GTYPE"].eq("C") & frame["PHENOM"].isin(list(ZONE_KINDS))
    poly_rows = frame["GTYPE"].eq("P") & ~frame["PHENOM"].isin(list(ZONE_KINDS))
    frame = frame[(zone_rows | poly_rows) & frame.intersects(area)]
    zones: dict[str, dict[str, Any]] = {}
    items: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in frame.sort_values(["ISSUED", "WFO", "ETN"]).to_dict("records"):
        window = warning_window(row)
        if window is None:
            continue
        clipped = row["geometry"].intersection(area)
        if clipped.is_empty or clipped.area < 1e-5:
            continue
        ugc = row.get("NWS_UGC") if row["GTYPE"] == "C" else None
        key = (row["PHENOM"], row["WFO"], int(row["ETN"]), ugc, window)
        if key in seen:
            continue
        seen.add(key)
        item: dict[str, Any] = {
            "id": f"{row['WFO']}.{row['PHENOM']}.W.{int(row['ETN']):04d}",
            "kind": WARNING_KINDS[row["PHENOM"]],
            "office": row["WFO"],
            "from": minutes(window[0]),
            "to": minutes(window[1]),
        }
        if ugc:
            if ugc not in zones:
                geometry = simplified_multipolygon(clipped)
                if geometry is None:
                    continue
                zones[ugc] = geometry
            item["zone"] = ugc
        else:
            geometry = simplified_multipolygon(clipped)
            if geometry is None:
                continue
            item["geometry"] = geometry
        items.append(item)
    return {
        "meta": _meta(
            "IEM archive of NWS VTEC watches, warnings and advisories (warnings HU, TR, FL, FA, FF, TO)",
            "https://mesonet.agron.iastate.edu/request/gis/watchwarn.phtml",
            "public domain (IEM disclaimer); NWS products",
            "from/to = minutes since window_start; zone warnings reference `zones`; geometry clipped to the"
            f" SGW footprint and simplified {SIMPLIFY_DEG} degree",
        ),
        "zones": dict(sorted(zones.items())),
        "warnings": items,
    }


def build_declarations(raw: Path, counties: dict[str, dict[str, str]]) -> dict[str, Any]:
    doc = json.loads(
        (raw / "openfema_declarations" / "helene_dr" / "dr_4829_4830.json").read_text(encoding="utf-8")
    )
    rows = [r for r in doc["DisasterDeclarationsSummaries"] if r["disasterNumber"] in DECLARATIONS]
    out = []
    for number in DECLARATIONS:
        mine = [r for r in rows if r["disasterNumber"] == number]
        first = mine[0]
        fips = sorted(
            {f"{r['fipsStateCode']}{r['fipsCountyCode']}" for r in mine if r["fipsCountyCode"] != "000"}
        )
        programs = [
            p
            for p, key in (
                ("Individual assistance", "ihProgramDeclared"),
                ("Public assistance", "paProgramDeclared"),
                ("Hazard mitigation", "hmProgramDeclared"),
            )
            if any(r[key] for r in mine)
        ]
        out.append(
            {
                "id": first["femaDeclarationString"],
                "number": number,
                "state": first["state"],
                "title": first["declarationTitle"].title(),
                "declared": first["declarationDate"][:10],
                "incident_begin": first["incidentBeginDate"][:10],
                "incident_end": (first["incidentEndDate"] or "")[:10] or None,
                "programs": programs,
                "counties_total": len(fips),
                "footprint_fips": [f for f in fips if f in counties],
            }
        )
    return {
        "meta": _meta(
            "OpenFEMA Disaster Declarations Summaries v2",
            "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries",
            "OpenFEMA terms: uses the FEMA OpenFEMA API, not endorsed by FEMA",
            "one entry per declaration; footprint_fips = designated counties inside the SGW footprint",
        ),
        "declarations": out,
    }


def zone_county(state: str, name: str, by_name: dict[tuple[str, str], str]) -> str | None:
    clean = re.sub(r"\s+", " ", ZONE_NAME_NOISE.sub("", name.upper().replace(" (ZONE)", ""))).strip()
    clean = clean.replace("DE KALB", "DEKALB")
    return by_name.get((state, clean))


def _damage(text: str | float | None) -> int:
    if text is None or (isinstance(text, float) and math.isnan(text)) or text == "":
        return 0
    s = str(text).strip().upper()
    scale = {"K": 1e3, "M": 1e6, "B": 1e9}.get(s[-1:], 1)
    try:
        return int(round(float(s.rstrip("KMB") or 0) * scale))
    except ValueError:
        return 0


def _event_time(text: str, zone: str) -> datetime:
    offset = int(zone.split("-")[-1]) if "-" in zone else 5
    local = datetime.strptime(text, "%d-%b-%y %H:%M:%S")
    return (local + timedelta(hours=offset)).replace(tzinfo=UTC)


def build_storm_events(raw: Path, counties: dict[str, dict[str, str]]) -> dict[str, Any]:
    by_name = {(m["state"], m["name"].upper()): fips for fips, m in counties.items()}
    events = []
    with gzip.open(raw / "storm_events" / "subset_helene_se.csv.gz", "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            state = STATE_NAMES.get(r["STATE"])
            if state is None:
                continue
            fips: str | None
            if r["CZ_TYPE"] == "C":
                code = f"{STATE_FIPS[state]}{int(r['CZ_FIPS']):03d}"
                fips = code if code in counties else None
            else:
                fips = zone_county(state, r["CZ_NAME"], by_name)
            if fips is None:
                continue
            begin = _event_time(r["BEGIN_DATE_TIME"], r["CZ_TIMEZONE"])
            if not EVENTS_FROM <= begin < EVENTS_TO:
                continue
            events.append(
                {
                    "id": int(r["EVENT_ID"]),
                    "type": r["EVENT_TYPE"],
                    "fips": fips,
                    "begin": begin.strftime("%Y-%m-%dT%H:%MZ"),
                    "end": _event_time(r["END_DATE_TIME"], r["CZ_TIMEZONE"]).strftime("%Y-%m-%dT%H:%MZ"),
                    "deaths": int(r["DEATHS_DIRECT"] or 0) + int(r["DEATHS_INDIRECT"] or 0),
                    "injuries": int(r["INJURIES_DIRECT"] or 0) + int(r["INJURIES_INDIRECT"] or 0),
                    "damage_usd": _damage(r["DAMAGE_PROPERTY"]),
                }
            )
    events.sort(key=lambda e: (e["begin"], e["id"]))
    return {
        "meta": _meta(
            "NOAA NCEI Storm Events Database (details file 2024, c20261118)",
            "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/",
            "public domain (US federal work)",
            "events of 25-28 Sep 2024 in the SGW footprint counties (county events by FIPS, zone events by"
            " zone name); deaths and injuries direct + indirect; damage_usd = reported property damage",
        ),
        "events": events,
    }


def _meta(source: str, url: str, licence: str, fields: str) -> dict[str, str]:
    return {
        "source": source,
        "url": url,
        "licence": licence,
        "fields": fields,
        "window_start": WINDOW_START.strftime("%Y-%m-%dT%H:%MZ"),
        "built_by": "uv run python -I scripts/build_open_data.py",
    }


OUTPUTS = {
    "usgs_nwis/helene_gauges.json": "gauges",
    "iem_asos/helene_wind.json": "wind",
    "iem_vtec/helene_warnings.json": "warnings",
    "openfema/helene_declarations.json": "declarations",
    "ncei_storm_events/helene_events.json": "events",
}


def build_all(raw: Path = RAW_ROOT, out: Path = OUT_ROOT) -> dict[str, int]:
    area, counties = footprint()
    docs = {
        "gauges": build_gauges(raw, area),
        "wind": build_wind(raw),
        "warnings": build_warnings(raw, area),
        "declarations": build_declarations(raw, counties),
        "events": build_storm_events(raw, counties),
    }
    sizes: dict[str, int] = {}
    for rel, key in OUTPUTS.items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(docs[key], separators=(",", ":"), ensure_ascii=False) + "\n"
        path.write_text(body, encoding="utf-8", newline="\n")
        sizes[rel] = len(body.encode())
    return sizes
