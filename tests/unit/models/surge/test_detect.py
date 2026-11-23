from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sgw.models.surge.detect import (
    CusumParams,
    FixedShareParams,
    RollingZParams,
    Surge,
    detect,
    segment,
)

STEPS_PER_DAY = 96
MCC = np.array([20_000.0, 5_000.0])


def _times(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2021-06-01", periods=n, freq="15min", tz="UTC")


def _quiet(n: int, seed: int = 7) -> np.ndarray:
    gen = np.random.default_rng(seed)
    return np.column_stack([gen.poisson(40, n), gen.poisson(3, n)]).astype(float)


def _with_surge(x: np.ndarray, start: int, county: int, level: float, hours: int = 36) -> np.ndarray:
    y = x.copy()
    ramp = np.minimum(np.arange(hours * 4) / 8.0, 1.0)
    y[start : start + hours * 4, county] += level * ramp
    return y


def test_cusum_flags_a_sustained_rise_quickly() -> None:
    n = 14 * STEPS_PER_DAY
    start = 10 * STEPS_PER_DAY
    x = _with_surge(_quiet(n), start, county=0, level=800.0)
    surges = detect(x, MCC, _times(n), CusumParams())
    assert [s.county for s in surges] == [0]
    delay_steps = (surges[0].detected_at - _times(n)[start]).total_seconds() / 900
    assert 0 <= delay_steps <= 8
    assert surges[0].onset_at <= surges[0].detected_at
    assert surges[0].peak_customers_out >= 800


def test_cusum_stays_quiet_on_a_stationary_series() -> None:
    n = 30 * STEPS_PER_DAY
    assert detect(_quiet(n, seed=11), MCC, _times(n), CusumParams()) == []


def test_magnitude_gate_ignores_relative_noise_in_a_tiny_county() -> None:
    n = 14 * STEPS_PER_DAY
    x = _with_surge(_quiet(n), 10 * STEPS_PER_DAY, county=1, level=20.0)
    assert detect(x, MCC, _times(n), CusumParams()) == []


def test_detection_is_causal_prefix_stable() -> None:
    n = 16 * STEPS_PER_DAY
    x = _with_surge(_with_surge(_quiet(n), 9 * STEPS_PER_DAY, 0, 900.0), 12 * STEPS_PER_DAY, 1, 600.0)
    times = _times(n)
    full = detect(x, MCC, times, CusumParams())
    cut = 10 * STEPS_PER_DAY + 5
    prefix = detect(x[:cut], MCC, times[:cut], CusumParams())
    expected = [(s.county, s.detected_at, s.onset_at) for s in full if s.detected_at <= times[cut - 1]]
    assert [(s.county, s.detected_at, s.onset_at) for s in prefix] == expected
    assert all(s.status == "active" for s in prefix)


def test_feed_gap_holds_state_and_flags_the_next_surge() -> None:
    n = 14 * STEPS_PER_DAY
    start = 10 * STEPS_PER_DAY
    x = _with_surge(_quiet(n), start, county=0, level=800.0)
    x[start - 12 : start, :] = np.nan
    surges = detect(x, MCC, _times(n), CusumParams())
    assert len(surges) == 1
    assert "after_feed_gap" in surges[0].dq_flags


def test_exceeds_mcc_flag() -> None:
    n = 14 * STEPS_PER_DAY
    x = _with_surge(_quiet(n), 10 * STEPS_PER_DAY, county=1, level=6_000.0)
    surges = detect(x, MCC, _times(n), CusumParams())
    assert surges and "exceeds_mcc" in surges[0].dq_flags
    assert surges[0].share_out == 1.0


def test_fixed_share_baseline_uses_the_share_of_customers() -> None:
    n = 14 * STEPS_PER_DAY
    x = _with_surge(_quiet(n), 10 * STEPS_PER_DAY, county=0, level=100.0)
    assert detect(x, MCC, _times(n), FixedShareParams(share=0.01)) == []
    surges = detect(x, MCC, _times(n), FixedShareParams(share=0.005))
    assert [s.county for s in surges] == [0]


def test_rolling_z_baseline_flags_a_jump() -> None:
    n = 14 * STEPS_PER_DAY
    x = _with_surge(_quiet(n), 10 * STEPS_PER_DAY, county=0, level=800.0)
    surges = detect(x, MCC, _times(n), RollingZParams(z=4.0))
    assert [s.county for s in surges] == [0]


def test_segment_joins_alarms_until_customers_stay_down_for_end_h() -> None:
    n = 4 * STEPS_PER_DAY
    times = _times(n)
    start = np.zeros((n, 1), dtype=bool)
    x = np.full((n, 1), 10.0)
    for a, b in ((100, 110), (120, 130), (300, 310)):
        start[a:b, 0] = True
        x[a:b, 0] = 500.0
    surges = segment(
        start,
        x,
        np.full((n, 1), 10.0),
        np.array([1000.0]),
        times,
        onset=np.arange(n)[:, None],
        gap=np.zeros(n, dtype=bool),
        end_h=6.0,
        gate_customers=np.array([100.0]),
    )
    assert [s.detected_at for s in surges] == [times[100], times[300]]
    assert surges[0].status == "ended" and surges[0].ended_at == times[130 + 23]
    assert all(isinstance(s, Surge) for s in surges)


def test_corroboration_needs_a_neighbouring_start() -> None:
    n = 14 * STEPS_PER_DAY
    start = 10 * STEPS_PER_DAY
    mcc = np.array([20_000.0, 20_000.0])
    quiet = np.column_stack([_quiet(n, seed=3)[:, 0], _quiet(n, seed=5)[:, 0]])
    alone = _with_surge(quiet, start, county=0, level=800.0)
    params = CusumParams(corroborate=1)
    assert detect(alone, mcc, _times(n), params) == []
    both = _with_surge(alone, start + 4, county=1, level=800.0)
    surges = detect(both, mcc, _times(n), params)
    assert [s.county for s in surges] == [1, 0] or [s.county for s in surges] == [0, 1]
    assert max(s.detected_at for s in surges) <= _times(n)[start + 12]


def test_params_validate() -> None:
    with pytest.raises(ValueError):
        CusumParams(h=-1.0)
