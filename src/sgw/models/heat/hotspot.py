"""Heat trigger, temperature-driven load, transformer hot-spot table and the H2 binding-constraint check.

Trigger: a hot day is a day whose station-mean Tmax (five footprint ASOS stations) is at or above the JJA
P95 of the calibration summer; the trigger fires at local midnight starting the second consecutive hot
day. Observed Tmax stands in for a day-ahead forecast (perfect-forecast proxy; forecast skill is not
modelled).

Load (per unit, pu of rating): K(t) = k_base x shape(local hour) x (1 + s (Tmean_day - 21)+), with s the
BA cooling slope (SCEG 5.8 %/C, project fact base) and shape(h) = (1 + a cos(2 pi (h - 17)/24)) / (1 + a), so
k_base is the 17:00 loading on a 21 C day. Ambient is AGS hourly, linearly interpolated to the 1-min
thermal step.

H2: same load, still air. The feeder trunk carries a current with the same load factor as its
transformer; its IEEE 738 ampacity is evaluated hourly at the observed ambient and clear-sky sun, once at
the rating-basis wind (0.61 m/s, the usual planning value) and once in still air (0.3 m/s). ASOS reports
calm as 0, so observed wind is not used at conductor height. The binding constraint is whichever limit is
reached first: the line (loading >= 100 % of ampacity) or the transformer (hot spot >= the warning level)."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import numpy as np
import yaml

from sgw.models.heat.ampacity import Conductor, ampacity
from sgw.models.heat.thermal import COOLING, ThermalTrace, simulate

PARAMS_PATH = Path(__file__).with_name("params.yaml")
EASTERN = ZoneInfo("America/New_York")
STEP_MIN = 1.0


class AmbientHour(Protocol):
    @property
    def t(self) -> datetime: ...
    @property
    def t_c(self) -> float: ...
    @property
    def wind_ms(self) -> float: ...


@cache
def params() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))
    return raw


def value(section: str, key: str) -> Any:
    return params()[section][key]["value"]


@dataclass(frozen=True)
class HeatTrigger:
    threshold_c: float
    calibration_days: int
    hot_days: list[date]
    fire_days: list[date]

    def fires_in(self, first: date, last: date) -> list[date]:
        return [d for d in self.fire_days if first <= d <= last]


def station_mean_tmax(daily: Sequence[tuple[str, date, float]], stations: Sequence[str]) -> dict[date, float]:
    by_day: dict[date, dict[str, float]] = defaultdict(dict)
    for st, d, tmax in daily:
        by_day[d][st] = tmax
    return {d: math.fsum(v.values()) / len(v) for d, v in sorted(by_day.items()) if set(stations) <= set(v)}


def heat_trigger(daily: Sequence[tuple[str, date, float]]) -> HeatTrigger:
    stations = list(value("trigger", "stations"))
    means = station_mean_tmax(daily, stations)
    year = int(value("trigger", "calibration_year"))
    cal = [v for d, v in means.items() if d.year == year and d.month in (6, 7, 8)]
    if not cal:
        raise ValueError("no calibration-summer days")
    thr = float(np.percentile(cal, float(value("trigger", "percentile"))))
    need = int(value("trigger", "consecutive_days"))
    hot = [d for d, v in means.items() if v >= thr]
    hot_set = set(hot)
    fire = [d for d in hot if all(d - timedelta(days=i) in hot_set for i in range(need))]
    fire = [d for d in fire if d - timedelta(days=1) not in set(fire)]
    return HeatTrigger(thr, len(cal), hot, fire)


def local_midnight_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=EASTERN).astimezone(UTC)


def shape(hour_local: float) -> float:
    a = float(value("load", "diurnal_amplitude"))
    peak = float(value("load", "peak_hour_local"))
    return (1.0 + a * math.cos(2.0 * math.pi * (hour_local - peak) / 24.0)) / (1.0 + a)


def load_factor(t: datetime, day_mean_c: float) -> float:
    s = float(value("load", "cooling_slope_pct_per_c")) / 100.0
    ref = float(value("load", "reference_daily_mean_c"))
    loc = t.astimezone(EASTERN)
    return shape(loc.hour + loc.minute / 60.0) * (1.0 + s * max(day_mean_c - ref, 0.0))


def solar_w_m2(t: datetime) -> float:
    lat = math.radians(float(value("solar", "latitude_deg")))
    doy = t.timetuple().tm_yday
    decl = math.radians(23.44) * math.sin(2.0 * math.pi * (284 + doy) / 365.0)
    lon = -81.72
    solar_time = t.hour + t.minute / 60.0 + lon / 15.0
    ha = math.radians(15.0 * (solar_time - 12.0))
    sin_el = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(ha)
    return float(value("solar", "clear_sky_w_m2")) * max(sin_el, 0.0)


@dataclass(frozen=True)
class Grid:
    times: list[datetime]
    ambient_c: list[float]
    wind_ms: list[float]
    day_mean_c: Mapping[date, float]


def minute_grid(obs: Sequence[AmbientHour], start: datetime, end: datetime) -> Grid:
    ordered = sorted(obs, key=lambda o: o.t)
    xs = np.array([o.t.timestamp() for o in ordered])
    temps = np.array([o.t_c for o in ordered])
    winds = np.array([o.wind_ms for o in ordered])
    n = int((end - start).total_seconds() // (STEP_MIN * 60.0))
    times = [start + timedelta(minutes=STEP_MIN * i) for i in range(n)]
    ts = np.array([t.timestamp() for t in times])
    day_vals: dict[date, list[float]] = defaultdict(list)
    for o in ordered:
        day_vals[o.t.astimezone(EASTERN).date()].append(o.t_c)
    return Grid(
        times,
        [float(x) for x in np.interp(ts, xs, temps)],
        [float(x) for x in np.interp(ts, xs, winds)],
        {d: math.fsum(v) / len(v) for d, v in day_vals.items()},
    )


@dataclass(frozen=True)
class UnitResult:
    unit: Mapping[str, Any]
    trace: ThermalTrace
    times: list[datetime]


def run_unit(unit: Mapping[str, Any], grid: Grid) -> UnitResult:
    k = [
        float(unit["k_base"]) * load_factor(t, grid.day_mean_c[t.astimezone(EASTERN).date()])
        for t in grid.times
    ]
    trace = simulate(COOLING[str(unit["cooling"])], k, grid.ambient_c, STEP_MIN)
    return UnitResult(unit, trace, grid.times)


def alarm(theta_h: float) -> str:
    if theta_h >= float(value("alarms", "emergency_c")):
        return "emergency"
    if theta_h >= float(value("alarms", "warning_c")):
        return "warning"
    if theta_h >= float(value("alarms", "watch_c")):
        return "watch"
    return "normal"


def summarise(res: UnitResult, start: datetime, end: datetime) -> dict[str, Any]:
    idx = [i for i, t in enumerate(res.times) if start <= t < end]
    tr = res.trace
    peak_i = max(idx, key=lambda i: (tr.theta_h[i], -i))
    hours = lambda thr: sum(1 for i in idx if tr.theta_h[i] >= thr) * STEP_MIN / 60.0  # noqa: E731
    lol_h = math.fsum(tr.faa[i] for i in idx) * STEP_MIN / 60.0
    return {
        "asset_id": res.unit["asset_id"],
        "site": res.unit["site"],
        "cooling": res.unit["cooling"],
        "rating_kva": res.unit["rating_kva"],
        "k_base": res.unit["k_base"],
        "k_peak": max(tr.k[i] for i in idx),
        "theta_a_at_peak_c": tr.theta_a[peak_i],
        "theta_o_peak_c": max(tr.theta_o[i] for i in idx),
        "theta_h_peak_c": tr.theta_h[peak_i],
        "peak_utc": res.times[peak_i],
        "hours_ge_watch": hours(float(value("alarms", "watch_c"))),
        "hours_ge_warning": hours(float(value("alarms", "warning_c"))),
        "faa_peak": tr.faa[peak_i],
        "aging_equiv_days": lol_h / 24.0,
        "window_days": len(idx) * STEP_MIN / 1440.0,
        "night_min_theta_h_c": min(tr.theta_h[i] for i in idx),
        "alarm": alarm(tr.theta_h[peak_i]),
    }


@dataclass(frozen=True)
class BindingCheck:
    wind_case: str
    line_limit_utc: datetime | None
    transformer_limit_utc: datetime | None
    peak_line_loading_pct: float
    peak_line_loading_utc: datetime
    binding: str


def conductor() -> Conductor:
    c = params()["line"]["conductor"]
    return Conductor(
        c["name"],
        float(c["diameter_m"]),
        float(c["r25_ohm_per_m"]),
        float(c["r75_ohm_per_m"]),
        float(c["emissivity"]),
        float(c["absorptivity"]),
        float(c["max_temp_c"]),
    )


def binding_check(
    transformer: UnitResult, grid: Grid, start: datetime, end: datetime, wind_ms: float
) -> BindingCheck:
    """Hourly line loading (current / ampacity) and the transformer hot spot; the first limit binds."""
    cond = conductor()
    i_base = float(params()["line"]["current_base_a"]["value"])
    k_base = float(transformer.unit["k_base"])
    warn = float(value("alarms", "warning_c"))
    line_t: datetime | None = None
    tx_t: datetime | None = None
    peak = (0.0, start)
    for i, t in enumerate(grid.times):
        if not start <= t < end:
            continue
        if tx_t is None and transformer.trace.theta_h[i] >= warn:
            tx_t = t
        if t.minute != 0:
            continue
        current = i_base * transformer.trace.k[i] / k_base
        loading = 100.0 * current / ampacity(cond, grid.ambient_c[i], wind_ms, solar_w_m2(t))
        if loading > peak[0]:
            peak = (loading, t)
        if line_t is None and loading >= 100.0:
            line_t = t
    firsts = [(x, name) for x, name in ((line_t, "line"), (tx_t, "transformer")) if x is not None]
    binding = min(firsts)[1] if firsts else "none"
    return BindingCheck(
        f"wind {wind_ms:g} m/s",
        line_t,
        tx_t,
        peak[0],
        peak[1],
        binding,
    )
