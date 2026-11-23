"""Builds the simplified county and coast layers for the thin map from public-domain Census TIGER data."""

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

root = Path(sys.argv[1])
zip_path = root / "raw/data/census_tiger/cb_2023_us_county_5m.zip"
footprint = pd.read_csv(root / "data/synthetic/footprint_counties.csv", dtype={"fips": str})
out = Path(__file__).resolve().parents[1] / "src/features/map/geo"

counties = gpd.read_file(f"zip://{zip_path}")
counties = counties[counties["GEOID"].isin(footprint["fips"])][["GEOID", "NAME", "STUSPS", "geometry"]]
counties = counties.rename(columns={"GEOID": "fips", "NAME": "name", "STUSPS": "state"})
counties["geometry"] = counties.geometry.simplify(0.004, preserve_topology=True)
counties.to_file(out / "counties.geo.json", driver="GeoJSON", COORDINATE_PRECISION=4)
(root / "data/reference/counties.geo.json").write_bytes((out / "counties.geo.json").read_bytes())

land = gpd.GeoSeries([counties.geometry.union_all()], crs=counties.crs)
land.to_file(out / "footprint.geo.json", driver="GeoJSON", COORDINATE_PRECISION=4)
coast = gpd.GeoSeries([land.iloc[0].boundary], crs=counties.crs)
coast.to_file(out / "coast.geo.json", driver="GeoJSON", COORDINATE_PRECISION=4)
print(len(counties), "counties")
