"""A6 ETR model: when will 90 percent of the peak customers out be restored, globally and per operating area.

At an issue time the model sees what an EOC sees: faults so far, sections restored or in progress, damage
states of assessed sections, secondary jobs already visible behind restored sections, the crew roster and
mutual-aid arrivals so far, and the customers-out series up to now. It does not see the truth's damage
states of unassessed sections, job work, hidden secondary jobs, future mutual-aid arrivals or the storm's
productivity. Each Monte Carlo member draws those from fitted components (log-normal AFT with a storm effect
updated from this storm's finished and in-progress jobs, damage state given hazard gust, secondary-job rate,
access clearance, mutual-aid delay) and schedules the remaining work per operating area as a fluid queue on
the area's crew capacity (line crews x duty clock), in dispatch-priority order. Quantiles of the members give
P10..P90; `conformal.py` widens or narrows them to calibrated coverage.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
from scipy.special import ndtri
from scipy.stats import norm

from sgw.generator.config import rng
from sgw.models.restoration.aft import StratifiedAft, county_spread, fit_stratified
from sgw.models.restoration.curves import run_grid, run_intervals, series
from sgw.models.restoration.params import DutyClock, Params, default_params
from sgw.models.restoration.process import SECONDARY, SECTION, ProcessRun, crew_availability

STRATA = ("section_ds1", "section_ds2", "section_ds3", "section_ds4", "secondary")
SEC_STRATUM = 4
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
MODEL_NAME = "sgw-etr-a6"
MODEL_VERSION = "1.0.0"
GLOBAL = "GLOBAL"


def job_strata(run: ProcessRun) -> np.ndarray:
    ds = np.maximum(run.world.ds[run.jobs.section], 1) - 1
    return np.where(run.jobs.kind == SECONDARY, SEC_STRATUM, ds)


def observed_work(
    run: ProcessRun, clock: DutyClock, until: float = math.inf
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(line-crew hours spent, finished?, started?) per job as seen at `until`."""
    started = ~np.isnan(run.start) & (run.start <= until)
    finished = started & (run.end <= until)
    stop = np.where(finished, run.end, np.minimum(until, np.nan_to_num(run.end, nan=until)))
    h = (clock.hours(stop) - clock.hours(np.nan_to_num(run.start, nan=until))) * np.nan_to_num(
        run.lines, nan=0.0
    )
    return np.where(started, np.maximum(h, 0.0), 0.0), finished, started


def hazard_gust(run: ProcessRun, prm: Params, seed: int) -> np.ndarray:
    """The section peak gust as a hazard model estimates it (truth x log-normal error)."""
    r = rng(seed, "wp17", "hazard_gust")
    return run.world.peak_gust * np.exp(
        prm.f("etr", "hazard_gust_sigma") * r.standard_normal(len(run.world.peak_gust))
    )


def mean_matched(
    aft: StratifiedAft, stratum: np.ndarray, offset: np.ndarray, log_w: np.ndarray
) -> StratifiedAft:
    """Shift each stratum's location so the fitted mean work (given the storm and county effects in
    `offset`) equals the observed mean (smearing): the sum of many jobs drives the ETR, and a log-normal
    fitted to non-log-normal work misstates its mean."""
    mu = aft.mu.copy()
    for k in range(len(mu)):
        m = stratum == k
        if m.any():
            fitted = np.exp(mu[k] + offset[m] + 0.5 * aft.sigma[k] ** 2).sum()
            mu[k] += float(np.log(np.exp(log_w[m]).sum() / fitted))
    return replace(aft, mu=mu)


def fit_work_model(
    stratum: np.ndarray, storm: np.ndarray, county_key: np.ndarray, log_w: np.ndarray
) -> StratifiedAft:
    """Storm effects by censored ML, then the county spread from residuals, then mean matching."""
    base = fit_stratified(stratum, storm, log_w, np.ones(len(log_w), dtype=bool), STRATA)
    storm_eff = base.storm_effects[np.searchsorted(np.unique(storm), storm)]
    resid = log_w - base.mu[stratum] - storm_eff
    c_sigma, c_eff, within = county_spread(stratum, county_key, resid, base.sigma)
    aft = replace(base, sigma=within, county_sigma=c_sigma, sigma_total=base.sigma)
    return mean_matched(aft, stratum, storm_eff + c_eff, log_w)


@dataclass(frozen=True)
class EtrModel:
    aft: StratifiedAft
    gust_edges: np.ndarray
    ds_probs: np.ndarray
    sec_rate: np.ndarray
    sec_storm_sigma: float
    sec_customers: np.ndarray
    sec_share: float
    p_blocked: np.ndarray
    access_mu: float
    access_sigma: float
    travel_load: np.ndarray
    train_seeds: tuple[int, ...]

    def expected_work(self, stratum: np.ndarray) -> np.ndarray:
        return self.aft.mean(stratum)


def fit_model(runs: list[ProcessRun], prm: Params | None = None) -> EtrModel:
    """Fit every component on complete training storms (family-A train seeds)."""
    prm = prm or default_params()
    clock = DutyClock.from_params(prm)
    strata, storms, counties, logw, gusts, dss = [], [], [], [], [], []
    sec_n = np.zeros(4)
    sec_exposure = np.zeros(4)
    per_storm_rate = []
    sec_cust = []
    access = []
    blocked = []
    travel: dict[int, list[np.ndarray]] = {SECTION: [], SECONDARY: []}
    for run in runs:
        w, fin, _ = observed_work(run, clock)
        st = job_strata(run)
        ok = fin & (w > 0)
        strata.append(st[ok])
        storms.append(np.full(int(ok.sum()), run.world.seed))
        counties.append(np.char.add(f"{run.world.seed}:", run.world.fips[run.jobs.section[ok]].astype(str)))
        logw.append(np.log(w[ok]))
        world = run.world
        failed = np.flatnonzero(world.failed)
        g = hazard_gust(run, prm, run.world.seed)
        gusts.append(g[failed])
        dss.append(np.maximum(world.ds[failed], 1))
        sec = run.jobs.kind == SECONDARY
        counts = np.bincount(run.jobs.section[sec], minlength=len(world.ds))
        n_s, e_s = np.zeros(4), np.zeros(4)
        np.add.at(n_s, np.maximum(world.ds[failed], 1) - 1, counts[failed])
        np.add.at(e_s, np.maximum(world.ds[failed], 1) - 1, world.customers[failed] / 100.0)
        sec_n += n_s
        sec_exposure += e_s
        per_storm_rate.append((n_s.sum(), e_s))
        sec_cust.append(run.jobs.customers[sec])
        delay = (world.work_ok[failed] - world.base_t[failed]) / 3600.0
        access.append(delay[delay > 1e-6])
        blocked.append(delay > 1e-6)
        tl = (clock.hours(run.arrive) - clock.hours(run.assigned)) * run.lines
        for kind in (SECTION, SECONDARY):
            m = (run.jobs.kind == kind) & ~np.isnan(tl)
            travel[kind].append(tl[m])
    aft = fit_work_model(
        np.concatenate(strata), np.concatenate(storms), np.concatenate(counties), np.concatenate(logw)
    )
    g_all = np.concatenate(gusts)
    d_all = np.concatenate(dss)
    edges = np.quantile(g_all, [0.2, 0.4, 0.6, 0.8])
    bins = np.searchsorted(edges, g_all)
    probs = np.ones((len(edges) + 1, 4))
    np.add.at(probs, (bins, d_all - 1), 1.0)
    probs /= probs.sum(axis=1, keepdims=True)
    b_all = np.concatenate(blocked)
    p_block = np.array(
        [(b_all[bins == k].sum() + 1.0) / ((bins == k).sum() + 2.0) for k in range(len(edges) + 1)]
    )
    rate = sec_n / np.maximum(sec_exposure, 1e-9)
    ratios = [n / max(float(np.dot(rate, e)), 1e-9) for n, e in per_storm_rate]
    sec_sigma = float(np.std(np.log(np.maximum(ratios, 1e-6)), ddof=1)) if len(ratios) > 2 else 0.0
    acc = np.log(np.concatenate(access))
    cust = np.concatenate(sec_cust)
    r = rng(0, "wp17", "sec_customers_sample")
    cust = r.choice(cust, size=min(len(cust), 20000), replace=False) if len(cust) else np.array([1.0])
    return EtrModel(
        aft=aft,
        gust_edges=edges,
        ds_probs=probs,
        sec_rate=rate,
        sec_storm_sigma=sec_sigma,
        sec_customers=np.sort(cust),
        sec_share=prm.f("process", "secondary_max_share"),
        p_blocked=p_block,
        access_mu=float(acc.mean()),
        access_sigma=float(acc.std(ddof=1)),
        travel_load=np.array(
            [
                float(np.mean(np.concatenate(travel[SECTION]))),
                float(np.mean(np.concatenate(travel[SECONDARY]))),
            ]
        ),
        train_seeds=tuple(int(run.world.seed) for run in runs),
    )


@dataclass(frozen=True)
class Observation:
    """What the EOC knows at `as_of` (derived from a process run, never its hidden draws)."""

    run: ProcessRun
    as_of: float
    gust_est: np.ndarray
    peak_region: np.ndarray
    peak_global: float
    out_now_region: np.ndarray
    peak_time_region: np.ndarray
    peak_time_global: float


def observe(run: ProcessRun, as_of: float, prm: Params, seed: int) -> Observation:
    grid = run_grid(run, prm.f("process", "horizon_days"), prm.f("process", "step_s"))
    n_reg = len(run.world.region_ids)
    s = series(run_intervals(run, by="region"), list(range(n_reg)), grid)
    past = grid <= as_of
    seen = s[:, past]
    total = seen.sum(axis=0)
    gp = grid[past]
    now = int(np.flatnonzero(past)[-1])
    return Observation(
        run,
        as_of,
        hazard_gust(run, prm, seed),
        seen.max(axis=1),
        float(total.max()),
        s[:, now],
        gp[np.argmax(seen, axis=1)],
        float(gp[int(np.argmax(total))]),
    )


@dataclass(frozen=True)
class EtrForecast:
    as_of: float
    region_ids: tuple[str, ...]
    samples_h: np.ndarray
    global_h: np.ndarray
    peak_region: np.ndarray
    peak_global: float
    eligible: np.ndarray

    def quantiles(self, qs: tuple[float, ...] = QUANTILES) -> tuple[np.ndarray, np.ndarray]:
        reg = np.quantile(self.samples_h, qs, axis=1).T
        glob = np.quantile(self.global_h, qs)
        return reg, glob


def time_to_threshold(ends: np.ndarray, customers: np.ndarray, threshold: float, as_of: float) -> float:
    """First time after `as_of` with customers still out (end > t) at or below `threshold`."""
    threshold = threshold * (1.0 + 1e-9)
    live = ends > as_of
    e = ends[live]
    c = customers[live]
    if c.sum() <= threshold:
        return as_of
    order = np.argsort(-e)
    cum = np.cumsum(c[order])
    k = int(np.searchsorted(cum, threshold, side="right"))
    return float(e[order][k])


def _capacity_inverse(clock: DutyClock, lines: np.ndarray, avail: np.ndarray, as_of: float, horizon_h: float):
    h0 = float(clock.hours(as_of))
    hs = np.maximum(clock.hours(np.maximum(avail, as_of)), h0)
    order = np.argsort(hs)
    hs, ls = hs[order], lines[order]
    grid_h = h0 + np.arange(0.0, horizon_h + 0.25, 0.25)
    idx = np.searchsorted(hs, grid_h, side="right")
    cum_l = np.concatenate([[0.0], np.cumsum(ls)])
    cum_lh = np.concatenate([[0.0], np.cumsum(ls * hs)])
    cap = grid_h * cum_l[idx] - cum_lh[idx]

    def inverse(c: np.ndarray) -> np.ndarray:
        h = np.interp(c, cap, grid_h, right=np.inf)
        return np.where(np.isfinite(h), clock.wall(np.where(np.isfinite(h), h, 0.0)), np.inf)

    return inverse


def forecast(
    model: EtrModel, obs: Observation, prm: Params | None = None, members: int | None = None, seed: int = 0
) -> EtrForecast:
    prm = prm or default_params()
    clock = DutyClock.from_params(prm)
    members = int(prm.f("etr", "members")) if members is None else members
    share = prm.f("etr", "restored_share")
    run, w, t0 = obs.run, obs.run.world, obs.as_of
    n_reg = len(w.region_ids)
    persons = prm.f("process", "persons_per_line_crew")
    horizon_h = prm.f("process", "horizon_days") * 24.0

    work_done, finished, started = observed_work(run, clock, t0)
    jobs = run.jobs
    strata = job_strata(run)
    is_sec = jobs.kind == SECONDARY
    sec_visible = is_sec & (run.release <= t0)
    sec_rows = np.flatnonzero(sec_visible)

    failed = w.failed & (w.fault_t <= t0)
    sec_job_of = np.full(len(w.ds), -1, dtype=int)
    sec_job_of[jobs.section[~is_sec]] = np.flatnonzero(~is_sec)
    own_done = np.full(len(w.ds), np.nan)
    sj = sec_job_of[failed]
    own_done[failed] = np.where(finished[sj], run.end[sj], np.nan)
    assessed = failed & (w.work_ok <= t0)

    obs_rows = np.flatnonzero((finished | started) & (~is_sec | sec_visible))
    obs_rows = obs_rows[(~is_sec[obs_rows]) | sec_visible[obs_rows]]
    obs_rows = obs_rows[
        (jobs.kind[obs_rows] == SECONDARY) | assessed[jobs.section[obs_rows]] | started[obs_rows]
    ]
    ok = work_done[obs_rows] > 0
    rho_grid, rho_w = model.aft.rho_posterior(
        strata[obs_rows][ok], np.log(work_done[obs_rows][ok]), finished[obs_rows][ok]
    )
    fips_keys, county_of_section = np.unique(w.fips, return_inverse=True)
    r_c = rng(seed, "wp17", "etr_county", w.seed, int(t0))
    c_draws = model.aft.county_draws(
        strata[obs_rows][ok],
        np.log(work_done[obs_rows][ok]),
        finished[obs_rows][ok],
        county_of_section[jobs.section[obs_rows][ok]],
        len(fips_keys),
        float(np.dot(rho_grid, rho_w)),
        members,
        r_c,
    )

    restored_parent = np.zeros(len(w.ds), dtype=bool)
    vis_parents = np.unique(jobs.section[sec_rows])
    restored_parent[vis_parents] = True
    trunk = w.trunk_of
    eff_known = failed & ~np.isnan(own_done) & (~failed[trunk] | ~np.isnan(own_done[trunk]))
    seen_counts = np.bincount(jobs.section[sec_rows], minlength=len(w.ds))
    exposure = w.customers[eff_known] / 100.0
    dsk = np.maximum(w.ds[eff_known], 1) - 1
    nu_grid = np.linspace(-4 * max(model.sec_storm_sigma, 1e-3), 4 * max(model.sec_storm_sigma, 1e-3), 121)
    lam = (model.sec_rate[dsk] * exposure)[None, :] * np.exp(nu_grid)[:, None]
    ll = (seen_counts[eff_known][None, :] * np.log(np.maximum(lam, 1e-12)) - lam).sum(axis=1)
    lp = ll + norm.logpdf(nu_grid, 0.0, max(model.sec_storm_sigma, 1e-3))
    nu_w = np.exp(lp - lp.max())
    nu_w /= nu_w.sum()

    crew_lines = w.crew_headcount / persons
    lbar_all = float(crew_lines.mean())
    ma_known = run.world.crew_mutual_aid
    avail_true = crew_availability(w, run.effects, w.seed)
    open_secs = np.flatnonzero(failed & np.isnan(own_done))
    unassessed = open_secs[~assessed[open_secs]]
    gbin = np.searchsorted(model.gust_edges, obs.gust_est)
    exp_by_stratum = model.aft.mean(np.arange(len(STRATA)))
    ds_exp = model.ds_probs @ exp_by_stratum[:4]
    r = rng(seed, "wp17", "etr_forecast", w.seed, int(t0))
    peak_r = obs.peak_region
    thr_r = (1.0 - share) * peak_r
    thr_g = (1.0 - share) * obs.peak_global
    eligible = (peak_r >= prm.f("etr", "min_region_peak")) & (obs.out_now_region > thr_r)
    samples = np.full((n_reg, members), np.nan)
    glob = np.full(members, np.nan)
    out_start, _ = run.section_out
    out_now = ~np.isnan(out_start) & (out_start <= t0)
    sec_customers_seen = np.zeros(len(w.ds))
    np.add.at(sec_customers_seen, jobs.section[sec_rows], jobs.customers[sec_rows])
    travel_s, travel_2 = model.travel_load

    for m in range(members):
        rho = float(r.choice(rho_grid, p=rho_w))
        c_sec = c_draws[m][county_of_section]
        nu = float(r.choice(nu_grid, p=nu_w))
        ds_m = w.ds.copy()
        if len(unassessed):
            u = r.uniform(size=len(unassessed))
            cdf = np.cumsum(model.ds_probs[gbin[unassessed]], axis=1)
            ds_m[unassessed] = 1 + (u[:, None] > cdf).sum(axis=1)
        rel = np.where(assessed, w.work_ok, np.nan)
        if len(unassessed):
            base = w.base_t[unassessed]
            gap = np.maximum((t0 - base) / 3600.0, 1e-6)
            a = norm.cdf((np.log(gap) - model.access_mu) / model.access_sigma)
            z = ndtri(np.clip(a + (1 - a) * r.uniform(size=len(unassessed)), 1e-12, 1 - 1e-12))
            delay = np.exp(model.access_mu + model.access_sigma * z) * 3600.0
            calm_later = base > t0
            is_blocked = ~calm_later | (r.uniform(size=len(unassessed)) < model.p_blocked[gbin[unassessed]])
            rel[unassessed] = base + np.where(is_blocked, delay, 0.0)
        avail = avail_true.copy()
        pending = ma_known & (avail_true > t0)
        if pending.any():
            gap = np.maximum((t0 - w.request_t) / 3600.0, 1e-6)
            mu_a, s_a = math.log(w.mutual_aid_median_h), w.mutual_aid_sigma
            a = norm.cdf((math.log(gap) - mu_a) / s_a)
            z = ndtri(np.clip(a + (1 - a) * r.uniform(size=int(pending.sum())), 1e-12, 1 - 1e-12))
            avail[pending] = w.request_t + np.exp(mu_a + s_a * z) * 3600.0

        st_open = np.maximum(ds_m[open_secs], 1) - 1
        jidx_open = sec_job_of[open_secs]
        in_prog = started[jidx_open]
        off_open = c_sec[open_secs]
        work = model.aft.sample(st_open, rho, r, off_open)
        if in_prog.any():
            work[in_prog] = model.aft.sample_beyond(
                st_open[in_prog], work_done[jidx_open][in_prog], rho, r, off_open[in_prog]
            )
        remaining = np.where(in_prog, work - work_done[jidx_open], work)
        load_sec = np.where(in_prog, remaining, travel_s + remaining)
        rel_sec = np.where(in_prog, t0, np.nan_to_num(rel[open_secs], nan=t0))
        exp_sec = np.where(assessed[open_secs], exp_by_stratum[st_open], ds_exp[gbin[open_secs]])
        score_sec = (
            w.weight[open_secs] / (travel_s + exp_sec)
            + np.where(w.critical[open_secs], 1e12, 0.0)
            + np.where(in_prog, 1e15, 0.0)
        )

        vis_open = sec_rows[~finished[sec_rows]]
        vis_prog = started[vis_open]
        off_vis = c_sec[jobs.section[vis_open]]
        vw = model.aft.sample(np.full(len(vis_open), SEC_STRATUM), rho, r, off_vis)
        if vis_prog.any():
            vw[vis_prog] = model.aft.sample_beyond(
                np.full(int(vis_prog.sum()), SEC_STRATUM),
                work_done[vis_open][vis_prog],
                rho,
                r,
                off_vis[vis_prog],
            )
        vis_load = np.where(vis_prog, vw - work_done[vis_open], travel_2 + vw)
        vis_cust_score = jobs.customers[vis_open] / (travel_2 + exp_by_stratum[SEC_STRATUM])

        hid_par = open_secs
        lam = model.sec_rate[st_open] * w.customers[hid_par] / 100.0 * math.exp(nu)
        n_hid = r.poisson(lam)
        par = np.repeat(hid_par, n_hid)
        cust = (
            model.sec_customers[r.integers(0, len(model.sec_customers), size=len(par))]
            if len(par)
            else np.zeros(0)
        )
        if len(par):
            order_p = np.argsort(par, kind="stable")
            par, cust = par[order_p], cust[order_p]
            first = np.searchsorted(par, par, side="left")
            csum = np.cumsum(cust)
            within = csum - np.concatenate([[0.0], csum])[first]
            keep = within <= model.sec_share * w.customers[par]
            par, cust = par[keep], cust[keep]
        hw = model.aft.sample(np.full(len(par), SEC_STRATUM), rho, r, c_sec[par])
        hid_load = travel_2 + hw
        hid_customers_by_sec = np.zeros(len(w.ds))
        np.add.at(hid_customers_by_sec, par, cust)

        own_end = own_done.copy()
        region_sec = w.region[open_secs]
        sec_end_vis = np.full(len(vis_open), np.nan)
        sec_end_hid = np.full(len(par), np.nan)
        reg_vis = jobs.region[vis_open]
        reg_hid = w.region[par]
        for reg in range(n_reg):
            crews = w.crew_region == reg
            if not crews.any():
                continue
            lbar = float(crew_lines[crews].mean())
            inv = _capacity_inverse(clock, crew_lines[crews], avail[crews], t0, horizon_h)
            a_idx = np.flatnonzero(region_sec == reg)
            v_idx = np.flatnonzero(reg_vis == reg)
            h_idx = np.flatnonzero(reg_hid == reg)
            sec_score = np.concatenate(
                [
                    vis_cust_score[v_idx] + np.where(vis_prog[v_idx], 1e15, 0.0),
                    cust[h_idx] / (travel_2 + exp_by_stratum[SEC_STRATUM]),
                ]
            )
            score = np.concatenate([score_sec[a_idx], sec_score])
            load = np.concatenate([load_sec[a_idx], vis_load[v_idx], hid_load[h_idx]])
            order = np.argsort(-score, kind="stable")
            t_cap = np.empty(len(load))
            t_cap[order] = inv(np.cumsum(load[order]))
            n_a = len(a_idx)
            own_end[open_secs[a_idx]] = np.maximum(
                t_cap[:n_a], clock.finish(rel_sec[a_idx], remaining[a_idx] / lbar)
            )
            sec_end_vis[v_idx] = t_cap[n_a : n_a + len(v_idx)]
            sec_end_hid[h_idx] = t_cap[n_a + len(v_idx) :]

        trunk_end = np.where(failed[trunk], own_end[trunk], -np.inf)
        sec_out_end = np.fmax(np.where(failed, own_end, -np.inf), trunk_end)
        sec_out_end = np.where(np.isnan(sec_out_end), np.inf, sec_out_end)
        vis_parent_end = sec_out_end[jobs.section[vis_open]]
        vis_end = np.maximum(
            vis_parent_end,
            np.where(
                vis_prog,
                sec_end_vis,
                np.maximum(
                    sec_end_vis,
                    clock.finish(np.where(np.isfinite(vis_parent_end), vis_parent_end, t0), vw / lbar_all),
                ),
            ),
        )
        hid_end = np.maximum(
            sec_out_end[par],
            np.maximum(
                sec_end_hid,
                clock.finish(np.where(np.isfinite(sec_out_end[par]), sec_out_end[par], t0), hw / lbar_all),
            ),
        )
        prim_c = w.customers - sec_customers_seen - hid_customers_by_sec
        rows = np.flatnonzero(out_now)
        ends_all = np.concatenate([sec_out_end[rows], vis_end, hid_end])
        regs_all = np.concatenate([w.region[rows], jobs.region[vis_open], reg_hid])
        cust_all = np.concatenate([prim_c[rows], jobs.customers[vis_open], cust])
        for k_reg in np.flatnonzero(eligible):
            m_r = regs_all == k_reg
            samples[k_reg, m] = (
                time_to_threshold(ends_all[m_r], cust_all[m_r], thr_r[k_reg], t0) - t0
            ) / 3600.0
        glob[m] = (time_to_threshold(ends_all, cust_all, thr_g, t0) - t0) / 3600.0
    return EtrForecast(t0, w.region_ids, samples, glob, peak_r, obs.peak_global, eligible)


def declared_peak_time(run: ProcessRun, prm: Params) -> float:
    """When an EOC can declare the footprint outage peak live: the first time the customers-out total has
    stayed below its running maximum for `peak_hold_h` hours. Uses only data up to that time."""
    grid = run_grid(run, prm.f("process", "horizon_days"), prm.f("process", "step_s"))
    total = series(run_intervals(run, by="region"), list(range(len(run.world.region_ids))), grid).sum(axis=0)
    hold = prm.f("etr", "peak_hold_h") * 3600.0
    run_max = np.maximum.accumulate(total)
    t_max = grid[0]
    for k in range(1, len(grid)):
        if total[k] >= run_max[k - 1] and total[k] > 0:
            t_max = grid[k]
        elif run_max[k] > 0 and grid[k] - t_max >= hold:
            return float(grid[k])
    return float(grid[-1])


def issue_time(run: ProcessRun, prm: Params, hours_after_declared_peak: float) -> float:
    return declared_peak_time(run, prm) + hours_after_declared_peak * 3600.0


def truth_etr(run: ProcessRun, obs: Observation, prm: Params) -> tuple[np.ndarray, float]:
    """Realised hours from the issue time until customers out (all outages, including faults after the
    issue time) first fall to 10 percent of the peak known at the issue time (P-17-03)."""
    share = prm.f("etr", "restored_share")
    grid = run_grid(run, prm.f("process", "horizon_days"), prm.f("process", "step_s"))
    n_reg = len(run.world.region_ids)
    s = series(run_intervals(run, by="region"), list(range(n_reg)), grid)
    after = grid >= obs.as_of

    def first_below(curve: np.ndarray, peak: float) -> float:
        hit = np.flatnonzero(curve[after] <= (1.0 - share) * peak * (1.0 + 1e-9))
        return float((grid[after][hit[0]] - obs.as_of) / 3600.0) if len(hit) else math.nan

    reg = np.array([first_below(s[k], obs.peak_region[k]) for k in range(n_reg)])
    return reg, first_below(s.sum(axis=0), obs.peak_global)
