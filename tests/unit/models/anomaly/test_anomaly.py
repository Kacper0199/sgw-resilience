from __future__ import annotations

import numpy as np
import pytest

from sgw.generator.config import rng
from sgw.models.anomaly.detect import (
    Alarm,
    baseline_alarms,
    cusum_episodes,
    detect,
    exceedance,
    frozen_runs,
    replay_hits,
    sensor_model,
    suspect_mask,
)
from sgw.models.anomaly.report import anomaly_report
from sgw.models.anomaly.score import helene_truth
from sgw.models.anomaly.streams import from_fixture
from sgw.models.water.params import family
from sgw.models.water.telemetry import epoch
from sgw.models.water.twin import zone_twins


@pytest.fixture(scope="module")
def report() -> dict:
    return anomaly_report(bench_days=200)


@pytest.fixture(scope="module")
def helene() -> dict:
    fam = family()
    twins = zone_twins()
    out = {}
    for s in from_fixture():
        m = sensor_model(
            twins[s.station].pm,
            fam.f("water.pressure_noise_psi"),
            fam.f("water.level_noise_ft"),
            twins[s.station],
        )
        out[s.station] = (s, m, detect(s, m, fam.f("water.low_pressure_alarm_psi")))
    return out


def test_every_seeded_helene_water_fault_is_found_by_the_right_family(report: dict) -> None:
    block = report["results"]["helene_dev"]
    assert block["metrics"]["faults"] == 5
    assert all(f["detected"] for f in block["faults"])
    by = {f["kind"]: f["by"] for f in block["faults"]}
    assert by["pump_trip"] == "pump_trip"
    assert by["leak"] == "demand_increase"
    assert by["replay_pressure"] in {"pressure_level_inconsistent", "replayed_sequence"}
    assert by["stuck_level"] == "frozen_reading"
    assert by["drift_pressure"] == "pressure_level_inconsistent"
    assert block["false_alarms"] == []
    assert block["metrics"]["spoof_flagged"] == block["metrics"]["spoof_cases"] == 1


def test_spoof_guard_suppresses_the_fake_low_pressure_the_baseline_raises(helene: dict) -> None:
    s, m, alarms = helene["PS-23"]
    spoof = next(w for w in helene_truth()["PS-23"] if w.kind == "replay_pressure")
    inside = [a for a in alarms if a.kind == "pressure_loss" and spoof.start <= a.detected <= spoof.end]
    assert inside == []
    base = baseline_alarms(s, m, family().f("water.low_pressure_alarm_psi"))
    assert any(spoof.start <= a.detected <= spoof.end for a in base)
    assert any(a.family == "A8" and spoof.start <= a.detected <= spoof.start + 1800 for a in alarms)


def test_power_loss_pressure_drops_are_explained_not_accused(helene: dict) -> None:
    for st in ("PS-17", "PS-23"):
        _, _, alarms = helene[st]
        first = next(a for a in alarms if a.kind == "pressure_loss")
        assert first.detail["explanation"] == "power_loss"
        assert not any(a.family == "A8" and a.start < epoch("2024-09-29T00:00:00Z") for a in alarms)
    _, _, alarms = helene["PS-52"]
    assert next(a for a in alarms if a.kind == "pressure_loss").detail["explanation"] == "generator_failure"


def test_dev_bench_regression_guard_and_honest_acceptance(report: dict) -> None:
    block = report["results"]["dev_bench"]
    m = block["metrics"]
    assert 0.65 <= m["recall"] < 0.8
    assert block["acceptance"] == "not met on raw; WP-15 decides"
    assert "post-hoc" in report["post_hoc_subset"]
    assert m["fa_per_100_asset_days"] <= 1.0
    assert m["spoof_consequential_flagged"] == m["spoof_consequential"] > 0
    base = report["results"]["dev_bench"]["baseline_metrics"]
    assert base["recall"] < m["recall"]


def test_report_is_deterministic() -> None:
    a = anomaly_report(bench_days=40)
    b = anomaly_report(bench_days=40)
    assert a["results"]["dev_bench"]["metrics"] == b["results"]["dev_bench"]["metrics"]


def test_cusum_finds_a_shift_and_stays_quiet_on_noise() -> None:
    z = rng(5, "cusum").normal(size=20000)
    assert cusum_episodes(z, 0.5, 10.0) == []
    shifted = z.copy()
    shifted[5000:5100] += 2.0
    eps = cusum_episodes(shifted, 0.5, 10.0)
    assert len(eps) == 1 and 5000 <= eps[0][1] < 5020 and eps[0][3] == "up"
    bigger = z.copy()
    bigger[5000:5100] += 4.0
    assert cusum_episodes(bigger, 0.5, 10.0)[0][4] > eps[0][4] > 10.0


def test_alarm_score_is_the_share_of_the_peak_past_the_threshold() -> None:
    assert exceedance(20.0, 10.0) == 0.5 and exceedance(40.0, 10.0) == 0.75
    assert exceedance(10.0, 10.0) == 0.0 and exceedance(0.0, 10.0) == 0.0


def test_helene_alarms_carry_graded_scores(report: dict) -> None:
    rows = report["results"]["helene_dev"]["alarms"]
    assert all(0.0 < r["score"] <= 1.0 for r in rows)
    assert {r["score"] for r in rows if r["kind"] in ("pump_trip", "replayed_sequence")} == {1.0}
    graded = [r["score"] for r in rows if r["kind"] not in ("pump_trip", "replayed_sequence")]
    assert len(set(graded)) == len(graded) and max(graded) < 1.0


def test_frozen_runs_skip_the_range_end() -> None:
    x = np.array([1.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    assert frozen_runs(x, 6) == [(1, 6), (8, 14)]
    assert frozen_runs(x, 6, exclude_at_or_below=0.05) == [(1, 6)]


def test_replay_needs_an_exact_noisy_repeat_beyond_the_minimum_lag() -> None:
    r = rng(9, "replay")
    x = np.round(60 + r.normal(0, 0.3, 400), 1)
    t = np.arange(400) * 900.0
    assert not replay_hits(x, t, 8, 4 * 3600.0, 7 * 86400.0).any()
    y = x.copy()
    y[300:310] = x[204:214]
    hits = replay_hits(y, t, 8, 4 * 3600.0, 7 * 86400.0)
    assert hits[300:310].sum() >= 8 and not hits[:300].any()
    flat = np.full(50, 61.0)
    assert not replay_hits(flat, t[:50], 8, 4 * 3600.0, 7 * 86400.0).any()


def test_pairwise_inconsistency_does_not_mask_the_level_for_mass_balance() -> None:
    t = np.arange(10) * 1800.0
    pair = Alarm("X", "A8", "pressure_level_inconsistent", ("PT", "LT"), 0.0, 1e9, 0.0)
    own = Alarm("X", "A8", "frozen_reading", ("LT",), 0.0, 3600.0, 1800.0)
    assert suspect_mask(t, "LT", [pair]).all()
    assert not suspect_mask(t, "LT", [pair], own_only=True).any()
    assert suspect_mask(t, "LT", [pair, own], own_only=True).sum() == 2


def test_spoof_mask_is_causal() -> None:
    t = np.arange(10) * 1800.0
    late = Alarm("X", "A8", "replayed_sequence", ("PT",), 0.0, 9 * 1800.0, 4 * 1800.0)
    mask = suspect_mask(t, "PT", [late])
    assert not mask[:4].any() and mask[4:].all()
