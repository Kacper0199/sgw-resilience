"""Wildfire (Red Flag protocol) trigger, PS DC-32 / project fact base:

    (FFWI >= 35 and RH <= 25 % held for 3 consecutive hours) OR KBDI >= 500

evaluated hourly on station observations. The FFWI/RH branch becomes active at the end of the third
consecutive qualifying hour and stays active while the hourly condition holds; a missing hour breaks the
run. Active hours less than `MAX_GAP` apart form one episode (`hours` counts active hours only). The KBDI
branch uses the KBDI at the end of the previous local day, so it is known at local midnight. A KBDI-only rule
misses Table Rock (KBDI about 40-115 after mid-March rain, R05 1.3), which is why the OR exists.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import yaml

from sgw.models.wildfire.indices import ffwi

PARAMS_PATH = Path(__file__).with_name("params.yaml")
EASTERN = ZoneInfo("America/New_York")
HOUR = timedelta(hours=1)
MAX_GAP = timedelta(hours=3)


class WeatherHour(Protocol):
    @property
    def t(self) -> datetime: ...
    @property
    def t_c(self) -> float: ...
    @property
    def rh_pct(self) -> float: ...
    @property
    def wind_ms(self) -> float: ...
    @property
    def precip_mm(self) -> float: ...


@cache
def params() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))
    return raw


def value(section: str, key: str) -> Any:
    return params()[section][key]["value"]


@dataclass(frozen=True)
class TriggerRule:
    ffwi_min: float
    rh_max_pct: float
    min_hours: int
    kbdi_min: float

    @classmethod
    def default(cls) -> TriggerRule:
        return cls(
            float(value("trigger", "ffwi_min")),
            float(value("trigger", "rh_max_pct")),
            int(value("trigger", "min_hours")),
            float(value("trigger", "kbdi_min")),
        )

    @property
    def rule_id(self) -> str:
        return (
            f"rule.wildfire.red_flag(ffwi>={self.ffwi_min:g} & rh<={self.rh_max_pct:g} for {self.min_hours}h"
            f" | kbdi>={self.kbdi_min:g})"
        )


@dataclass(frozen=True)
class HourState:
    t: datetime
    ffwi: float
    rh_pct: float
    kbdi: float | None
    run_h: int
    ffwi_branch: bool
    kbdi_branch: bool

    @property
    def active(self) -> bool:
        return self.ffwi_branch or self.kbdi_branch


@dataclass(frozen=True)
class Episode:
    start_utc: datetime
    end_utc: datetime
    branches: tuple[str, ...]
    hours: int
    ffwi_max: float
    rh_min_pct: float


@dataclass(frozen=True)
class TriggerResult:
    rule: TriggerRule
    hours: list[HourState]
    episodes: list[Episode] = field(default_factory=list)

    @property
    def fired(self) -> bool:
        return bool(self.episodes)

    def first_fire_utc(self) -> datetime | None:
        return self.episodes[0].start_utc if self.episodes else None

    def active_local_days(self) -> list[date]:
        return sorted({h.t.astimezone(EASTERN).date() for h in self.hours if h.active})


def evaluate(
    obs: Sequence[WeatherHour], kbdi_end_of_day: Mapping[date, float], rule: TriggerRule | None = None
) -> TriggerResult:
    rule = rule or TriggerRule.default()
    hours: list[HourState] = []
    run = 0
    prev: datetime | None = None
    for o in sorted(obs, key=lambda x: x.t):
        f = ffwi(o.t_c, o.rh_pct, o.wind_ms)
        ok = f >= rule.ffwi_min and o.rh_pct <= rule.rh_max_pct
        contiguous = prev is not None and o.t - prev == HOUR
        run = (run + 1 if contiguous else 1) if ok else 0
        prev = o.t
        k = kbdi_end_of_day.get(o.t.astimezone(EASTERN).date() - timedelta(days=1))
        hours.append(
            HourState(
                t=o.t,
                ffwi=f,
                rh_pct=o.rh_pct,
                kbdi=k,
                run_h=run,
                ffwi_branch=run >= rule.min_hours,
                kbdi_branch=k is not None and k >= rule.kbdi_min,
            )
        )
    return TriggerResult(rule, hours, _episodes(hours))


def _episodes(hours: Sequence[HourState]) -> list[Episode]:
    out: list[Episode] = []
    cur: list[HourState] = []

    def close() -> None:
        if cur:
            branches = tuple(
                b
                for b, on in (
                    ("ffwi_rh", any(h.ffwi_branch for h in cur)),
                    ("kbdi", any(h.kbdi_branch for h in cur)),
                )
                if on
            )
            out.append(
                Episode(
                    start_utc=cur[0].t,
                    end_utc=cur[-1].t,
                    branches=branches,
                    hours=len(cur),
                    ffwi_max=max(h.ffwi for h in cur),
                    rh_min_pct=min(h.rh_pct for h in cur),
                )
            )
            cur.clear()

    for h in hours:
        if not h.active:
            continue
        if cur and h.t - cur[-1].t > MAX_GAP:
            close()
        cur.append(h)
    close()
    return out
