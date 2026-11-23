from __future__ import annotations

import math

import numpy as np
import pytest

from sgw.models.restoration.conformal import Calibrator, clustered_ci, conformal_quantile, coverage
from sgw.models.restoration.curves import Intervals, hours_to_share, series
from sgw.models.restoration.etr import time_to_threshold
from sgw.models.restoration.params import DutyClock, default_params, load_params

H = 3600.0
DAY = 86400.0


def test_every_parameter_carries_a_known_label_and_the_splits_are_disjoint() -> None:
    prm = load_params()
    assert all(p.label in {"F", "C", "A", "P"} for g in prm.groups.values() for p in g.values())
    train, cal, test = (set(prm.seeds(s)) for s in ("train", "calibration", "test"))
    assert not (train & cal or train & test or cal & test)


def test_duty_clock_skips_the_rest_period() -> None:
    clock = DutyClock(on_h=16.0, start_utc_h=10.0)
    assert clock.hours(10 * H) == pytest.approx(0.0)
    assert clock.hours(26 * H) == pytest.approx(16.0)
    assert clock.hours(30 * H) == pytest.approx(16.0)
    assert clock.finish(24 * H, 3.0) == pytest.approx(35 * H)
    assert clock.finish(30 * H, 1.0) == pytest.approx(35 * H)
    assert clock.finish(12 * H, 14.0) == pytest.approx(26 * H)


def test_duty_clock_round_trips_on_duty_times() -> None:
    clock = DutyClock.from_params(default_params())
    t = np.array([10.5, 15.0, 25.9, 35.0, 49.0]) * H + 3 * DAY
    assert np.allclose(clock.wall(clock.hours(t)), t)


def test_time_to_threshold_on_a_hand_example() -> None:
    ends = np.array([5.0, 10.0, 20.0, 40.0]) * H
    customers = np.array([100.0, 50.0, 30.0, 20.0])
    assert time_to_threshold(ends, customers, 25.0, 0.0) == pytest.approx(20 * H)
    assert time_to_threshold(ends, customers, 50.0, 0.0) == pytest.approx(10 * H)
    assert time_to_threshold(ends, customers, 10.0, 0.0) == pytest.approx(40 * H)
    assert time_to_threshold(ends, customers, 200.0, 0.0) == 0.0
    assert time_to_threshold(ends, customers, 25.0, 30 * H) == pytest.approx(30 * H)


def test_series_conserves_customers_and_reads_t50_t90_from_the_peak() -> None:
    grid = np.arange(0.0, 100 * H, 900.0)
    iv = Intervals(
        key=np.array([0, 0, 0, 1]),
        customers=np.array([60.0, 30.0, 10.0, 5.0]),
        start=np.array([1, 2, 2, 3]) * H,
        end=np.array([10, 30, 50, np.inf]) * H,
    )
    s = series(iv, [0, 1], grid)
    assert s[0].max() == 100.0
    assert s[0, -1] == 0.0 and s[1, -1] == 5.0
    peak, tpeak, t50 = hours_to_share(s[0], grid, 0.5)
    _, _, t90 = hours_to_share(s[0], grid, 0.9)
    assert (peak, tpeak / H, t50, t90) == (100.0, 2.0, 8.0, 28.0)
    assert math.isnan(hours_to_share(s[1], grid, 0.9)[2])


def test_conformal_quantile_is_the_finite_sample_rank() -> None:
    scores = np.arange(1.0, 11.0)
    assert conformal_quantile(scores, 0.2) == 9.0
    assert math.isinf(conformal_quantile(scores[:3], 0.2))


def test_calibrator_restores_80_percent_coverage_of_a_biased_overconfident_model() -> None:
    r = np.random.default_rng(5)

    def draw(n: int) -> tuple[np.ndarray, np.ndarray]:
        mu = r.uniform(3.0, 5.0, n)
        y = np.exp(mu + 0.4 * r.standard_normal(n))
        z = np.array([-1.2816, -0.6745, 0.0, 0.6745, 1.2816])
        q = np.exp(mu[:, None] + 0.2 + 0.15 * z[None, :])
        return q, y

    q1, y1 = draw(400)
    q2, y2 = draw(800)
    qt, yt = draw(4000)
    raw = coverage(qt[:, 0], qt[:, 4], yt)
    cal = Calibrator.fit(q1, y1, q2, y2)
    adj = cal.apply(qt)
    assert raw < 0.5
    assert abs(coverage(adj[:, 0], adj[:, 4], yt) - 0.8) < 0.03
    assert abs(coverage(adj[:, 1], adj[:, 3], yt) - 0.5) < 0.04
    assert np.all(np.diff(adj, axis=1) >= 0)


def test_clustered_interval_contains_the_rate() -> None:
    covered = np.array([1, 1, 0, 1, 1, 1, 0, 1, 1, 1], dtype=float)
    cluster = np.repeat(np.arange(5), 2)
    lo, hi = clustered_ci(covered, cluster, n_boot=500)
    assert lo <= covered.mean() <= hi
