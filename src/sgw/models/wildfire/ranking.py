"""Circuit ranking for a fire-weather window: expected power-line ignitions per feeder,
`sum over hours of p(outage)_h x p(ignition | outage)_h` (PS DC-32, PG&E DEPM structure, R02 2.3).

Per overhead km and hour, the fault hazard is

    h(t) = base / 8760 x w(t) / mean_year(w) x (veg_floor + veg) / (veg_floor + mean veg),
    w(t) = 1 + (max(U(t) - onset, 0) / scale)^2,

normalised so the calibration years reproduce `base` faults per km-year for the mean feeder. The conditional
ignition probability is the R02 Southeast transfer

    logit p(i|o) = a + c_k (KBDI - 400)/200 + c_f (FFWI - 30)/20 + 0.6 fuel - 1.5 wet24h, capped at 0.5,

with fuel = the feeder vegetation index (0..1). R02 proposes c_k = 1.0, c_f = 0.8; on GSP 2023-24 weather
that puts 6 % of annual ignitions in February-April, where SC records 42.6 % (spring fine-fuel season), so
c_k and c_f are fitted in-sample to those month shares; leave-one-month-out holds 2 of 3
months within 5 points and the window score scales with c_f (`params.yaml` validation). The
intercept `a` (R02 writes it logit(0.3 p0)) is not guessed: it is solved so that the mean feeder over the
calibration years ignites at the handoff base rate (0.022 per 100 km-year), so the ranking is anchored to an
observed rate and only the shape is assumed.
Expected ignitions are additive over hours (the Poisson mean); the window probability is 1 - exp(-E).
`ratio_to_average_window` compares with an average window of the same length in the calibration years.
Domain: one station's weather applied to all ranked feeders (GSP for the upstate counties); no fire spread.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from scipy.optimize import brentq

from sgw.models.wildfire.indices import ffwi
from sgw.models.wildfire.trigger import EASTERN, WeatherHour, params, value

HOURS_PER_YEAR = 8760.0


@dataclass(frozen=True)
class Circuit:
    feeder_id: str
    fips: str
    customers: int
    veg: float
    overhead_km: float


@dataclass(frozen=True)
class HourDriver:
    t: datetime
    wind_mult: float
    ffwi: float
    kbdi: float
    wet24h: bool


@dataclass(frozen=True)
class Calibration:
    intercept: float
    wind_mult_mean: float
    veg_mean: float
    base_faults_per_km_year: float
    rate_per_km_year: float
    hours: int

    @property
    def p0(self) -> float:
        """R02's p0 (the intercept is logit(0.3 p0))."""
        return 1.0 / (1.0 + math.exp(-self.intercept)) / 0.3


@dataclass(frozen=True)
class RankedCircuit:
    rank: int
    circuit: Circuit
    p_outage: float
    expected_faults: float
    expected_ignitions: float
    p_ignition: float
    peak_p_ign_given_outage: float
    ratio_to_average_window: float


def wind_mult(wind_ms: float) -> float:
    onset = float(value("outage", "wind_onset_ms"))
    scale = float(value("outage", "wind_scale_ms"))
    return 1.0 + (max(wind_ms - onset, 0.0) / scale) ** 2


def drivers(obs: Sequence[WeatherHour], kbdi_end_of_day: Mapping[date, float]) -> list[HourDriver]:
    wet_mm = float(value("ignition", "wet24h_mm"))
    ordered = sorted(obs, key=lambda o: o.t)
    out: list[HourDriver] = []
    window: list[tuple[datetime, float]] = []
    total = 0.0
    for o in ordered:
        window.append((o.t, o.precip_mm))
        total += o.precip_mm
        while window and window[0][0] <= o.t - timedelta(hours=24):
            total -= window.pop(0)[1]
        k = kbdi_end_of_day.get(o.t.astimezone(EASTERN).date() - timedelta(days=1), 0.0)
        out.append(HourDriver(o.t, wind_mult(o.wind_ms), ffwi(o.t_c, o.rh_pct, o.wind_ms), k, total > wet_mm))
    return out


def _logit_terms(d: HourDriver) -> float:
    return (
        float(value("ignition", "logit_kbdi_coef"))
        * (d.kbdi - float(value("ignition", "logit_kbdi_ref")))
        / 200.0
        + float(value("ignition", "logit_ffwi_coef"))
        * (d.ffwi - float(value("ignition", "logit_ffwi_ref")))
        / 20.0
        + float(value("ignition", "logit_wet_coef")) * (1.0 if d.wet24h else 0.0)
    )


def p_ign_given_outage(d: HourDriver, fuel: float, intercept: float) -> float:
    z = intercept + _logit_terms(d) + float(value("ignition", "logit_fuel_coef")) * fuel
    return min(float(value("ignition", "p_cap")), 1.0 / (1.0 + math.exp(-z)))


def _hazard_per_km_h(
    d: HourDriver, veg: float, cal_wind_mean: float, cal_veg_mean: float, base: float
) -> float:
    floor = float(value("outage", "veg_floor"))
    return base / HOURS_PER_YEAR * d.wind_mult / cal_wind_mean * (floor + veg) / (floor + cal_veg_mean)


def calibrate(year_drivers: Sequence[HourDriver], veg_mean: float) -> Calibration:
    """Solve the intercept so the mean feeder's ignition rate over `year_drivers` equals the base rate."""
    if not year_drivers:
        raise ValueError("calibration needs weather hours")
    base = float(value("outage", "base_faults_per_km_year"))
    target = float(value("ignition", "rate_per_100km_year")) / 100.0
    years = len(year_drivers) / HOURS_PER_YEAR
    w_mean = math.fsum(d.wind_mult for d in year_drivers) / len(year_drivers)

    def rate(a: float) -> float:
        e = math.fsum(
            _hazard_per_km_h(d, veg_mean, w_mean, veg_mean, base) * p_ign_given_outage(d, veg_mean, a)
            for d in year_drivers
        )
        return e / years - target

    intercept = brentq(rate, -30.0, 5.0, xtol=1e-12)
    return Calibration(intercept, w_mean, veg_mean, base, target, len(year_drivers))


def seasonal_shares(year_drivers: Sequence[HourDriver], cal: Calibration) -> dict[int, float]:
    """Share (%) of the mean feeder's expected ignitions per calendar month over the calibration years."""
    by_month: dict[int, float] = {}
    for d in year_drivers:
        e = _hazard_per_km_h(d, cal.veg_mean, cal.wind_mult_mean, cal.veg_mean, cal.base_faults_per_km_year)
        by_month[d.t.month] = by_month.get(d.t.month, 0.0) + e * p_ign_given_outage(
            d, cal.veg_mean, cal.intercept
        )
    total = math.fsum(by_month.values())
    return {m: 100.0 * v / total for m, v in sorted(by_month.items())}


def rank(
    circuits: Sequence[Circuit],
    window: Sequence[HourDriver],
    cal: Calibration,
    year_drivers: Sequence[HourDriver],
) -> list[RankedCircuit]:
    years = len(year_drivers) / HOURS_PER_YEAR
    rows: list[tuple[float, str, RankedCircuit]] = []
    for c in circuits:
        faults = ign = 0.0
        peak = 0.0
        for d in window:
            h = _hazard_per_km_h(d, c.veg, cal.wind_mult_mean, cal.veg_mean, cal.base_faults_per_km_year)
            p = p_ign_given_outage(d, c.veg, cal.intercept)
            faults += h * c.overhead_km
            ign += h * c.overhead_km * p
            peak = max(peak, p)
        annual = c.overhead_km * math.fsum(
            _hazard_per_km_h(d, c.veg, cal.wind_mult_mean, cal.veg_mean, cal.base_faults_per_km_year)
            * p_ign_given_outage(d, c.veg, cal.intercept)
            for d in year_drivers
        )
        typical = annual / years * len(window) / HOURS_PER_YEAR
        ranked = RankedCircuit(
            rank=0,
            circuit=c,
            p_outage=1.0 - math.exp(-faults),
            expected_faults=faults,
            expected_ignitions=ign,
            p_ignition=1.0 - math.exp(-ign),
            peak_p_ign_given_outage=peak,
            ratio_to_average_window=ign / typical if typical > 0 else math.inf,
        )
        rows.append((-ign, c.feeder_id, ranked))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [replace(r[2], rank=i + 1) for i, r in enumerate(rows)]


@contextmanager
def ignition_weights(kbdi_coef: float, ffwi_coef: float) -> Iterator[None]:
    """Evaluate the model at other logit weights (fits and sensitivity), restoring the configured ones."""
    ign = params()["ignition"]
    saved = (ign["logit_kbdi_coef"]["value"], ign["logit_ffwi_coef"]["value"])
    ign["logit_kbdi_coef"]["value"], ign["logit_ffwi_coef"]["value"] = kbdi_coef, ffwi_coef
    try:
        yield
    finally:
        ign["logit_kbdi_coef"]["value"], ign["logit_ffwi_coef"]["value"] = saved


def window_ratio(window: Sequence[HourDriver], year: Sequence[HourDriver], cal: Calibration) -> float:
    """Expected ignitions of the mean feeder in `window` over an average window of the same length."""
    mean = Circuit("MEAN", "", 0, cal.veg_mean, 1.0)
    return rank([mean], window, cal, year)[0].ratio_to_average_window


@dataclass(frozen=True)
class FitPoint:
    kbdi_coef: float
    ffwi_coef: float
    sse: float
    shares: dict[int, float]


def fit_weights(
    year: Sequence[HourDriver],
    veg_mean: float,
    targets: Mapping[int, float],
    kbdi_grid: Sequence[float],
    ffwi_grid: Sequence[float],
) -> list[FitPoint]:
    """Grid search of the two logit weights against observed month shares; best (lowest SSE) first."""
    out: list[FitPoint] = []
    for kc in kbdi_grid:
        for fc in ffwi_grid:
            with ignition_weights(kc, fc):
                shares = seasonal_shares(year, calibrate(year, veg_mean))
            sse = math.fsum((shares[m] - v) ** 2 for m, v in targets.items())
            out.append(FitPoint(kc, fc, sse, shares))
    return sorted(out, key=lambda p: (p.sse, p.kbdi_coef, p.ffwi_coef))
