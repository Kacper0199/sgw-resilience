"""Inputs of the ETR, sitrep and after-action graphs, read by code only.

- ETR estimates: WP-17's `EtrEstimate` (global + 11 operating areas, P10..P90 of the time to 90 percent of the
  peak customers out restored), from the latest `snapshot` of kind `etr` in the run's database, from a JSON
  lines file, or computed from the WP-17 serving artefact for the story of record.
- ETR caveat: the K17 coverage rows of `evals/reports/etr.json` (family-A synthetic storms).
- Replay status: customers out per county per hour from the committed Helene replay (`county_hourly.csv`).
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import psycopg

from sgw.models.restoration.publish import EtrEstimate

REPO_ROOT = Path(__file__).resolve().parents[3]
ETR_REPORT = REPO_ROOT / "evals" / "reports" / "etr.json"
COUNTY_HOURLY = REPO_ROOT / "data" / "fixtures" / "helene" / "county_hourly.csv"
OUTAGES = REPO_ROOT / "data" / "fixtures" / "helene" / "outages.csv"
NETWORK = REPO_ROOT / "data" / "fixtures" / "helene" / "network.json"
TREND_WINDOW = timedelta(hours=6)
TREND_DEADBAND = 0.02


def load_estimates(path: Path) -> list[EtrEstimate]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [EtrEstimate.model_validate_json(line) for line in lines if line.strip()]


def story_estimates(hours_after_peak: float = 24.0) -> list[EtrEstimate]:
    """WP-17's story-of-record estimates from the serving artefact (about 20 s; Monte Carlo)."""
    from sgw.models.restoration import artefact, publish

    model, cals, _ = artefact.load()
    return publish.estimates(publish.story_run(), hours_after_peak, model, cals)


def db_estimates(conn: psycopg.Connection[Any], as_of: datetime | None = None) -> list[EtrEstimate]:
    """The latest ETR publication of WP-17 (`snapshot` kind `etr`) issued at or before `as_of`."""
    sql = "SELECT output FROM snapshot WHERE kind = 'etr'"
    args: tuple[Any, ...] = ()
    if as_of is not None:
        sql += " AND as_of <= %s"
        args = (as_of,)
    row = conn.execute(sql + " ORDER BY as_of DESC LIMIT 1", args).fetchone()
    if row is None:
        return []
    return [EtrEstimate.model_validate(e) for e in row[0]]


@dataclass(frozen=True)
class EtrCaveat:
    """Out-of-sample coverage of the ETR intervals on family-A synthetic Helene-like storms (K17)."""

    issue_offset_h: int
    coverage80_ppm: int
    coverage50_ppm: int
    n_storms: int
    real_storm_checked: bool
    report: str


def etr_caveat(issue_offset_h: float = 24.0, path: Path = ETR_REPORT) -> EtrCaveat:
    offset = 0 if issue_offset_h < 12 else 24
    rows = {r["metric"]: r for r in json.loads(path.read_text(encoding="utf-8"))["metrics"]}
    key = f"etr90.family_a_test.global.issue_declared_peak_plus_{offset}h"
    c80, c50 = rows[f"{key}.coverage80"], rows[f"{key}.coverage50"]
    return EtrCaveat(
        issue_offset_h=offset,
        coverage80_ppm=round(float(c80["value"]) * 1_000_000),
        coverage50_ppm=round(float(c50["value"]) * 1_000_000),
        n_storms=int(c80["n"]),
        real_storm_checked=False,
        report=str(path.relative_to(REPO_ROOT)),
    )


@lru_cache(maxsize=2)
def _county_series(path: Path = COUNTY_HOURLY) -> dict[datetime, dict[str, int]]:
    out: dict[datetime, dict[str, int]] = defaultdict(dict)
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            at = datetime.fromisoformat(r["hour_utc"].replace("Z", "+00:00"))
            out[at][r["fips"]] = int(float(r["customers_out"]))
    return dict(out)


def county_series() -> dict[datetime, dict[str, int]]:
    """The replayed outage curve: hour -> county FIPS -> customers out (counties without outages omitted)."""
    return _county_series()


@dataclass(frozen=True)
class ReplayStatus:
    as_of: datetime
    customers_out_now: int
    peak_customers_out: int
    peak_at: datetime
    counties_out: int
    customers_out_before: int
    trend: str

    @property
    def restored_since_peak_ppm(self) -> int:
        if self.peak_customers_out <= 0:
            return 0
        return round((self.peak_customers_out - self.customers_out_now) / self.peak_customers_out * 1_000_000)


def replay_status(as_of: datetime, path: Path = COUNTY_HOURLY) -> ReplayStatus:
    """System status at `as_of` (the last whole hour at or before it) from the replayed outage curve."""
    series = _county_series(path)
    hours = sorted(t for t in series if t <= as_of.astimezone(UTC))
    if not hours:
        raise ValueError(f"no replay hour at or before {as_of.isoformat()}")
    now = hours[-1]
    totals = {t: sum(series[t].values()) for t in hours}
    peak_at = max(hours, key=lambda t: (totals[t], -t.timestamp()))
    before_at = max((t for t in hours if t <= now - TREND_WINDOW), default=hours[0])
    out_now, before = totals[now], totals[before_at]
    change = (out_now - before) / before if before else 0.0
    trend = "flat" if abs(change) <= TREND_DEADBAND else ("falling" if change < 0 else "rising")
    return ReplayStatus(
        as_of=now,
        customers_out_now=out_now,
        peak_customers_out=totals[peak_at],
        peak_at=peak_at,
        counties_out=sum(1 for v in series[now].values() if v > 0),
        customers_out_before=before,
        trend=trend,
    )


@lru_cache(maxsize=1)
def county_codes(path: Path = NETWORK) -> dict[str, str]:
    """FIPS -> the network's county code (registry ids of the Helene world)."""
    return dict(json.loads(path.read_text(encoding="utf-8"))["county_codes"])
