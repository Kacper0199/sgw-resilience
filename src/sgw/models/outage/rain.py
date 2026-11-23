"""Observed rainfall per county and storm (experiment v2, diagnostic only; never on the serving path).

Source: Iowa Environmental Mesonet IEMRE daily gridded analysis (`daily_precip_in`), one request per county
centroid and storm covering the 14 days before the storm window and the window itself. Raw JSON responses
are cached under `raw/data/iem_iemre/` (git-ignored; `python -m sgw.models.outage.rain raw/data/iem_iemre`);
the derived table is `data/open/eaglei/county_storm_rain.csv`.
- `rain_window_mm`: sum over the calendar days of the storm window.
- `rain_antecedent_14d_mm`: sum over the 14 days before the window start (soil wetness proxy).
- WP-11v3: `rain_antecedent_30d_mm` (30 days before the window start; `county_storm_rain_ante30.csv`, raw
  cache `raw/data/iem_iemre_ante30/`), a sensitivity only. Antecedent rain is known before landfall, so it is
  servable; window rain needs a rainfall forecast and is not.
"""

from __future__ import annotations

import csv
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from sgw.generator.config import load_counties
from sgw.models.hazard.hurdat2 import EXTENDED_STORMS, OPEN_DIR
from sgw.models.outage.eaglei import storm_window

RAIN_CSV = OPEN_DIR / "county_storm_rain.csv"
URL = "https://mesonet.agron.iastate.edu/iemre/multiday/{start}/{end}/{lat:.4f}/{lon:.4f}/json"
ANTECEDENT_DAYS = 14
MM_PER_IN = 25.4
RAIN_FEATURES = ("rain_window_mm", "rain_antecedent_14d_mm")
ANTE30_CSV = OPEN_DIR / "county_storm_rain_ante30.csv"
ANTE30_DAYS = 30
WORKERS = 4


def _fetch(url: str, path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
                    path.write_bytes(resp.read())
                break
            except OSError:
                time.sleep(2.0 * (attempt + 1))
        else:
            raise RuntimeError(f"IEMRE request failed: {url}")
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def derive_rain(raw_dir: Path, out: Path = RAIN_CSV) -> int:
    """`raw_dir` caches one JSON response per county and storm (pass `<repo>/raw/data/iem_iemre`)."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    counties = load_counties()
    jobs = []
    for storm in EXTENDED_STORMS:
        start, end = storm_window(storm)
        w0, w1 = start.date(), end.date()
        a0 = w0 - timedelta(days=ANTECEDENT_DAYS)
        for c in counties:
            url = URL.format(start=a0, end=w1, lat=c.lat, lon=c.lon)
            jobs.append((storm.name, c.fips, w0, url, raw_dir / f"{storm.name}_{c.fips}.json"))

    def one(job: tuple[str, str, date, str, Path]) -> dict[str, object]:
        name, fips, w0, url, path = job
        rows = _fetch(url, path)
        window = antecedent = 0.0
        for r in rows:
            v = r.get("daily_precip_in")
            mm = float(str(v)) * MM_PER_IN if v is not None else 0.0
            if date.fromisoformat(str(r["date"])) >= w0:
                window += mm
            else:
                antecedent += mm
        return {
            "storm": name,
            "fips": fips,
            "rain_window_mm": round(window, 1),
            "rain_antecedent_14d_mm": round(antecedent, 1),
        }

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        rows = list(pool.map(one, jobs))
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=["storm", "fips", *RAIN_FEATURES], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def derive_antecedent_30d(raw_dir: Path, out: Path = ANTE30_CSV) -> int:
    """30-day antecedent rain per county and storm (`raw_dir`: `raw/data/iem_iemre_ante30`)."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    counties = load_counties()
    jobs = []
    for storm in EXTENDED_STORMS:
        w0 = storm_window(storm)[0].date()
        a0, a1 = w0 - timedelta(days=ANTE30_DAYS), w0 - timedelta(days=1)
        for c in counties:
            url = URL.format(start=a0, end=a1, lat=c.lat, lon=c.lon)
            jobs.append((storm.name, c.fips, url, raw_dir / f"{storm.name}_{c.fips}.json"))

    def one(job: tuple[str, str, str, Path]) -> dict[str, object]:
        name, fips, url, path = job
        total = 0.0
        for r in _fetch(url, path):
            v = r.get("daily_precip_in")
            total += float(str(v)) * MM_PER_IN if v is not None else 0.0
        return {"storm": name, "fips": fips, "rain_antecedent_30d_mm": round(total, 1)}

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        rows = list(pool.map(one, jobs))
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["storm", "fips", "rain_antecedent_30d_mm"], lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def load_rain(path: Path = RAIN_CSV) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"fips": str})


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 2 and sys.argv[2] == "ante30":
        print(derive_antecedent_30d(Path(sys.argv[1])))
    else:
        print(derive_rain(Path(sys.argv[1])))
