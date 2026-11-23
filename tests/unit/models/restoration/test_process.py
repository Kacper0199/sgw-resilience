from __future__ import annotations

import numpy as np

from sgw.models.restoration.curves import county_times, run_grid, run_intervals, series
from sgw.models.restoration.params import DutyClock, default_params
from sgw.models.restoration.process import SECONDARY, SECTION, ProcessRun, simulate


def test_every_job_is_done_once_and_never_before_it_is_released(story: ProcessRun) -> None:
    assert not np.isnan(story.end).any()
    assert np.all(story.start >= story.release - 1e-6)
    assert np.all(story.end > story.start)
    assert np.all(story.start >= story.arrive - 1e-6)


def test_work_is_done_only_on_duty_at_the_crew_group_rate(story: ProcessRun) -> None:
    clock = DutyClock.from_params(default_params())
    on_duty = (clock.hours(story.end) - clock.hours(story.start)) * story.lines
    assert np.allclose(on_duty, story.jobs.work, rtol=1e-6, atol=1e-6)


def test_secondary_jobs_wait_for_their_section_and_its_trunk(story: ProcessRun) -> None:
    w = story.world
    sec = story.jobs.kind == SECONDARY
    parent = story.jobs.section[sec]
    trunk = w.trunk_of[parent]
    parent_back = np.fmax(
        story.own_restore[parent], np.where(w.failed[trunk], story.own_restore[trunk], -np.inf)
    )
    assert np.all(story.start[sec] >= parent_back - 1e-6)
    assert np.all(story.secondary_out_end >= story.section_out[1][parent] - 1e-6)
    assert sec.sum() > (story.jobs.kind == SECTION).sum()


def test_customers_out_are_conserved_and_all_back_by_the_horizon(story: ProcessRun) -> None:
    prm = default_params()
    grid = run_grid(story, prm.f("process", "horizon_days"), prm.f("process", "step_s"))
    s = series(run_intervals(story), list(range(len(story.world.region_ids))), grid)
    assert s[:, 0].sum() == 0
    assert s[:, -1].sum() == 0
    assert s.min() >= 0
    assert s.sum(axis=0).max() <= story.world.customers.sum()


def test_the_process_is_deterministic(story: ProcessRun) -> None:
    again = simulate(story.world, default_params())
    assert np.array_equal(again.end, story.end)
    assert np.array_equal(again.jobs.customers, story.jobs.customers)


def test_story_counties_restore_with_a_long_tail(story: ProcessRun) -> None:
    c = county_times(story)
    t90 = np.array([v["t90_h"] for v in c.values()])
    t50 = np.array([v["t50_h"] for v in c.values()])
    assert len(c) > 100
    assert np.nanmedian(t90) / np.nanmedian(t50) > 2.2
