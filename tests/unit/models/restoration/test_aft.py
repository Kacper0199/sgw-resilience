from __future__ import annotations

import numpy as np
import pytest

from sgw.models.restoration.aft import StratifiedAft, county_spread, fit_aft, fit_stratified


def _censored(n: int, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    r = np.random.default_rng(seed)
    group = r.integers(0, 2, n)
    x = np.column_stack([np.ones(n), group == 1])
    y = x @ np.array([1.0, 0.8]) + np.array([0.5, 0.3])[group] * r.standard_normal(n)
    cut = np.log(r.uniform(1.0, 8.0, n))
    event = y <= cut
    return x, np.minimum(y, cut), event, group


def test_censored_mle_recovers_location_and_scale_where_dropping_censored_rows_does_not() -> None:
    x, y, event, group = _censored(6000, 1)
    assert 0.2 < 1 - event.mean() < 0.6
    fit = fit_aft(x, y, event, group)
    assert fit.converged
    assert fit.beta == pytest.approx([1.0, 0.8], abs=0.05)
    assert fit.sigma == pytest.approx([0.5, 0.3], abs=0.04)
    naive = fit_aft(x[event], y[event], np.ones(int(event.sum()), dtype=bool), group[event])
    assert naive.beta[0] + naive.beta[1] < 1.8 - 0.1


def _storms(seed: int, storm_sigma: float = 0.3, n_storms: int = 12) -> tuple[np.ndarray, ...]:
    r = np.random.default_rng(seed)
    mu = np.array([1.0, 2.5, 4.0])
    sig = np.array([0.4, 0.5, 0.6])
    rho = r.normal(0.0, storm_sigma, n_storms)
    st = r.integers(0, 3, 9000)
    storm = r.integers(0, n_storms, 9000)
    y = mu[st] + rho[storm] + sig[st] * r.standard_normal(9000)
    return st, storm, y, rho


def test_stratified_fit_recovers_strata_and_the_storm_spread() -> None:
    st, storm, y, rho = _storms(2)
    aft = fit_stratified(st, storm, y, np.ones(len(y), dtype=bool), ("a", "b", "c"))
    assert aft.mu + rho.mean() == pytest.approx([1.0, 2.5, 4.0], abs=0.05)
    assert aft.sigma == pytest.approx([0.4, 0.5, 0.6], abs=0.03)
    assert np.corrcoef(aft.storm_effects, rho)[0, 1] > 0.98
    assert aft.storm_sigma == pytest.approx(np.std(rho, ddof=1), abs=0.03)


def test_storm_posterior_concentrates_on_the_true_effect_and_uses_censored_jobs() -> None:
    aft = StratifiedAft(("a",), np.array([2.0]), np.array([0.5]), 0.3, np.zeros(1))
    r = np.random.default_rng(3)
    true = 0.25
    w = 2.0 + true + 0.5 * r.standard_normal(400)
    grid, p = aft.rho_posterior(np.zeros(400, dtype=int), w, np.ones(400, dtype=bool))
    assert abs(float(np.dot(grid, p)) - true) < 0.06
    prior_grid, prior = aft.rho_posterior(np.zeros(0, dtype=int), np.zeros(0), np.zeros(0, dtype=bool))
    assert abs(float(np.dot(prior_grid, prior))) < 1e-9
    still_running = np.full(50, 2.0 + 1.0)
    g2, p2 = aft.rho_posterior(np.zeros(50, dtype=int), still_running, np.zeros(50, dtype=bool))
    assert float(np.dot(g2, p2)) > 0.3


def test_in_progress_work_is_sampled_beyond_what_is_done() -> None:
    aft = StratifiedAft(("a",), np.array([1.0]), np.array([0.5]), 0.2, np.zeros(1))
    r = np.random.default_rng(4)
    done = np.full(5000, np.exp(1.5))
    beyond = aft.sample_beyond(np.zeros(5000, dtype=int), done, 0.0, r)
    free = aft.sample(np.zeros(5000, dtype=int), 0.0, r)
    assert np.all(beyond >= done)
    assert beyond.mean() > free.mean()


def test_county_spread_recovers_the_between_county_sigma() -> None:
    r = np.random.default_rng(6)
    county = r.integers(0, 150, 20000)
    effect = r.normal(0.0, 0.5, 150)
    st = np.zeros(20000, dtype=int)
    resid = effect[county] + 0.4 * r.standard_normal(20000)
    total = np.array([float(np.std(resid))])
    c_sigma, c_eff, within = county_spread(st, county, resid, total)
    assert c_sigma == pytest.approx(0.5, abs=0.07)
    assert within[0] == pytest.approx(0.4, abs=0.03)
    assert np.corrcoef(c_eff, effect[county])[0, 1] > 0.95


def test_county_draws_follow_the_county_jobs() -> None:
    aft = StratifiedAft(("a",), np.array([2.0]), np.array([0.3]), 0.2, np.zeros(1), county_sigma=0.5)
    r = np.random.default_rng(7)
    county = np.repeat([0, 1], 60)
    w = 2.0 + np.where(county == 0, 0.6, -0.6) + 0.3 * r.standard_normal(120)
    draws = aft.county_draws(np.zeros(120, dtype=int), w, np.ones(120, dtype=bool), county, 3, 0.0, 400, r)
    assert draws.shape == (400, 3)
    assert draws[:, 0].mean() > 0.4 and draws[:, 1].mean() < -0.4
    assert abs(draws[:, 2].mean()) < 0.1 and 0.35 < draws[:, 2].std() < 0.65
