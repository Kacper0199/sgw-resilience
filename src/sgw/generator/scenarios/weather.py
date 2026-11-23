"""Real station weather for the second-tier scenarios (ASOS, Iowa Environmental Mesonet, public METAR data).

Committed extracts, derived once from the R05 download with
`python -m sgw.generator.scenarios derive-weather --raw <asos_hourly_5stn_2023-01_2025-03.csv>`:

- `data/fixtures/tablerock/asos_gsp_hourly.csv`: Greenville-Spartanburg (GSP) routine hourly observations
  2023-01-01..2025-03-31 UTC (temperature, dew point, wind, gust, hourly precipitation), the single weather
  truth for KBDI spin-up, FFWI climatology, the Table Rock window and the blue-sky fire check.
- `data/fixtures/heat/asos_5stn_daily.csv`: daily (Eastern local date) Tmax/Tmean per station for CAE, GSP,
  SAV, AGS, CHS, May-September 2023 and 2024 (trigger calibration on 2023, evaluation on 2024).
- `data/fixtures/heat/asos_ags_hourly_heatwave.csv`: Augusta (AGS, nearest station to the Aiken detail area)
  hourly 2024-07-08..2024-07-20 UTC, ambient for the transformer and conductor models.

Units at the boundary: temperatures in degrees C, wind in m/s, precipitation in mm; all times UTC.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURES = REPO_ROOT / "data" / "fixtures"
GSP_HOURLY = FIXTURES / "tablerock" / "asos_gsp_hourly.csv"
STATIONS_DAILY = FIXTURES / "heat" / "asos_5stn_daily.csv"
AGS_HOURLY = FIXTURES / "heat" / "asos_ags_hourly_heatwave.csv"
EASTERN = ZoneInfo("America/New_York")
STATIONS = ("AGS", "CAE", "CHS", "GSP", "SAV")
KT_TO_MS = 0.514444
IN_TO_MM = 25.4
TRACE_IN = 0.001
HOURLY_HEADER = ("valid_utc", "t_c", "td_c", "wind_ms", "gust_ms", "precip_mm")
DAILY_HEADER = ("station", "date_local", "tmax_c", "tmean_c", "n_obs")


@dataclass(frozen=True)
class HourlyObs:
    t: datetime
    t_c: float
    td_c: float
    wind_ms: float
    gust_ms: float | None
    precip_mm: float

    @property
    def rh_pct(self) -> float:
        return relative_humidity(self.t_c, self.td_c)


@dataclass(frozen=True)
class DailyObs:
    station: str
    day: date
    tmax_c: float
    tmean_c: float
    n_obs: int


def relative_humidity(t_c: float, td_c: float) -> float:
    """Magnus form (Alduchov and Eskridge coefficients), clipped to 0..100 %."""
    rh = 100.0 * math.exp(17.625 * td_c / (243.04 + td_c)) / math.exp(17.625 * t_c / (243.04 + t_c))
    return min(100.0, max(0.0, rh))


def f_to_c(f: float) -> float:
    return (f - 32.0) / 1.8


def _num(text: str) -> float | None:
    text = text.strip()
    if text in ("", "M"):
        return None
    if text == "T":
        return TRACE_IN
    return float(text)


def _parse_raw(raw: Path) -> dict[str, list[tuple[datetime, dict[str, float | None]]]]:
    rows: dict[str, list[tuple[datetime, dict[str, float | None]]]] = defaultdict(list)
    with raw.open(newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            if rec["station"] not in STATIONS:
                continue
            t = datetime.strptime(rec["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            rows[rec["station"]].append(
                (t, {k: _num(rec[k]) for k in ("tmpf", "dwpf", "sknt", "gust", "p01i")})
            )
    return rows


def _hourly(obs: Iterable[tuple[datetime, dict[str, float | None]]]) -> list[list[str]]:
    """One routine observation per UTC hour (the latest in the hour); rows without temperature, dew point or
    wind are dropped (0.01-0.24 % of hours, R05)."""
    by_hour: dict[datetime, dict[str, float | None]] = {}
    for t, v in sorted(obs, key=lambda x: x[0]):
        by_hour[t.replace(minute=0)] = v
    out: list[list[str]] = []
    for hour, v in sorted(by_hour.items()):
        if v["tmpf"] is None or v["dwpf"] is None or v["sknt"] is None:
            continue
        gust = v["gust"]
        out.append(
            [
                hour.strftime("%Y-%m-%dT%H:%MZ"),
                f"{f_to_c(v['tmpf']):.2f}",
                f"{f_to_c(v['dwpf']):.2f}",
                f"{v['sknt'] * KT_TO_MS:.2f}",
                "" if gust is None else f"{gust * KT_TO_MS:.2f}",
                f"{(v['p01i'] or 0.0) * IN_TO_MM:.2f}",
            ]
        )
    return out


def _write(path: Path, header: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def derive(raw: Path, fixtures: Path = FIXTURES) -> dict[str, int]:
    data = _parse_raw(raw)
    gsp = _hourly(data["GSP"])
    _write(fixtures / "tablerock" / GSP_HOURLY.name, HOURLY_HEADER, gsp)
    ags = [
        r
        for r in _hourly(data["AGS"])
        if datetime(2024, 7, 8, tzinfo=UTC) <= parse_utc(r[0]) < datetime(2024, 7, 21, tzinfo=UTC)
    ]
    _write(fixtures / "heat" / AGS_HOURLY.name, HOURLY_HEADER, ags)
    daily_rows: list[list[str]] = []
    for st in STATIONS:
        for d in daily_summary(_rows_to_obs(_hourly(data[st]))):
            if d.day.month in (5, 6, 7, 8, 9) and d.day.year in (2023, 2024):
                daily_rows.append(
                    [st, d.day.isoformat(), f"{d.tmax_c:.2f}", f"{d.tmean_c:.2f}", str(d.n_obs)]
                )
    _write(fixtures / "heat" / STATIONS_DAILY.name, DAILY_HEADER, daily_rows)
    return {"gsp_hourly": len(gsp), "ags_hourly": len(ags), "daily": len(daily_rows)}


def parse_utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)


def _rows_to_obs(rows: Iterable[Sequence[str]]) -> list[HourlyObs]:
    return [
        HourlyObs(
            t=parse_utc(r[0]),
            t_c=float(r[1]),
            td_c=float(r[2]),
            wind_ms=float(r[3]),
            gust_ms=float(r[4]) if r[4] else None,
            precip_mm=float(r[5]),
        )
        for r in rows
    ]


def load_hourly(path: Path) -> list[HourlyObs]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        if tuple(header) != HOURLY_HEADER:
            raise ValueError(f"{path}: unexpected header {header}")
        return _rows_to_obs(reader)


def daily_summary(obs: Sequence[HourlyObs], min_obs: int = 18) -> list[DailyObs]:
    """Eastern local-date Tmax and mean; days with fewer than `min_obs` hours are dropped."""
    by_day: dict[date, list[float]] = defaultdict(list)
    for o in obs:
        by_day[o.t.astimezone(EASTERN).date()].append(o.t_c)
    return [
        DailyObs("", d, max(v), math.fsum(v) / len(v), len(v))
        for d, v in sorted(by_day.items())
        if len(v) >= min_obs
    ]


def load_daily(path: Path = STATIONS_DAILY) -> list[DailyObs]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [
            DailyObs(
                r["station"],
                date.fromisoformat(r["date_local"]),
                float(r["tmax_c"]),
                float(r["tmean_c"]),
                int(r["n_obs"]),
            )
            for r in csv.DictReader(fh)
        ]


def local_date(t: datetime) -> date:
    return t.astimezone(EASTERN).date()
