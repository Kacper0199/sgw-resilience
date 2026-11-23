from __future__ import annotations

from dataclasses import replace

import numpy as np

from sgw.models.restoration.etr import EtrModel, declared_peak_time, forecast, issue_time, observe, truth_etr
from sgw.models.restoration.params import default_params
from sgw.models.restoration.process import SECONDARY, ProcessRun

MEMBERS = 16


def _issue(run: ProcessRun, hours_after_peak: float) -> float:
    return issue_time(run, default_params(), hours_after_peak)


def _hide_truth(run: ProcessRun, t0: float) -> ProcessRun:
    """Change everything an EOC cannot see at t0: unassessed damage, future work, hidden secondary jobs."""
    w = run.world
    unassessed = w.failed & (w.work_ok > t0)
    ds = np.where(unassessed, 5 - np.maximum(w.ds, 1), w.ds)
    not_started = np.isnan(run.start) | (run.start > t0)
    hidden = (run.jobs.kind == SECONDARY) & (run.release > t0)
    jobs = replace(
        run.jobs,
        work=np.where(not_started, run.jobs.work * 3.0, run.jobs.work),
        customers=np.where(hidden, run.jobs.customers + 7.0, run.jobs.customers),
    )
    end = np.where(run.end > t0, run.end + 86400.0, run.end)
    return replace(run, world=replace(w, ds=ds, hazus_h=w.hazus_h * 2.0), jobs=jobs, end=end)


def test_forecast_never_reads_what_the_eoc_cannot_see(small_model: EtrModel, test_storm: ProcessRun) -> None:
    prm = default_params()
    t0 = _issue(test_storm, 0.0)
    a = forecast(small_model, observe(test_storm, t0, prm, 7), prm, members=MEMBERS, seed=7)
    hidden = _hide_truth(test_storm, t0)
    b = forecast(small_model, observe(hidden, t0, prm, 7), prm, members=MEMBERS, seed=7)
    assert np.array_equal(a.global_h, b.global_h)
    assert np.array_equal(a.samples_h, b.samples_h, equal_nan=True)


def test_forecast_quantiles_are_ordered_and_narrow_as_the_storm_is_worked(
    small_model: EtrModel, test_storm: ProcessRun
) -> None:
    prm = default_params()
    widths = []
    for off in (0.0, 24.0):
        obs = observe(test_storm, _issue(test_storm, off), prm, 7)
        fc = forecast(small_model, obs, prm, members=MEMBERS, seed=7)
        reg, glob = fc.quantiles()
        assert np.all(np.diff(glob) >= 0)
        assert np.all(np.diff(reg[fc.eligible], axis=1) >= 0)
        assert np.all(fc.samples_h[fc.eligible] > 0)
        y_reg, y_glob = truth_etr(test_storm, obs, prm)
        assert y_glob > 0 and np.all(y_reg[fc.eligible] >= 0)
        ok = fc.eligible
        widths.append(float(np.median((reg[ok, 4] - reg[ok, 0]) / reg[ok, 2])))
    assert widths[1] < widths[0]


def test_fitted_components_are_physically_ordered(small_model: EtrModel) -> None:
    mu = small_model.aft.mu
    assert np.all(np.diff(mu[:4]) > 0)
    assert small_model.aft.county_sigma > 0
    assert np.allclose(small_model.ds_probs.sum(axis=1), 1.0)
    assert np.all(np.diff(small_model.ds_probs[:, 3]) >= -0.05)
    assert small_model.p_blocked.min() > 0 and small_model.p_blocked.max() < 1


def test_declared_peak_is_live_and_after_the_true_peak(test_storm: ProcessRun) -> None:
    prm = default_params()
    end = test_storm.world.start_t + prm.f("process", "horizon_days") * 86400.0 - 1.0
    true_peak = observe(test_storm, end, prm, 1).peak_time_global
    declared = declared_peak_time(test_storm, prm)
    hold = prm.f("etr", "peak_hold_h") * 3600.0
    assert true_peak + hold <= declared <= true_peak + hold + 6 * 3600.0
    seen = observe(test_storm, declared, prm, 1)
    assert seen.peak_time_global == true_peak
