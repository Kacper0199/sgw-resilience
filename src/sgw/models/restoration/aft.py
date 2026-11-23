"""Log-normal accelerated failure time model for restoration job work, with right censoring.

log W_i = x_i' beta + rho_storm + sigma_g(i) * eps_i,  eps ~ N(0, 1)

W is the line-crew work of one job (hours); strata g are the job type and damage state; rho_storm is a
storm-level productivity effect shared by every job of one storm. Jobs still in progress at the issue time
are right-censored at the work done so far. Training (complete storms) estimates beta, sigma_g and the spread
of rho across storms; during a storm the posterior of rho is updated from finished and in-progress jobs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.special import log_ndtr, ndtri
from scipy.stats import norm

LOG_2PI = float(np.log(2.0 * np.pi))


@dataclass(frozen=True)
class AftFit:
    beta: np.ndarray
    log_sigma: np.ndarray
    converged: bool
    loglik: float

    @property
    def sigma(self) -> np.ndarray:
        return np.exp(self.log_sigma)


def _mills(z: np.ndarray) -> np.ndarray:
    """phi(z) / (1 - Phi(z)), stable for large z."""
    return np.exp(norm.logpdf(z) - log_ndtr(-z))


def negloglik(
    theta: np.ndarray, x: np.ndarray, y: np.ndarray, event: np.ndarray, group: np.ndarray, n_groups: int
) -> tuple[float, np.ndarray]:
    p = x.shape[1]
    beta, log_s = theta[:p], theta[p : p + n_groups]
    s = np.exp(log_s)[group]
    z = (y - x @ beta) / s
    ll_e = -np.log(s) - 0.5 * z**2 - 0.5 * LOG_2PI
    ll_c = log_ndtr(-z)
    ll = np.where(event, ll_e, ll_c)
    dz = np.where(event, z, _mills(z))
    g_beta = -(x * (dz / s)[:, None]).sum(axis=0)
    d_logs = np.where(event, -1.0 + z**2, z * _mills(z))
    g_logs = -np.bincount(group, weights=d_logs, minlength=n_groups)
    return float(-ll.sum()), np.concatenate([g_beta, g_logs])


def fit_aft(
    x: np.ndarray, log_w: np.ndarray, event: np.ndarray, group: np.ndarray, n_groups: int | None = None
) -> AftFit:
    """Censored maximum likelihood (L-BFGS-B, analytic gradient); starts from least squares on events."""
    event = np.asarray(event, dtype=bool)
    group = np.asarray(group, dtype=int)
    n_groups = int(group.max()) + 1 if n_groups is None else n_groups
    beta0 = np.linalg.lstsq(x[event], log_w[event], rcond=None)[0]
    resid = log_w - x @ beta0
    s0 = np.array(
        [
            max(np.std(resid[event & (group == g)]) if np.any(event & (group == g)) else 1.0, 0.05)
            for g in range(n_groups)
        ]
    )
    theta0 = np.concatenate([beta0, np.log(s0)])
    res = minimize(
        negloglik,
        theta0,
        args=(x, log_w, event, group, n_groups),
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": 500},
    )
    p = x.shape[1]
    return AftFit(res.x[:p], res.x[p:], bool(res.success), float(-res.fun))


@dataclass(frozen=True)
class StratifiedAft:
    """Location per stratum, within-county sigma per stratum, storm and county random-effect spreads.

    `sigma_total` (no county effect) scores jobs for the storm-level posterior, which treats the jobs of a
    storm as independent; `sigma` (county effect removed) is the job-to-job spread once the county is known.
    """

    strata: tuple[str, ...]
    mu: np.ndarray
    sigma: np.ndarray
    storm_sigma: float
    storm_effects: np.ndarray
    county_sigma: float = 0.0
    sigma_total: np.ndarray | None = None

    def _total(self) -> np.ndarray:
        return self.sigma if self.sigma_total is None else self.sigma_total

    def mean(self, stratum: np.ndarray, rho: float = 0.0) -> np.ndarray:
        return np.exp(self.mu[stratum] + rho + 0.5 * self.sigma[stratum] ** 2)

    def sample(
        self, stratum: np.ndarray, rho: float, r: np.random.Generator, offset: np.ndarray | float = 0.0
    ) -> np.ndarray:
        z = r.standard_normal(len(stratum))
        return np.exp(self.mu[stratum] + rho + offset + self.sigma[stratum] * z)

    def sample_beyond(
        self,
        stratum: np.ndarray,
        done: np.ndarray,
        rho: float,
        r: np.random.Generator,
        offset: np.ndarray | float = 0.0,
    ) -> np.ndarray:
        """Total work of in-progress jobs given that `done` hours are already spent (truncated log-normal)."""
        mu = self.mu[stratum] + rho + offset
        s = self.sigma[stratum]
        a = norm.cdf((np.log(np.maximum(done, 1e-9)) - mu) / s)
        u = a + (1.0 - a) * r.uniform(size=len(stratum))
        z = ndtri(np.clip(u, 1e-12, 1.0 - 1e-12))
        return np.maximum(np.exp(mu + s * z), done)

    def rho_posterior(
        self,
        stratum: np.ndarray,
        log_w: np.ndarray,
        event: np.ndarray,
        grid: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Grid posterior of this storm's rho from finished (event) and in-progress (censored) jobs."""
        grid = np.linspace(-4 * self.storm_sigma, 4 * self.storm_sigma, 161) if grid is None else grid
        logp = norm.logpdf(grid, 0.0, max(self.storm_sigma, 1e-6))
        if len(stratum):
            mu = self.mu[stratum][None, :] + grid[:, None]
            s = self._total()[stratum][None, :]
            z = (log_w[None, :] - mu) / s
            ll = np.where(event[None, :], -np.log(s) - 0.5 * z**2, log_ndtr(-z))
            logp = logp + ll.sum(axis=1)
        w = np.exp(logp - logp.max())
        return grid, w / w.sum()

    def county_draws(
        self,
        stratum: np.ndarray,
        log_w: np.ndarray,
        event: np.ndarray,
        county: np.ndarray,
        n_counties: int,
        rho: float,
        draws: int,
        r: np.random.Generator,
    ) -> np.ndarray:
        """[draws, n_counties] samples of each county's effect from its grid posterior (prior
        N(0, county_sigma)) given the county's finished and in-progress jobs and this storm's rho."""
        sc = max(self.county_sigma, 1e-6)
        grid = np.linspace(-4 * sc, 4 * sc, 81)
        logp = np.tile(norm.logpdf(grid, 0.0, sc)[:, None], (1, n_counties))
        if len(stratum):
            mu = self.mu[stratum][None, :] + rho + grid[:, None]
            s = self.sigma[stratum][None, :]
            z = (log_w[None, :] - mu) / s
            ll = np.where(event[None, :], -np.log(s) - 0.5 * z**2, log_ndtr(-z))
            acc = np.zeros((len(grid), n_counties))
            np.add.at(acc.T, county, ll.T)
            logp = logp + acc
        w = np.exp(logp - logp.max(axis=0, keepdims=True))
        cdf = np.cumsum(w, axis=0)
        cdf /= cdf[-1:, :]
        u = r.uniform(size=(draws, n_counties))
        idx = np.array([np.searchsorted(cdf[:, c], u[:, c]) for c in range(n_counties)]).T
        return grid[np.minimum(idx, len(grid) - 1)]


def county_spread(
    stratum: np.ndarray, county_key: np.ndarray, resid: np.ndarray, sigma: np.ndarray, min_jobs: int = 5
) -> tuple[float, np.ndarray, np.ndarray]:
    """Method-of-moments county spread from residuals after strata and storm effects; returns
    (county_sigma, shrunken county effect per job, within-county sigma per stratum)."""
    _, inv = np.unique(county_key, return_inverse=True)
    prec = 1.0 / sigma[stratum] ** 2
    sw = np.bincount(inv, weights=prec)
    mean = np.bincount(inv, weights=prec * resid) / sw
    n = np.bincount(inv)
    ok = n >= min_jobs
    var = float(max(np.var(mean[ok], ddof=1) - np.mean(1.0 / sw[ok]), 0.0)) if ok.sum() > 2 else 0.0
    shrink = var / (var + 1.0 / sw)
    eff = (mean * shrink)[inv]
    within = np.array(
        [
            float(np.std(resid[stratum == k] - eff[stratum == k])) if np.any(stratum == k) else s
            for k, s in enumerate(sigma)
        ]
    )
    return float(np.sqrt(var)), eff, np.maximum(within, 0.05)


def _strat_nll(
    theta: np.ndarray,
    stratum: np.ndarray,
    s_idx: np.ndarray,
    y: np.ndarray,
    event: np.ndarray,
    k: int,
    n_storm: int,
) -> tuple[float, np.ndarray]:
    mu, free, log_s = theta[:k], theta[k : k + n_storm - 1], theta[k + n_storm - 1 :]
    eff = np.concatenate([free, [-free.sum()]]) if n_storm > 1 else np.zeros(1)
    s = np.exp(log_s)[stratum]
    z = (y - mu[stratum] - eff[s_idx]) / s
    ll = np.where(event, -np.log(s) - 0.5 * z**2 - 0.5 * LOG_2PI, log_ndtr(-z))
    dz = np.where(event, z, _mills(z)) / s
    g_mu = -np.bincount(stratum, weights=dz, minlength=k)
    g_eff = -np.bincount(s_idx, weights=dz, minlength=n_storm)
    g_free = g_eff[:-1] - g_eff[-1] if n_storm > 1 else np.zeros(0)
    d_logs = np.where(event, -1.0 + z**2, z * _mills(z))
    g_logs = -np.bincount(stratum, weights=d_logs, minlength=k)
    return float(-ll.sum()), np.concatenate([g_mu, g_free, g_logs])


def fit_stratified(
    stratum: np.ndarray, storm: np.ndarray, log_w: np.ndarray, event: np.ndarray, strata: tuple[str, ...]
) -> StratifiedAft:
    """Strata intercepts + storm effects (sum to zero), sigma per stratum, by censored maximum likelihood;
    the storm-effect spread is the standard deviation of the fitted effects."""
    stratum = np.asarray(stratum, dtype=int)
    event = np.asarray(event, dtype=bool)
    storms = np.unique(storm)
    s_idx = np.searchsorted(storms, storm)
    k = len(strata)
    n_storm = len(storms)
    mu0 = np.array([np.mean(log_w[stratum == g]) if np.any(stratum == g) else 0.0 for g in range(k)])
    sd0 = np.array(
        [max(float(np.std(log_w[stratum == g])), 0.05) if np.any(stratum == g) else 1.0 for g in range(k)]
    )
    theta0 = np.concatenate([mu0, np.zeros(max(n_storm - 1, 0)), np.log(sd0)])
    res = minimize(
        _strat_nll,
        theta0,
        args=(stratum, s_idx, log_w, event, k, n_storm),
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": 1000},
    )
    mu = res.x[:k]
    free = res.x[k : k + n_storm - 1]
    effects = np.concatenate([free, [-free.sum()]]) if n_storm > 1 else np.zeros(1)
    spread = float(np.std(effects, ddof=1)) if n_storm > 2 else 0.0
    return StratifiedAft(strata, mu, np.exp(res.x[k + n_storm - 1 :]), spread, effects)
