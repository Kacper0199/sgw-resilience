"""Fire-weather indices from station observations (R02 hazard-interdependency 2.1).

- Fosberg Fire Weather Index (FFWI): `eta * sqrt(1 + U^2) / 0.3002`, `eta = 1 - 2m + 1.5m^2 - 0.5m^3`,
  `m = EMC / 30`, U in mph; EMC (equilibrium moisture content, %) from RH (%) and T (deg F) with the three
  Simard branches (h < 10; 10 <= h <= 50; h > 50). Domain: 0 <= RH <= 100, U >= 0; FFWI is capped at 100.
- Keetch-Byram Drought Index (KBDI, 0..800, hundredths of an inch of soil-moisture deficit): daily update with
  Tmax in deg F and the station's mean annual rainfall P in inches,
  `dQ = (800 - Q)(0.968 exp(0.0486 T) - 8.30) / (1 + 10.88 exp(-0.0441 P)) * 1e-3` (8.30, not the 0.830 typo),
  never negative; rain reduces Q by 100 x net rain (in), where the first 0.2 in of a consecutive rain spell is
  intercepted.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

MS_TO_MPH = 2.236936
MM_TO_IN = 1.0 / 25.4
FFWI_CAP = 100.0
KBDI_MAX = 800.0
SPELL_INTERCEPT_IN = 0.2


def emc_pct(rh_pct: float, t_f: float) -> float:
    h = rh_pct
    if h < 10.0:
        return 0.03229 + 0.281073 * h - 0.000578 * h * t_f
    if h <= 50.0:
        return 2.22749 + 0.160107 * h - 0.01478 * t_f
    return 21.0606 + 0.005565 * h * h - 0.00035 * h * t_f - 0.483199 * h


def ffwi(t_c: float, rh_pct: float, wind_ms: float) -> float:
    if not 0.0 <= rh_pct <= 100.0 or wind_ms < 0.0:
        raise ValueError("FFWI needs 0 <= RH <= 100 and non-negative wind")
    m = min(max(emc_pct(rh_pct, t_c * 1.8 + 32.0), 0.0), 30.0) / 30.0
    eta = 1.0 - 2.0 * m + 1.5 * m * m - 0.5 * m**3
    u = wind_ms * MS_TO_MPH
    return min(FFWI_CAP, eta * math.sqrt(1.0 + u * u) / 0.3002)


@dataclass(frozen=True)
class KbdiDay:
    day: date
    kbdi: float
    tmax_c: float
    rain_mm: float


def kbdi_series(
    days: Sequence[tuple[date, float, float]], mean_annual_rain_in: float, start: float = 0.0
) -> list[KbdiDay]:
    """`days` = (local date, Tmax deg C, daily rain mm), consecutive and sorted. The value for a day is the
    state at its end, usable from the next local day on."""
    q = start
    spell = 0.0
    out: list[KbdiDay] = []
    denom = 1.0 + 10.88 * math.exp(-0.0441 * mean_annual_rain_in)
    for day, tmax_c, rain_mm in days:
        p = rain_mm * MM_TO_IN
        if p > 0.0:
            before = spell
            spell += p
            net = max(0.0, spell - SPELL_INTERCEPT_IN) if before < SPELL_INTERCEPT_IN else p
            q = max(0.0, q - 100.0 * net)
        else:
            spell = 0.0
        t_f = tmax_c * 1.8 + 32.0
        dq = (KBDI_MAX - q) * (0.968 * math.exp(0.0486 * t_f) - 8.30) / denom * 1e-3
        q = min(KBDI_MAX, max(0.0, q + max(0.0, dq)))
        out.append(KbdiDay(day, q, tmax_c, rain_mm))
    return out
