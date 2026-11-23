"""Builds the offline USA basemap (Natural Earth, public domain) and the Helene NHC cone/track file (NHC GIS
archive, US Government work) for the map.

usage: uv run python -I web/scripts/build_basemap.py <natural-earth dir> <nhc extract dir> <web dir>
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import geopandas as gpd
import shapefile
from shapely.geometry import box, shape

ne_dir, nhc_dir, web_dir = (Path(a) for a in sys.argv[1:4])
out = web_dir / "public/geo"
out.mkdir(parents=True, exist_ok=True)

CLIP = box(-102, 14, -58, 50)
SIMPLIFY = 0.012
MIN_LAKE_M2 = 3e9


def write(name: str, frame: gpd.GeoDataFrame) -> None:
    path = out / name
    frame.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=3)
    print(name, path.stat().st_size // 1024, "KB", len(frame), "features")


def clipped(frame: gpd.GeoDataFrame, tolerance: float) -> gpd.GeoDataFrame:
    frame = frame.copy()
    frame["geometry"] = frame.geometry.intersection(CLIP).simplify(tolerance, preserve_topology=True)
    return frame[~frame.geometry.is_empty]


land = gpd.read_file(ne_dir / "ne_10m_land.geojson")[["geometry"]]
write("land.geo.json", clipped(land, SIMPLIFY))

states = gpd.read_file(ne_dir / "ne_10m_admin_1_states_provinces.geojson")
states = states[states["iso_a2"] == "US"][["postal", "name", "geometry"]]
states = states.rename(columns={"postal": "abbr"})
states = states[states.geometry.intersects(CLIP)]
states = clipped(states, SIMPLIFY)
anchor = states.geometry.representative_point()
states["lon"] = anchor.x.round(2)
states["lat"] = anchor.y.round(2)
write("states.geo.json", states)

lakes = gpd.read_file(ne_dir / "ne_10m_lakes.geojson")[["geometry"]]
lakes = lakes[lakes.geometry.intersects(CLIP)]
lakes = lakes[lakes.geometry.to_crs(5070).area >= MIN_LAKE_M2]
write("lakes.geo.json", clipped(lakes, SIMPLIFY))

ZONE = {"EDT": -4, "CDT": -5}
ADVISORY = {
    5: "N-7",
    6: "N-6",
    7: "N-5",
    8: "N-4",
    9: "N-3",
    10: "N-2",
    11: "N-1",
    12: "N",
    13: "N+1",
    14: "N+2",
    15: "N+3",
    16: "N+4",
}


def issued_utc(advdate: str) -> datetime:
    hhmm, ampm, zone, _day, month, day, year = advdate.split()
    hour, minute = int(hhmm[:-2]), int(hhmm[-2:])
    hour = hour % 12 + (12 if ampm == "PM" else 0)
    local = datetime.strptime(f"{year} {month} {day}", "%Y %b %d").replace(hour=hour, minute=minute)
    return (local - timedelta(hours=ZONE[zone])).replace(tzinfo=UTC)


def simplify_ring(coords: list, tolerance: float) -> list:
    ring = shape({"type": "Polygon", "coordinates": [coords]}).simplify(tolerance, preserve_topology=True)
    return [[round(x, 3), round(y, 3)] for x, y in ring.exterior.coords]


products = {}
for number, label in ADVISORY.items():
    stem = nhc_dir / f"x_5day_{number:03d}" / f"al092024-{number:03d}_5day"
    cone = shapefile.Reader(f"{stem}_pgn")
    track = shapefile.Reader(f"{stem}_lin")
    pts = shapefile.Reader(f"{stem}_pts")
    meta = dict(zip([f[0] for f in cone.fields[1:]], cone.records()[0], strict=True))
    issued = issued_utc(meta["ADVDATE"])
    names = [f[0] for f in pts.fields[1:]]
    fixes = []
    for rec in pts.records():
        r = dict(zip(names, rec, strict=True))
        fixes.append([int(r["TAU"]), round(r["LAT"], 2), round(r["LON"], 2), int(r["MAXWIND"])])
    products[issued.strftime("%Y-%m-%dT%H:%M:%SZ")] = {
        "label": label,
        "nhc_advisory": int(meta["ADVISNUM"]),
        "cone": simplify_ring(cone.shape(0).points, 0.02),
        "track": [[round(x, 3), round(y, 3)] for x, y in track.shape(0).points],
        "fixes": fixes,
    }
(out / "helene-nhc.json").write_text(json.dumps(products, separators=(",", ":")), encoding="utf-8")
print("helene-nhc.json", (out / "helene-nhc.json").stat().st_size // 1024, "KB", len(products), "advisories")
