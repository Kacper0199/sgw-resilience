"""EAGLE-I 15-min county customers-out matrices for the surge detector.

Source: EAGLE-I (ORNL), figshare doi:10.6084/m9.figshare.24237376.v4, CC BY 4.0 (Brelsford et al. 2024).
Timestamps are UTC. A slot where no county of the extract reported is a feed gap (NaN); a county missing from
a slot that others reported counts as zero customers out (the descriptor does not tell zero from a county gap;
the convention of `sgw.models.outage.eaglei`). Duplicate rows of one county and slot are summed.

Seasons: the GA+SC May-Nov extracts for 2016-2023 and 2025, and the seven-state Aug-Oct 2024 extract (the only
2024 file on disk), cut to its GA and SC rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

GASC_YEARS = (2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2025)
SE_2024 = "eaglei_se_2024_aug-oct.csv.gz"
STATES = ("Georgia", "South Carolina")
HELENE_SERIES_START = pd.Timestamp("2024-09-12", tz="UTC")
HELENE_SERIES_END = pd.Timestamp("2024-10-05", tz="UTC")


@dataclass(frozen=True)
class Season:
    year: int
    path: Path
    start: pd.Timestamp
    end: pd.Timestamp


def seasons(raw_dir: Path) -> list[Season]:
    out = [
        Season(
            y,
            raw_dir / f"eaglei_gasc_{y}_may-nov.csv.gz",
            pd.Timestamp(f"{y}-05-01", tz="UTC"),
            pd.Timestamp(f"{y}-12-01", tz="UTC"),
        )
        for y in GASC_YEARS
    ]
    aug, nov = pd.Timestamp("2024-08-01", tz="UTC"), pd.Timestamp("2024-11-01", tz="UTC")
    out.append(Season(2024, raw_dir / SE_2024, aug, nov))
    return sorted(out, key=lambda s: s.year)


def read_rows(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(
        path,
        dtype={"fips_code": str},
        usecols=lambda c: c in ("fips_code", "county", "state", "customers_out", "sum", "run_start_time"),
    ).rename(columns={"sum": "customers_out"})
    if "state" in frame.columns:
        frame = frame[frame["state"].isin(STATES)]
    frame["fips_code"] = frame["fips_code"].str.zfill(5)
    frame["t"] = pd.to_datetime(frame["run_start_time"], utc=True)
    frame["customers_out"] = pd.to_numeric(frame["customers_out"], errors="coerce").fillna(0.0)
    return frame


def county_names(path: Path) -> dict[str, tuple[str, str]]:
    frame = read_rows(path).drop_duplicates("fips_code")
    abbrev = {"Georgia": "GA", "South Carolina": "SC"}
    rows = zip(frame["fips_code"], frame["county"], frame["state"], strict=True)
    return {f: (n, abbrev[s]) for f, n, s in rows}


def season_matrix(
    path: Path, fips: Sequence[str], start: pd.Timestamp, end: pd.Timestamp
) -> tuple[pd.DatetimeIndex, np.ndarray]:
    rows = read_rows(path)
    rows = rows[(rows["t"] >= start) & (rows["t"] < end)]
    times = pd.date_range(start, end, freq="15min", inclusive="left")
    reported = times.isin(pd.DatetimeIndex(rows["t"].unique()))
    wanted = rows[rows["fips_code"].isin(set(fips))]
    pivot = wanted.pivot_table(index="t", columns="fips_code", values="customers_out", aggfunc="sum")
    x = pivot.reindex(index=times, columns=list(fips)).fillna(0.0).to_numpy(dtype=float)
    x[~reported] = np.nan
    return times, x


def write_series(path: Path, times: pd.DatetimeIndex, x: np.ndarray, fips: Sequence[str]) -> None:
    frame = pd.DataFrame(x, columns=list(fips)).astype("Int64")
    frame.insert(0, "t_utc", times.strftime("%Y-%m-%dT%H:%MZ"))
    frame.to_csv(path, index=False, lineterminator="\n", compression={"method": "gzip", "mtime": 0})


def read_series(path: Path) -> tuple[pd.DatetimeIndex, np.ndarray, list[str]]:
    frame = pd.read_csv(path, dtype={"t_utc": str})
    times = pd.DatetimeIndex(pd.to_datetime(frame.pop("t_utc"), format="%Y-%m-%dT%H:%MZ", utc=True))
    return times, frame.to_numpy(dtype=float), [str(c).zfill(5) for c in frame.columns]
