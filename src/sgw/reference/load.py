"""Map reference rows for the demo (`sgw seed --demo`): county geometry for every footprint region and the
located synthetic assets of the Helene detail area, so `/api/regions` and `/api/assets` have data.

Sources (both already in the repository):
- County outlines: `data/reference/counties.geo.json`, the same file as the web map layer
  (`web/src/features/map/geo/counties.geo.json`, a test keeps the two identical), built by
  `web/scripts/build_geo.py` from the public-domain Census TIGER cartographic boundaries
  (`cb_2023_us_county_5m`), simplified.
- Asset points: the `named` block of `data/synthetic/helene.yaml` (the generator's source of truth, read
  only).
  Three kinds have no point of their own there. They are placed at a fixed offset from a linked asset so the
  PS-17 chain (fuel depot -> portable generator -> PS-17 -> pressure zone -> hospital) reads west to east on
  the map instead of stacking: a pressure zone 2.5 km north-east of its pump station, the fuel depot 2 km
  west of the generator parked there, the hospital 2 km east of the zone it is served from. Each such row
  records `location_from`, `location_offset_m`, `location_bearing_deg` and `location_basis` ("assumed for
  the map").

Idempotent: regions and assets are upserted by id. An existing asset keeps its geometry, name, customers
and every attribute key it already has; the loader only fills a missing geometry, name or attribute key, so
approval inputs and positions set by anyone else never change.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import yaml
from psycopg.types.json import Jsonb

REPO_ROOT = Path(__file__).resolve().parents[3]
COUNTIES_PATH = REPO_ROOT / "data" / "reference" / "counties.geo.json"
WEB_COUNTIES_PATH = REPO_ROOT / "web" / "src" / "features" / "map" / "geo" / "counties.geo.json"
WORLD_PATH = REPO_ROOT / "data" / "synthetic" / "helene.yaml"
COUNTY_SOURCE = "Census TIGER cb_2023_us_county_5m (public domain), simplified"
WORLD_SOURCE = "data/synthetic/helene.yaml named assets (synthetic)"
ASSUMED_BASIS = "assumed for the map"
EARTH_RADIUS_M = 6_371_000.0
ZONE_OFFSET = (2500, 60)
DEPOT_OFFSET = (2000, 270)
HOSPITAL_OFFSET = (2000, 90)


@dataclass(frozen=True)
class PlacedAsset:
    asset_id: str
    domain: str
    kind: str
    name: str
    lon: float
    lat: float
    fips: str | None = None
    location_from: str | None = None
    critical_facility: bool = False
    offset_m: int | None = None
    bearing_deg: int | None = None

    def attributes(self) -> dict[str, Any]:
        out: dict[str, Any] = {"synthetic": True, "location_source": WORLD_SOURCE}
        if self.location_from:
            out |= {
                "location_from": self.location_from,
                "location_offset_m": self.offset_m,
                "location_bearing_deg": self.bearing_deg,
                "location_basis": ASSUMED_BASIS,
            }
        return out


def offset(lon: float, lat: float, distance_m: float, bearing_deg: float) -> tuple[float, float]:
    """Point `distance_m` from (lon, lat) on the initial bearing (spherical earth), rounded to 1e-6 degree."""
    d = distance_m / EARTH_RADIUS_M
    b, p1, l1 = math.radians(bearing_deg), math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return round(math.degrees(l2), 6), round(math.degrees(p2), 6)


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Haversine distance between two (lon, lat) points in metres."""
    (l1, p1), (l2, p2) = (tuple(map(math.radians, a)), tuple(map(math.radians, b)))
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def _linked(
    asset_id: str,
    domain: str,
    kind: str,
    name: str,
    anchor: tuple[str, float, float],
    rule: tuple[int, int],
    *,
    critical: bool = False,
) -> PlacedAsset:
    origin, lon, lat = anchor
    x, y = offset(lon, lat, *rule)
    return PlacedAsset(
        asset_id,
        domain,
        kind,
        name,
        x,
        y,
        location_from=origin,
        critical_facility=critical,
        offset_m=rule[0],
        bearing_deg=rule[1],
    )


@dataclass(frozen=True)
class MapReferenceReport:
    regions: int
    assets: int


def missing_sources() -> list[Path]:
    """Source files the loader needs that are not on disk (checked before the demo seed starts)."""
    return [p for p in (COUNTIES_PATH, WORLD_PATH) if not p.is_file()]


def county_features(path: Path = COUNTIES_PATH) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["features"]
    return features


def placed_assets(path: Path = WORLD_PATH) -> list[PlacedAsset]:
    named = yaml.safe_load(path.read_text(encoding="utf-8"))["named"]
    out: list[PlacedAsset] = []
    sub = named["substation"]
    out.append(
        PlacedAsset(
            sub["id"],
            "electric",
            "substation",
            f"Substation {sub['id']} (synthetic)",
            sub["lon"],
            sub["lat"],
            sub["fips"],
        )
    )
    for fid, f in sorted(named["feeders"].items()):
        out.append(PlacedAsset(fid, "electric", "feeder", f"Feeder {fid} (synthetic)", f["lon"], f["lat"]))
    zones: dict[str, PlacedAsset] = {}
    for pid, p in sorted(named["pump_stations"].items()):
        out.append(
            PlacedAsset(pid, "water", "pump_station", f"Pump station {pid} (synthetic)", p["lon"], p["lat"])
        )
        zone = _linked(
            p["zone"],
            "water",
            "pressure_zone",
            f"Pressure zone {p['zone']} (synthetic)",
            (pid, p["lon"], p["lat"]),
            ZONE_OFFSET,
        )
        out.append(zone)
        zones[zone.asset_id] = zone
    gen = named["portable_generator"]
    out.append(
        PlacedAsset(
            gen["id"],
            "water",
            "portable_generator",
            f"Portable generator {gen['id']} (synthetic)",
            gen["lon"],
            gen["lat"],
        )
    )
    out.append(
        _linked(
            gen["depot"],
            "water",
            "fuel_depot",
            f"Fuel depot {gen['depot']} (synthetic)",
            (gen["id"], gen["lon"], gen["lat"]),
            DEPOT_OFFSET,
        )
    )
    hsp = named["hospital"]
    zone = zones[hsp["zone"]]
    out.append(
        _linked(
            hsp["id"],
            "water",
            "critical_customer",
            f"Hospital {hsp['id']} (synthetic)",
            (zone.asset_id, zone.lon, zone.lat),
            HOSPITAL_OFFSET,
            critical=True,
        )
    )
    for yid, y in sorted(named["yards"].items()):
        out.append(
            PlacedAsset(
                yid,
                "electric",
                "staging_yard",
                f"Staging yard {yid} (synthetic)",
                y["lon"],
                y["lat"],
                y["fips"],
            )
        )
    return out


_REGION = """
INSERT INTO region (region_id, state, county_fips, name, geom)
VALUES (%(region_id)s, %(state)s, %(fips)s, %(name)s,
        ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326)))
ON CONFLICT (region_id) DO UPDATE SET geom = EXCLUDED.geom
"""

_ASSET = """
WITH pt AS (SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326) AS g)
INSERT INTO asset (asset_id, domain, kind, region_id, name, geom, critical_facility, attributes)
SELECT %(asset_id)s, %(domain)s, %(kind)s,
       coalesce(
           (SELECT region_id FROM region WHERE county_fips = %(fips)s::text ORDER BY region_id LIMIT 1),
           (SELECT r.region_id FROM region r, pt WHERE ST_Covers(r.geom, pt.g) ORDER BY r.region_id LIMIT 1)),
       %(name)s, pt.g, %(critical)s, %(attributes)s
FROM pt
ON CONFLICT (asset_id) DO UPDATE SET
    geom = coalesce(asset.geom, EXCLUDED.geom),
    name = coalesce(asset.name, EXCLUDED.name),
    attributes = EXCLUDED.attributes || asset.attributes
"""


def region_id(state: str, fips: str) -> str:
    return f"{state}-{fips}"


def load_map_reference(conn: psycopg.Connection[Any]) -> MapReferenceReport:
    features = county_features()
    assets = placed_assets()
    with conn.transaction():
        for f in features:
            props = f["properties"]
            conn.execute(
                _REGION,
                {
                    "region_id": region_id(props["state"], props["fips"]),
                    "state": props["state"],
                    "fips": props["fips"],
                    "name": f"{props['name']} County",
                    "geometry": json.dumps(f["geometry"]),
                },
            )
        for a in assets:
            conn.execute(
                _ASSET,
                {
                    "asset_id": a.asset_id,
                    "domain": a.domain,
                    "kind": a.kind,
                    "name": a.name,
                    "lon": a.lon,
                    "lat": a.lat,
                    "fips": a.fips,
                    "critical": a.critical_facility,
                    "attributes": Jsonb(a.attributes()),
                },
            )
    return MapReferenceReport(regions=len(features), assets=len(assets))
