"""Static county covariates for the WP-11v3 outage experiments (servable: known before any storm).

- `land_km2`: TIGER cartographic boundary 2023 (1:5m) `ALAND`, US Census Bureau, public domain.
- `customer_density`: EAGLE-I MCC customers per land km2 (exposure beside log customers).
- `dist_coast_km`: distance from the county centroid used by the hazard features to the coast, taken as the
  boundary of the union of the contiguous-US counties of the same file (shoreline-clipped), in EPSG:5070.
- `ep_mobile`: CDC/ATSDR SVI 2022 county share of mobile homes (percent).

Rebuild: `uv run python -m sgw.models.outage.county_static <raw/data>` (needs `census_tiger/` and `cdc_svi/`).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from sgw.generator.config import load_counties
from sgw.models.hazard.hurdat2 import OPEN_DIR

STATIC_CSV = OPEN_DIR / "county_static.csv"
TIGER_ZIP = "census_tiger/cb_2023_us_county_5m.zip"
SVI_CSV = "cdc_svi/SVI_2022_US_county.csv"
NON_CONTIGUOUS = {"02", "15", "60", "66", "69", "72", "78"}
EQUAL_AREA = "EPSG:5070"


@lru_cache(maxsize=1)
def _coast(raw_dir: str):  # type: ignore[no-untyped-def]
    import geopandas as gpd
    from shapely.ops import unary_union

    gdf = gpd.read_file(f"zip://{Path(raw_dir) / TIGER_ZIP}")
    gdf = gdf[~gdf["STATEFP"].isin(NON_CONTIGUOUS)].to_crs(EQUAL_AREA)
    return gdf, unary_union(gdf.geometry.buffer(50.0)).boundary


def coast_distance_km(lat: np.ndarray, lon: np.ndarray, raw_dir: Path) -> np.ndarray:
    import geopandas as gpd

    _, coast = _coast(str(raw_dir))
    pts = gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs="EPSG:4326").to_crs(EQUAL_AREA)
    return np.array([coast.distance(p) / 1000.0 for p in pts])


def derive_static(raw_dir: Path, out: Path = STATIC_CSV) -> pd.DataFrame:
    from sgw.models.outage.eaglei import read_mcc

    counties = load_counties()
    gdf, _ = _coast(str(raw_dir))
    land = gdf.set_index("GEOID")["ALAND"].astype(float) / 1e6
    svi = pd.read_csv(raw_dir / SVI_CSV, dtype={"FIPS": str}, encoding="utf-8-sig").set_index("FIPS")
    mcc = read_mcc(raw_dir / "eaglei" / "MCC.csv")
    fips = [c.fips for c in counties]
    lat = np.array([c.lat for c in counties])
    lon = np.array([c.lon for c in counties])
    frame = pd.DataFrame(
        {
            "fips": fips,
            "land_km2": [round(float(land[f]), 2) for f in fips],
            "customers_mcc": [mcc[f] for f in fips],
            "dist_coast_km": np.round(coast_distance_km(lat, lon, raw_dir), 2),
            "ep_mobile": [float(svi.loc[f, "EP_MOBILE"]) for f in fips],
        }
    )
    frame["customer_density"] = (frame["customers_mcc"] / frame["land_km2"]).round(3)
    frame = frame.drop(columns="customers_mcc")
    frame.to_csv(out, index=False, lineterminator="\n")
    return frame


def load_static(path: Path = STATIC_CSV) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"fips": str})


if __name__ == "__main__":
    import sys

    print(derive_static(Path(sys.argv[1])).describe().round(2).to_string())
