"""GSP fire weather from the committed station extract: hourly observations, KBDI per local day (spun up from
2023-01-01 at 0, R05), the trigger over the whole record, and the ignition calibration on 2023-2024."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from functools import cache
from pathlib import Path

from sgw.generator.scenarios.weather import GSP_HOURLY, HourlyObs, load_hourly, local_date
from sgw.models.wildfire import ranking as rk
from sgw.models.wildfire.indices import KbdiDay, kbdi_series
from sgw.models.wildfire.trigger import TriggerResult, evaluate

CAL_YEARS = (2023, 2024)


@dataclass(frozen=True)
class FireWeather:
    obs: list[HourlyObs]
    kbdi: list[KbdiDay]
    mean_annual_rain_in: float
    trigger: TriggerResult

    @property
    def kbdi_by_day(self) -> dict[date, float]:
        return {k.day: k.kbdi for k in self.kbdi}

    def between(self, start: datetime, end: datetime) -> list[HourlyObs]:
        return [o for o in self.obs if start <= o.t < end]


def build(path: Path = GSP_HOURLY) -> FireWeather:
    obs = load_hourly(path)
    tmax: dict[date, float] = defaultdict(lambda: -math.inf)
    rain: dict[date, float] = defaultdict(float)
    for o in obs:
        d = local_date(o.t)
        tmax[d] = max(tmax[d], o.t_c)
        rain[d] += o.precip_mm
    days = sorted(tmax)
    cal_rain_mm = math.fsum(rain[d] for d in days if d.year in CAL_YEARS)
    p_ann = cal_rain_mm / 25.4 / len(CAL_YEARS)
    series = kbdi_series([(d, tmax[d], rain[d]) for d in days], p_ann)
    kb = {k.day: k.kbdi for k in series}
    return FireWeather(obs, series, p_ann, evaluate(obs, kb))


@cache
def gsp() -> FireWeather:
    return build()


@cache
def calibration(veg_mean: float) -> tuple[rk.Calibration, tuple[rk.HourDriver, ...]]:
    fw = gsp()
    year = [o for o in fw.obs if o.t.year in CAL_YEARS]
    drivers = tuple(rk.drivers(year, fw.kbdi_by_day))
    return rk.calibrate(drivers, veg_mean), drivers
