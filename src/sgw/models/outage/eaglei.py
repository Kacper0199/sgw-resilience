"""EAGLE-I county outages for the backtest storms: derived target tables (A2 real labels).

`county_storm_outages.csv` keeps the four WP-11 storms from their original slices (byte-identical);
`county_storm_outages_extended.csv` adds every storm of `EXTENDED_STORMS` (WP-11v2), the new ones from GA+SC
May-Nov extracts of the yearly files.

Source: EAGLE-I (ORNL), figshare doi:10.6084/m9.figshare.24237376.v4, CC BY 4.0 (Brelsford et al. 2024,
Scientific Data). The 2023 file names the count column `sum` (read as `customers_out`). Timestamps are UTC;
a missing 15-min row means zero customers out or a collection gap (the descriptor does not distinguish), so
missing rows (and empty counts, seen in older years) count as zero. Denominator: EAGLE-I `MCC.csv`
(modelled 2022 customers per county), never `total_customers`.

Storm window: from 12 h before the storm centre first comes within `WINDOW_KM` of a footprint county to 72 h
after it last is; the pre-storm level is the median over the 72 h before the window and is subtracted.
Target: `peak_frac` = (window peak - pre-storm level) / MCC customers, cut to [0, 1] (`frac_capped` = 1 when
cut; EAGLE-I peaks above MCC exist, R03 V-data-03).
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from sgw.generator.config import load_counties
from sgw.generator.wind import distance_km
from sgw.models.hazard.hurdat2 import EXTENDED_STORMS, OPEN_DIR, STORMS, Storm, load_track

TARGETS_CSV = OPEN_DIR / "county_storm_outages.csv"
EXTENDED_CSV = OPEN_DIR / "county_storm_outages_extended.csv"
MANIFEST_JSON = OPEN_DIR / "manifest.json"
WINDOW_KM = 600.0
LEAD_H = 12
TAIL_H = 72
PRE_H = 72
FIGSHARE_DOI = "10.6084/m9.figshare.24237376.v4"
FIGSHARE_FILES = {
    2016: "42547825",
    2017: "42547828",
    2018: "42547879",
    2019: "42547885",
    2020: "42547894",
    2021: "42547891",
    2022: "42547897",
    2023: "44574907",
    2024: "53581661",
    2025: "62164877",
}
RAW_FILES = {
    2018: "eaglei_se_2018_sep-oct.csv.gz",
    2022: "eaglei_se_2022_sep-oct.csv.gz",
    2024: "eaglei_se_2024_aug-oct.csv.gz",
}
EXTENDED_YEARS = (2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2025)


def raw_file(storm: Storm) -> str:
    """WP-11 storms keep their original slices; the others read the GA+SC May-Nov extract of their year."""
    if storm in STORMS or storm.year not in EXTENDED_YEARS:
        return RAW_FILES[storm.year]
    return f"eaglei_gasc_{storm.year}_may-nov.csv.gz"


COLUMNS = (
    "storm",
    "fips",
    "window_start_utc",
    "window_end_utc",
    "pre_storm_out",
    "peak_out",
    "peak_excess",
    "peak_time_utc",
    "customer_hours",
    "customers_mcc",
    "peak_frac",
    "frac_capped",
    "rows",
)


def storm_window(storm: Storm) -> tuple[datetime, datetime]:
    track = load_track(storm.name)
    counties = load_counties()
    lat = np.array([c.lat for c in counties])
    lon = np.array([c.lon for c in counties])
    d = distance_km(track.lat[:, None], track.lon[:, None], lat[None, :], lon[None, :]).min(axis=1)
    near = np.flatnonzero(d <= WINDOW_KM)
    if not len(near):
        raise ValueError(f"{storm.name} never comes within {WINDOW_KM} km of the footprint")
    first = datetime.fromtimestamp(track.t[near[0]], tz=UTC) - timedelta(hours=LEAD_H)
    last = datetime.fromtimestamp(track.t[near[-1]], tz=UTC) + timedelta(hours=TAIL_H)
    return first, last


def read_mcc(path: Path) -> dict[str, int]:
    with path.open(encoding="utf-8-sig") as fh:
        return {r["County_FIPS"].zfill(5): int(float(r["Customers"])) for r in csv.DictReader(fh)}


def read_raw(path: Path, fips: Iterable[str], start: datetime, end: datetime) -> pd.DataFrame:
    wanted = set(fips)
    frame = pd.read_csv(
        path,
        dtype={"fips_code": str},
        usecols=lambda c: c in ("fips_code", "customers_out", "sum", "run_start_time"),
    ).rename(columns={"sum": "customers_out"})
    frame["fips_code"] = frame["fips_code"].str.zfill(5)
    frame = frame[frame["fips_code"].isin(wanted)]
    frame["t"] = pd.to_datetime(frame["run_start_time"], utc=True)
    return frame[(frame["t"] >= start) & (frame["t"] < end)][["fips_code", "t", "customers_out"]]


def derive_storm(storm: Storm, raw_dir: Path, mcc: dict[str, int]) -> list[dict[str, object]]:
    counties = load_counties()
    fips = [c.fips for c in counties]
    start, end = storm_window(storm)
    pre_start = start - timedelta(hours=PRE_H)
    raw = read_raw(raw_dir / raw_file(storm), fips, pre_start, end)
    grid = pd.date_range(pre_start, end, freq="15min", inclusive="left", tz=UTC)
    rows: list[dict[str, object]] = []
    for f in fips:
        series = (
            raw[raw["fips_code"] == f]
            .groupby("t")["customers_out"]
            .max()
            .reindex(grid, fill_value=0)
            .astype(float)
            .fillna(0.0)
        )
        pre = float(series[series.index < start].median())
        storm_part = series[series.index >= start]
        excess = (storm_part - pre).clip(lower=0.0)
        peak_out = float(storm_part.max())
        peak_excess = float(excess.max())
        customers = mcc[f]
        frac = peak_excess / customers if customers else 0.0
        rows.append(
            {
                "storm": storm.name,
                "fips": f,
                "window_start_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "window_end_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "pre_storm_out": round(pre, 1),
                "peak_out": int(peak_out),
                "peak_excess": int(round(peak_excess)),
                "peak_time_utc": storm_part.idxmax().strftime("%Y-%m-%dT%H:%M:%SZ") if peak_out > 0 else "",
                "customer_hours": round(float(excess.sum()) * 0.25, 1),
                "customers_mcc": customers,
                "peak_frac": round(min(frac, 1.0), 6),
                "frac_capped": int(frac > 1.0),
                "rows": int((raw["fips_code"] == f).sum()),
            }
        )
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def derive(raw_dir: Path, hurdat2_path: Path | None = None, out_dir: Path = OPEN_DIR) -> dict[str, object]:
    """Rebuild the committed table from the raw extracts; returns the manifest."""
    if hurdat2_path is not None:
        from sgw.models.hazard.hurdat2 import write_tracks

        write_tracks(hurdat2_path, out_dir / "storm_tracks.csv")
    mcc = read_mcc(raw_dir / "MCC.csv")
    by_storm = {storm.name: derive_storm(storm, raw_dir, mcc) for storm in EXTENDED_STORMS}
    rows = [row for storm in STORMS for row in by_storm[storm.name]]
    extended = [row for storm in EXTENDED_STORMS for row in by_storm[storm.name]]
    out = out_dir / TARGETS_CSV.name
    for path, table in ((out, rows), (out_dir / EXTENDED_CSV.name, extended)):
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(table)
    raw_names = sorted({raw_file(s) for s in EXTENDED_STORMS})
    inputs = {name: sha256_file(raw_dir / name) for name in [*raw_names, "MCC.csv"]}
    if hurdat2_path is not None:
        inputs[hurdat2_path.name] = sha256_file(hurdat2_path)
    manifest: dict[str, object] = {
        "dataset": "eaglei_county_storm_outages",
        "label": "C (own aggregation of EAGLE-I; not a utility or DOE figure)",
        "source": f"EAGLE-I, ORNL, figshare doi:{FIGSHARE_DOI}",
        "licence": "CC BY 4.0",
        "figshare_files": FIGSHARE_FILES,
        "hurdat2": "NHC HURDAT2 hurdat2-1851-2025-092326.txt (US federal work, public domain)",
        "derived_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs_sha256": inputs,
        "outputs_sha256": {
            p.name: sha256_file(p)
            for p in (out, out_dir / EXTENDED_CSV.name, out_dir / "storm_tracks.csv")
            if p.is_file()
        },
        "rows": len(rows),
        "rows_extended": len(extended),
        "storms_extended": [s.name for s in EXTENDED_STORMS],
        "method": __doc__,
    }
    (out_dir / MANIFEST_JSON.name).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_targets(path: Path = TARGETS_CSV) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"fips": str})


def load_extended_targets(path: Path = EXTENDED_CSV) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"fips": str})
