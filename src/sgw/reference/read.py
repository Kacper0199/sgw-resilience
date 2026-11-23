"""Read side of the K1 reference tables for K3 `/api/regions` and `/api/assets` (map layers).

Only C0/C1 rows leave this module: C2 and above never reach these routes. The list withholds `criticality`
(null): a list of more than `policy_c3_aggregation_assets` assets that can be ranked by criticality is C3;
the single-asset read keeps it. An asset needs a geometry to be
listed (the K3 `Asset` carries a point); its point is `ST_PointOnSurface`, so lines and polygons get a
point on themselves, in microdegrees. Assets are filtered to those valid at the scenario time and paged by
`asset_id` (keyset), so a page is stable while the table grows elsewhere.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from sgw.contracts.api_models import Asset, Region
from sgw.contracts.vocab import Classification, Domain

PUBLIC_CLASSES = (Classification.C0.value, Classification.C1.value)
DEFAULT_LIMIT = 500
MAX_LIMIT = 1000

_REGIONS = """
SELECT region_id, state, county_fips, name,
       CASE WHEN geom IS NULL THEN NULL ELSE ARRAY[
           floor(ST_XMin(geom) * 1e6)::bigint, floor(ST_YMin(geom) * 1e6)::bigint,
           ceil(ST_XMax(geom) * 1e6)::bigint, ceil(ST_YMax(geom) * 1e6)::bigint] END AS bbox_e6
FROM region
ORDER BY region_id
"""

_ASSETS = """
SELECT asset_id, domain::text AS domain, kind, region_id,
       round(ST_X(pt) * 1e6)::bigint AS lon_e6, round(ST_Y(pt) * 1e6)::bigint AS lat_e6,
       criticality, critical_facility, customers_served, classification::text AS classification, name
FROM (
    SELECT a.*, ST_PointOnSurface(a.geom) AS pt
    FROM asset a
    WHERE a.geom IS NOT NULL
      AND a.classification::text = ANY(%(classes)s::text[])
      AND a.valid @> %(at)s::timestamptz
      AND (%(asset_id)s::text IS NULL OR a.asset_id = %(asset_id)s::text)
      AND (%(domain)s::text IS NULL OR a.domain::text = %(domain)s::text)
      AND (%(regions)s::text[] IS NULL OR a.region_id = ANY(%(regions)s::text[]))
      AND (%(after)s::text IS NULL OR a.asset_id > %(after)s::text)
      AND (%(x0)s::float8 IS NULL
           OR a.geom && ST_MakeEnvelope(%(x0)s::float8, %(y0)s::float8, %(x1)s::float8, %(y1)s::float8, 4326))
    ORDER BY a.asset_id
    LIMIT %(limit)s
) page
ORDER BY asset_id
"""


class InvalidQuery(ValueError):
    pass


@dataclass(frozen=True)
class Bbox:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


@dataclass(frozen=True)
class AssetQuery:
    at: datetime
    domain: Domain | None = None
    regions: tuple[str, ...] = ()
    bbox: Bbox | None = None
    limit: int = DEFAULT_LIMIT
    after: str | None = None


@dataclass(frozen=True)
class AssetPage:
    items: list[Asset]
    next_after: str | None


def parse_bbox(raw: str | None) -> Bbox | None:
    """`min_lon,min_lat,max_lon,max_lat` in degrees, WGS84; min not above max (no antimeridian crossing)."""
    if raw is None or raw == "":
        return None
    parts = raw.split(",")
    if len(parts) != 4:
        raise InvalidQuery("bbox needs four numbers: min_lon,min_lat,max_lon,max_lat")
    try:
        x0, y0, x1, y1 = (float(p) for p in parts)
    except ValueError as exc:
        raise InvalidQuery("bbox values must be numbers") from exc
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
        raise InvalidQuery("bbox values must be finite")
    if not (-180 <= x0 <= x1 <= 180 and -90 <= y0 <= y1 <= 90):
        raise InvalidQuery(
            "bbox must be min_lon <= max_lon within [-180, 180] and min_lat <= max_lat within [-90, 90]"
        )
    return Bbox(x0, y0, x1, y1)


def check_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidQuery(f"limit must be between 1 and {MAX_LIMIT}")
    return limit


async def _rows(
    conn: AsyncConnection[Any], query: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return await cur.fetchall()


async def list_regions(conn: AsyncConnection[Any]) -> list[Region]:
    rows = await _rows(conn, _REGIONS)
    return [Region(**{**r, "bbox_e6": tuple(r["bbox_e6"]) if r["bbox_e6"] else None}) for r in rows]


def _params(q: AssetQuery, *, asset_id: str | None, limit: int) -> dict[str, Any]:
    box = q.bbox
    return {
        "classes": list(PUBLIC_CLASSES),
        "at": q.at,
        "asset_id": asset_id,
        "domain": q.domain.value if q.domain else None,
        "regions": list(q.regions) or None,
        "after": q.after,
        "x0": box.min_lon if box else None,
        "y0": box.min_lat if box else None,
        "x1": box.max_lon if box else None,
        "y1": box.max_lat if box else None,
        "limit": limit,
    }


async def list_assets(conn: AsyncConnection[Any], q: AssetQuery) -> AssetPage:
    rows = await _rows(conn, _ASSETS, _params(q, asset_id=None, limit=q.limit + 1))
    items = [Asset(**{**r, "criticality": None}) for r in rows[: q.limit]]
    more = len(rows) > q.limit
    return AssetPage(items, items[-1].asset_id if more and items else None)


async def get_asset(conn: AsyncConnection[Any], asset_id: str, at: datetime) -> Asset | None:
    rows = await _rows(conn, _ASSETS, _params(AssetQuery(at=at), asset_id=asset_id, limit=1))
    return Asset(**rows[0]) if rows else None


def region_ids(raw: Sequence[str] | None) -> tuple[str, ...]:
    return tuple(sorted({r for r in raw or () if r}))
