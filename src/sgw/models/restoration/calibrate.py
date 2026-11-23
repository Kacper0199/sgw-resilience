"""Helene calibration of the restoration process against EAGLE-I county restoration times.

Fitted (in-sample, two parameters for two targets): `section_scale` and `secondary_per_100`, so that the
median over counties of t50 and t90 (hours from county peak to 50 / 90 percent restored) match EAGLE-I.
Not fitted (reported as checks): the 75th and 25th percentiles of county t90, the 75th percentile of
county t50, the share of counties slower than a week, county rank agreement, the median county
customer-hours over the peak (WP-11's EAGLE-I aggregation) and the outage-weighted county t90 (each
county weighted by its peak customers out, over the same compared counties; the repo holds no EAGLE-I
footprint series, so the statewide numbers.yaml figure is not comparable). The WP-06 generator's own
restoration is the baseline. The process compresses the county distribution.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from sgw.common import numbers as numbers_mod
from sgw.generator.config import REPO_ROOT, SYNTHETIC_DIR, load_family, load_scenario, parse_utc
from sgw.generator.truth import Truth, run_truth
from sgw.generator.wind import epoch
from sgw.models.restoration.curves import (
    censored_median,
    county_times,
    run_grid,
    run_intervals,
    series,
)
from sgw.models.restoration.params import Params, default_params
from sgw.models.restoration.process import ProcessRun, simulate
from sgw.models.restoration.world import World, family_a_world, story_seed

EAGLEI_CSV = SYNTHETIC_DIR / "validation" / "helene_eaglei_county.csv"
CUSTOMER_HOURS_CSV = REPO_ROOT / "data" / "open" / "eaglei" / "county_storm_outages.csv"
WEEK_H = 168.0


@dataclass(frozen=True)
class Observed:
    t50: dict[str, float]
    t90: dict[str, float]
    peak: dict[str, float]


def load_observed(path: Path = EAGLEI_CSV) -> Observed:
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    def num(v: str) -> float:
        return float(v) if v else math.nan

    return Observed(
        t50={r["fips"].zfill(5): num(r["t50_h"]) for r in rows},
        t90={r["fips"].zfill(5): num(r["t90_h"]) for r in rows},
        peak={r["fips"].zfill(5): num(r["peak_out"]) for r in rows},
    )


def weighted_median(values: list[float], weights: list[float]) -> float:
    """Weighted median with nan ('never reached') above every finite value."""
    v = np.array([math.inf if math.isnan(x) else x for x in values])
    w = np.asarray(weights, dtype=float)
    order = np.argsort(v, kind="stable")
    cum = np.cumsum(w[order])
    return float(v[order][int(np.searchsorted(cum, 0.5 * cum[-1]))])


FIT_KEYS = ("section_scale", "secondary_per_100")
TARGET_NAMES = ("t50_median_h", "t90_median_h", "t90_p75_h")


def censored_percentile(values: list[float], q: float) -> float:
    arr = np.array([math.inf if math.isnan(v) else v for v in values])
    return float(np.percentile(arr, q, method="lower"))


def county_stats(county: dict[str, dict[str, float]]) -> np.ndarray:
    """(median t50, median t90, 75th percentile t90) over counties; never-reached counts as slowest."""
    t50 = [v["t50_h"] for v in county.values()]
    t90 = [v["t90_h"] for v in county.values()]
    return np.array([censored_median(t50), censored_median(t90), censored_percentile(t90, 75)])


def model_stats(worlds: list[World], prm: Params) -> np.ndarray:
    """County statistics averaged over worlds (common random numbers across parameter values)."""
    h = prm.f("process", "horizon_days")
    step = prm.f("process", "step_s")
    return np.mean([county_stats(county_times(simulate(w, prm), h, step)) for w in worlds], axis=0)


def targets(obs: Observed) -> np.ndarray:
    t50 = float(numbers_mod.value("helene_restoration_t50_hours"))
    t90 = list(obs.t90.values())
    return np.array([t50, censored_median(t90), censored_percentile(t90, 75)])


def calibration_worlds(n_extra: int = 4) -> list[World]:
    prm = default_params()
    extra = prm.seeds("train")[:n_extra]
    return [family_a_world(story_seed())] + [family_a_world(s) for s in extra]


def fit(
    worlds: list[World], prm: Params, obs: Observed, iterations: int = 5, tol_rel: float = 0.025
) -> tuple[Params, list[dict[str, float]]]:
    """Newton steps in log-parameter space, finite-difference Jacobian; three parameters, three targets."""
    n = len(FIT_KEYS)
    goal = np.log(targets(obs))[:n]
    x = np.log([prm.f("process", k) for k in FIT_KEYS])
    trace: list[dict[str, float]] = []

    def at(v: np.ndarray) -> np.ndarray:
        vals = {k: float(np.exp(v[i])) for i, k in enumerate(FIT_KEYS)}
        stats = model_stats(worlds, prm.with_values("process", **vals))
        trace.append({**vals, **dict(zip(TARGET_NAMES, stats.tolist(), strict=True))})
        return np.log(stats)[:n]

    y = at(x)
    for _ in range(iterations):
        if np.all(np.abs(y - goal) <= tol_rel):
            break
        eps = 0.08
        jac = np.zeros((n, n))
        for k in range(n):
            dx = np.zeros(n)
            dx[k] = eps
            jac[:, k] = (at(x + dx) - y) / eps
        step = np.clip(np.linalg.lstsq(jac, goal - y, rcond=None)[0], -0.5, 0.5)
        x = x + step
        y = at(x)
    best = min(trace, key=lambda r: float(np.abs(np.log([r[t] for t in TARGET_NAMES[:n]]) - goal).sum()))
    return prm.with_values("process", **{k: round(best[k], 4) for k in FIT_KEYS}), trace


def load_customer_hours(path: Path = CUSTOMER_HOURS_CSV) -> tuple[dict[str, float], float, float]:
    """EAGLE-I Helene customer-hours over peak per county (WP-11 table) and its window (epoch s)."""
    with path.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["storm"] == "helene"]
    eq = {
        r["fips"].zfill(5): float(r["customer_hours"]) / float(r["peak_excess"])
        for r in rows
        if float(r["peak_excess"]) > 0
    }
    t0 = epoch(parse_utc(rows[0]["window_start_utc"]))
    t1 = epoch(parse_utc(rows[0]["window_end_utc"]))
    return eq, t0, t1


def _equivalent(series_by_county: np.ndarray, grid: np.ndarray, t0: float, t1: float) -> np.ndarray:
    m = (grid >= t0) & (grid < t1)
    step_h = float(grid[1] - grid[0]) / 3600.0
    peak = series_by_county[:, m].max(axis=1)
    return np.where(peak > 0, series_by_county[:, m].sum(axis=1) * step_h / np.maximum(peak, 1.0), np.nan)


def equivalent_hours(run: ProcessRun, truth: Truth, common: list[str], prm: Params) -> list[Compared]:
    """Customer-hours over the peak in the EAGLE-I window, per county: an integral of the whole curve,
    from a second EAGLE-I aggregation, never used in the fit."""
    if not CUSTOMER_HOURS_CSV.is_file():
        return []
    obs, t0, t1 = load_customer_hours()
    keys = [k for k in common if k in obs]
    grid = run_grid(run, prm.f("process", "horizon_days"), prm.f("process", "step_s"))
    model = _equivalent(series(run_intervals(run, by="fips"), list(keys), grid), grid, t0, t1)
    customers = np.asarray(truth.net.sections["customers"], dtype=float)
    fips = np.asarray(truth.net.sections["fips"])
    base_series = np.stack([truth.out[:, fips == k] @ customers[fips == k] for k in keys])
    base = _equivalent(base_series, truth.times, t0, t1)
    return [
        Compared(
            "county_equivalent_outage_hours_median",
            float(np.nanmedian(model)),
            float(np.median([obs[k] for k in keys])),
            float(np.nanmedian(base)),
            "h",
            False,
        )
    ]


@dataclass(frozen=True)
class Compared:
    """One Helene statistic: model (WP-17 process), observed (EAGLE-I) and the WP-06 generator baseline."""

    name: str
    model: float
    observed: float
    baseline: float
    unit: str
    fitted: bool


@dataclass
class CalibrationReport:
    counties_compared: int
    stats: list[Compared]
    params: dict[str, float]
    story: list[Compared] = field(default_factory=list)
    worlds: list[int] = field(default_factory=list)

    def get(self, name: str) -> Compared:
        return next(c for c in self.stats if c.name == name)


def _spearman(a: list[float], b: list[float]) -> float:
    """Rank correlation with 'never reached' (nan) ranked above every finite time."""
    big = 1e6
    return float(
        spearmanr([big if math.isnan(x) else x for x in a], [big if math.isnan(x) else x for x in b])[0]
    )


def _share_over(v: list[float], h: float) -> float:
    return float(np.mean([math.isnan(x) or x > h for x in v]))


def world_stats(world: World, prm: Params, obs: Observed) -> tuple[int, list[Compared]]:
    """Every compared statistic for one family-A world: WP-17 process vs EAGLE-I vs the WP-06 generator."""
    run = simulate(world, prm)
    h = prm.f("process", "horizon_days")
    step = prm.f("process", "step_s")
    model = county_times(run, h, step)
    truth = run_truth(load_scenario(world.scenario), load_family("A"), seed=world.seed)
    base = truth.county
    common = sorted(set(model) & set(base) & {k for k, v in obs.t50.items() if not math.isnan(v)})

    def col(src: dict[str, dict[str, float]], key: str) -> list[float]:
        return [src[k][key] for k in common]

    m50, m90 = col(model, "t50_h"), col(model, "t90_h")
    b50, b90 = col(base, "t50_h"), col(base, "t90_h")
    o50, o90 = [obs.t50[k] for k in common], [obs.t90[k] for k in common]
    mp, bp, op = col(model, "peak_out"), col(base, "peak_out"), [obs.peak[k] for k in common]

    def trio(name: str, f, unit: str, fitted: bool) -> Compared:  # type: ignore[no-untyped-def]
        return Compared(name, f(m50, m90), f(o50, o90), f(b50, b90), unit, fitted)

    stats = [
        trio("county_t50_median", lambda a, b: censored_median(a), "h", True),
        trio("county_t90_median", lambda a, b: censored_median(b), "h", True),
        trio("county_t90_p75", lambda a, b: censored_percentile(b, 75), "h", False),
        trio("county_t90_p25", lambda a, b: censored_percentile(b, 25), "h", False),
        trio("county_t50_p75", lambda a, b: censored_percentile(a, 75), "h", False),
        trio("county_t90_share_over_week", lambda a, b: _share_over(b, WEEK_H), "share of counties", False),
        Compared(
            "county_t90_spearman", _spearman(m90, o90), 1.0, _spearman(b90, o90), "rank correlation", False
        ),
        Compared(
            "county_t90_peak_weighted_median",
            weighted_median(m90, mp),
            weighted_median(o90, op),
            weighted_median(b90, bp),
            "h",
            False,
        ),
    ]
    stats += equivalent_hours(run, truth, common, prm)
    return len(common), stats


def report(
    prm: Params | None = None, obs: Observed | None = None, worlds: list[World] | None = None
) -> CalibrationReport:
    """The calibration worlds (story seed + 4 train seeds, as fitted) against EAGLE-I; every statistic is
    the mean over worlds, the story seed is kept apart in `story`. The generator is the baseline."""
    prm = prm or default_params()
    obs = obs or load_observed()
    worlds = worlds or calibration_worlds()
    per = [world_stats(w, prm, obs) for w in worlds]
    names = [c.name for c in per[0][1]]
    stats = []
    for i, name in enumerate(names):
        cs = [p[1][i] for p in per]
        stats.append(
            Compared(
                name,
                float(np.mean([c.model for c in cs])),
                float(np.mean([c.observed for c in cs])),
                float(np.mean([c.baseline for c in cs])),
                cs[0].unit,
                cs[0].fitted,
            )
        )
    return CalibrationReport(
        int(min(p[0] for p in per)),
        stats,
        {k: prm.f("process", k) for k in FIT_KEYS},
        story=per[0][1],
        worlds=[int(w.seed) for w in worlds],
    )
