"""Family-A evaluation of the ETR model: fit on train storms, calibrate on calibration storms, score on test.

A storm is one family-A seed of the Helene scenario: the generator's network and damage for that seed and a
restoration-process run with that seed's storm effects. The ETR issued at the global outage peak and 24 h
later is compared with the realised time to 90 percent restored, per operating area and for the footprint.
"""

from __future__ import annotations

import math
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from sgw.models.restoration.conformal import Calibrator, clustered_ci, coverage
from sgw.models.restoration.etr import EtrModel, fit_model, forecast, issue_time, observe, truth_etr
from sgw.models.restoration.params import Params, default_params
from sgw.models.restoration.process import ProcessRun, StormEffects, simulate
from sgw.models.restoration.world import World, family_a_world


def storm_run(seed: int, prm: Params) -> ProcessRun:
    world: World = family_a_world(seed)
    return simulate(world, prm, StormEffects.draw(world, prm, seed), seed)


@dataclass(frozen=True)
class IssueRows:
    seed: int
    offset_h: float
    as_of: float
    region_q: np.ndarray
    region_y: np.ndarray
    region_ok: np.ndarray
    region_analog: np.ndarray
    global_q: np.ndarray
    global_y: float
    global_analog: float


def analog_hours(peak_t: float, as_of: float, analog_t90_h: float) -> float:
    """Historical-analog baseline: the region's peak time plus the observed Helene county median t90."""
    return max((peak_t + analog_t90_h * 3600.0 - as_of) / 3600.0, 0.25)


def storm_rows(seed: int, model: EtrModel, prm: Params, analog_t90_h: float) -> list[IssueRows]:
    run = storm_run(seed, prm)
    members = int(prm.f("etr", "members"))
    out = []
    for off in prm.arr("etr", "issue_offsets_h"):
        as_of = issue_time(run, prm, float(off))
        obs = observe(run, as_of, prm, seed)
        fc = forecast(model, obs, prm, members=members, seed=seed)
        rq, gq = fc.quantiles()
        ry, gy = truth_etr(run, obs, prm)
        ok = fc.eligible & np.isfinite(ry) & (ry > 0)
        analog = np.array([analog_hours(t, as_of, analog_t90_h) for t in obs.peak_time_region])
        out.append(
            IssueRows(
                seed,
                float(off),
                as_of,
                rq,
                ry,
                ok,
                analog,
                gq,
                gy,
                analog_hours(obs.peak_time_global, as_of, analog_t90_h),
            )
        )
    return out


@dataclass
class Population:
    q: np.ndarray
    y: np.ndarray
    seed: np.ndarray
    analog: np.ndarray

    @classmethod
    def collect(cls, rows: list[IssueRows], offset: float, regional: bool) -> Population:
        qs, ys, ss, an = [], [], [], []
        for r in rows:
            if r.offset_h != offset:
                continue
            if regional:
                m = r.region_ok
                qs.append(r.region_q[m])
                ys.append(r.region_y[m])
                ss.append(np.full(int(m.sum()), r.seed))
                an.append(r.region_analog[m])
            elif math.isfinite(r.global_y) and r.global_y > 0:
                qs.append(r.global_q[None, :])
                ys.append(np.array([r.global_y]))
                ss.append(np.array([r.seed]))
                an.append(np.array([r.global_analog]))
        if not qs:
            return cls(np.zeros((0, 5)), np.zeros(0), np.zeros(0, dtype=int), np.zeros(0))
        return cls(np.concatenate(qs), np.concatenate(ys), np.concatenate(ss), np.concatenate(an))

    def subset(self, seeds: set[int]) -> Population:
        m = np.isin(self.seed, list(seeds))
        return Population(self.q[m], self.y[m], self.seed[m], self.analog[m])


@dataclass
class Score:
    population: str
    offset_h: float
    n: int
    n_storms: int
    coverage80: float
    coverage80_ci: tuple[float, float]
    coverage80_raw: float
    coverage50: float
    coverage50_ci: tuple[float, float]
    coverage50_raw: float
    coverage80_wilson: tuple[float, float]
    coverage80_shrunk10: float
    coverage80_widened10: float
    width80_median_h: float
    width50_median_h: float
    width80_rel: float
    width80_rel_raw: float
    width50_rel: float
    width50_rel_raw: float
    p50_mdape: float
    analog_mdape: float
    calibrator: Calibrator


def mdape(pred: np.ndarray, y: np.ndarray) -> float:
    return float(np.median(np.abs(pred - y) / np.maximum(y, 1.0)))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95 percent interval of a binomial share k / n."""
    if n == 0:
        return math.nan, math.nan
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def _union(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return min(a[0], b[0]), max(a[1], b[1])


def _rel_width(q: np.ndarray, hi: int, lo: int) -> float:
    return float(np.median((q[:, hi] - q[:, lo]) / np.maximum(q[:, 2], 0.25)))


def _scaled_coverage(adj: np.ndarray, y: np.ndarray, factor: float) -> float:
    """80 percent coverage with the band's log half-width scaled by `factor` (fragility of a narrow band)."""
    lo, hi = np.log(np.maximum(adj[:, 0], 0.25)), np.log(np.maximum(adj[:, 4], 0.25))
    mid, half = (lo + hi) / 2, (hi - lo) / 2 * factor
    ly = np.log(np.maximum(y, 0.25))
    return float(np.mean((ly >= mid - half) & (ly <= mid + half)))


def score(cal: Population, test: Population, shift_seeds: set[int], name: str, offset: float) -> Score:
    first = cal.subset(shift_seeds)
    rest = cal.subset(set(cal.seed.tolist()) - shift_seeds)
    calib = Calibrator.fit(first.q, first.y, rest.q, rest.y)
    adj = calib.apply(test.q)
    covered = (test.y >= adj[:, 0]) & (test.y <= adj[:, 4])
    covered50 = (test.y >= adj[:, 1]) & (test.y <= adj[:, 3])
    ci = _union(clustered_ci(covered.astype(float), test.seed), wilson(int(covered.sum()), len(covered)))
    ci50 = _union(
        clustered_ci(covered50.astype(float), test.seed), wilson(int(covered50.sum()), len(covered50))
    )
    return Score(
        population=name,
        offset_h=offset,
        n=len(test.y),
        n_storms=len(np.unique(test.seed)),
        coverage80=float(covered.mean()),
        coverage80_ci=ci,
        coverage80_raw=coverage(test.q[:, 0], test.q[:, 4], test.y),
        coverage50=float(covered50.mean()),
        coverage50_ci=ci50,
        coverage50_raw=coverage(test.q[:, 1], test.q[:, 3], test.y),
        coverage80_wilson=wilson(int(covered.sum()), len(covered)),
        coverage80_shrunk10=_scaled_coverage(adj, test.y, 0.9),
        coverage80_widened10=_scaled_coverage(adj, test.y, 1.1),
        width80_median_h=float(np.median(adj[:, 4] - adj[:, 0])),
        width50_median_h=float(np.median(adj[:, 3] - adj[:, 1])),
        width80_rel=_rel_width(adj, 4, 0),
        width80_rel_raw=_rel_width(test.q, 4, 0),
        width50_rel=_rel_width(adj, 3, 1),
        width50_rel_raw=_rel_width(test.q, 3, 1),
        p50_mdape=mdape(adj[:, 2], test.y),
        analog_mdape=mdape(test.analog, test.y),
        calibrator=calib,
    )


@dataclass
class Evaluation:
    model: EtrModel
    scores: list[Score] = field(default_factory=list)
    calibrators: dict[tuple[str, float], Calibrator] = field(default_factory=dict)
    n_train: int = 0
    n_cal: int = 0
    n_test: int = 0


def _rows_worker(args: tuple[int, EtrModel, float]) -> list[IssueRows]:
    seed, model, analog = args
    return storm_rows(seed, model, default_params(), analog)


def _train_worker(seed: int) -> ProcessRun:
    return storm_run(seed, default_params())


def evaluate(analog_t90_h: float, workers: int = 2, limit: int | None = None) -> Evaluation:
    prm = default_params()
    train = prm.seeds("train")[:limit]
    cal = prm.seeds("calibration")[:limit]
    test = prm.seeds("test")[:limit]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(_train_worker, train))
        model = fit_model(runs, prm)
        del runs
        jobs = [(s, model, analog_t90_h) for s in cal + test]
        rows = [r for chunk in pool.map(_rows_worker, jobs) for r in chunk]
    cal_rows = [r for r in rows if r.seed in set(cal)]
    test_rows = [r for r in rows if r.seed in set(test)]
    shift_seeds = set(cal[: max(1, len(cal) // 3)])
    ev = Evaluation(model, n_train=len(train), n_cal=len(cal), n_test=len(test))
    for off in prm.arr("etr", "issue_offsets_h"):
        for name, regional in (("regional", True), ("global", False)):
            sc = score(
                Population.collect(cal_rows, float(off), regional),
                Population.collect(test_rows, float(off), regional),
                shift_seeds,
                name,
                float(off),
            )
            ev.scores.append(sc)
            ev.calibrators[(name, float(off))] = sc.calibrator
    return ev
