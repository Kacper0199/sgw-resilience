"""Observed ASOS peak gusts per storm and station (WP-11v3; label-free check and calibration of the A1 wind).

Source: Iowa Environmental Mesonet ASOS archive (public NWS/FAA METAR observations), networks GA_ASOS and
SC_ASOS, every station, each storm's outage-label window. Raw responses are cached under
`raw/data/iem_asos/storms/` (git-ignored); the derived table is `data/open/eaglei/asos_storm_peak_gust.csv`.

Per station and storm: observed peak = max of `gust`, `peak_wind_gust` and `sknt` (kt to m/s; a sustained
reading bounds the gust from below), the share of hours with a report in [closest approach - 24 h, + 24 h],
the modelled features at the station from `point_features` (the same function as the outage model), and the
station's distance to the coast (`sgw.models.outage.county_static`, needs `raw/data/census_tiger/`).
"""

from __future__ import annotations

import csv
import json
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sgw.generator.wind import KT, distance_km
from sgw.models.hazard.field import Points, point_features
from sgw.models.hazard.hurdat2 import EXTENDED_STORMS, OPEN_DIR, Storm, load_track

NETWORKS = ("GA_ASOS", "SC_ASOS")
STATIONS_URL = "https://mesonet.agron.iastate.edu/geojson/network/{network}.geojson"
ASOS_URL = (
    "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?{stations}&data=sknt&data=gust"
    "&data=peak_wind_gust&year1={a.year}&month1={a.month}&day1={a.day}&hour1={a.hour}&minute1=0"
    "&year2={b.year}&month2={b.month}&day2={b.day}&hour2={b.hour}&minute2=0&tz=Etc/UTC&format=onlycomma"
    "&latlon=yes&missing=empty&trace=empty&direct=no&report_type=3&report_type=4"
)
ASOS_CSV = OPEN_DIR / "asos_storm_peak_gust.csv"
REPORT_HALF_WINDOW_H = 24
COLUMNS = (
    "storm",
    "station",
    "network",
    "lat",
    "lon",
    "obs_peak_gust_ms",
    "report_share",
    "closest_utc",
    "peak_gust_ms",
    "hours_gust_ge_20",
    "vmax_ms_closest",
    "speed_kmh_closest",
    "min_dist_km",
    "dist_coast_km",
)


def _get(url: str, path: Path) -> bytes:
    if not path.is_file():
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=180) as resp:  # noqa: S310
                    path.write_bytes(resp.read())
                break
            except OSError:
                time.sleep(5.0 * (attempt + 1))
        else:
            raise RuntimeError(f"IEM request failed: {url}")
    return path.read_bytes()


def stations(raw_dir: Path) -> pd.DataFrame:
    rows = []
    for network in NETWORKS:
        data = json.loads(_get(STATIONS_URL.format(network=network), raw_dir / f"stations_{network}.geojson"))
        for f in data["features"]:
            lon, lat = f["geometry"]["coordinates"]
            rows.append({"station": f["properties"]["sid"], "network": network, "lat": lat, "lon": lon})
    return pd.DataFrame(rows).drop_duplicates("station").reset_index(drop=True)


def fetch_storm(
    storm: Storm, meta: pd.DataFrame, raw_dir: Path, start: datetime, end: datetime
) -> pd.DataFrame:
    frames = []
    for network in NETWORKS:
        ids = meta.loc[meta["network"] == network, "station"]
        url = ASOS_URL.format(stations="&".join(f"station={s}" for s in ids), a=start, b=end)
        path = raw_dir / f"{storm.name}_{network}.csv"
        _get(url, path)
        frames.append(pd.read_csv(path, dtype={"station": str}))
    return pd.concat(frames, ignore_index=True)


def summarise_storm(storm: Storm, obs: pd.DataFrame, meta: pd.DataFrame) -> list[dict[str, object]]:
    obs = obs.copy()
    obs["t"] = pd.to_datetime(obs["valid"], utc=True)
    values = obs[["gust", "peak_wind_gust", "sknt"]].apply(pd.to_numeric, errors="coerce")
    obs["g"] = values.max(axis=1) * KT
    track = load_track(storm.name)
    seen = meta[meta["station"].isin(obs["station"].unique())].reset_index(drop=True)
    if seen.empty:
        return []
    pts = Points(ids=tuple(seen["station"]), lat=seen["lat"].to_numpy(), lon=seen["lon"].to_numpy())
    feats = point_features(track, pts).set_index("point_id")
    active = track.vmax > 0
    d = distance_km(
        track.lat[active][:, None], track.lon[active][:, None], pts.lat[None, :], pts.lon[None, :]
    )
    t_close = track.t[active][np.argmin(d, axis=0)]
    rows = []
    for i, st in enumerate(seen.itertuples()):
        o = obs[obs["station"] == st.station]
        tc = datetime.fromtimestamp(float(t_close[i]), tz=UTC)
        lo, hi = tc - timedelta(hours=REPORT_HALF_WINDOW_H), tc + timedelta(hours=REPORT_HALF_WINDOW_H)
        near = o[(o["t"] >= lo) & (o["t"] < hi) & o["g"].notna()]
        hours = near["t"].dt.floor("h").nunique()
        f = feats.loc[st.station]
        peak = o["g"].max()
        rows.append(
            {
                "storm": storm.name,
                "station": st.station,
                "network": st.network,
                "lat": round(float(st.lat), 4),
                "lon": round(float(st.lon), 4),
                "obs_peak_gust_ms": round(float(peak), 2) if pd.notna(peak) else "",
                "report_share": round(hours / (2 * REPORT_HALF_WINDOW_H), 3),
                "closest_utc": tc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "peak_gust_ms": round(float(f["peak_gust_ms"]), 3),
                "hours_gust_ge_20": round(float(f["hours_gust_ge_20"]), 2),
                "vmax_ms_closest": round(float(f["vmax_ms_closest"]), 3),
                "speed_kmh_closest": round(float(f["speed_kmh_closest"]), 3),
                "min_dist_km": round(float(f["min_dist_km"]), 1),
            }
        )
    return rows


def derive_asos(raw_dir: Path, out: Path = ASOS_CSV) -> int:
    """`raw_dir` caches the station lists and one CSV per storm and network (`raw/data/iem_asos/storms`)."""
    from sgw.models.outage.eaglei import storm_window

    raw_dir.mkdir(parents=True, exist_ok=True)
    meta = stations(raw_dir)
    rows: list[dict[str, Any]] = []
    for storm in EXTENDED_STORMS:
        start, end = storm_window(storm)
        rows += summarise_storm(storm, fetch_storm(storm, meta, raw_dir, start, end), meta)
    from sgw.models.outage.county_static import coast_distance_km

    lat = np.array([float(r["lat"]) for r in rows])
    lon = np.array([float(r["lon"]) for r in rows])
    for r, d in zip(rows, coast_distance_km(lat, lon, raw_dir.parents[1]), strict=True):
        r["dist_coast_km"] = round(float(d), 2)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def load_asos(path: Path = ASOS_CSV) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"station": str})


if __name__ == "__main__":
    import sys

    print(derive_asos(Path(sys.argv[1])))
