from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from sgw.models.surge.evaluate import (
    choose,
    match,
    paired_bootstrap,
    summarise,
)

T = pd.Timestamp("2022-06-10 12:00", tz="UTC")
H = timedelta(hours=1)


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fips": ["45019", "45019", "13051", "13051"],
            "begin": [T, T + 48 * H, T, T + 5 * H],
            "end": [T + 2 * H, T + 48 * H, T, T + 5 * H],
            "label": [True, True, True, False],
            "tier": ["tropical", "thunderstorm", "thunderstorm", "other"],
        }
    )


def _surges() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fips": ["45019", "13051", "13051", "45019"],
            "detected_at": [T - 2 * H, T + 6 * H, T + 30 * H, T + 100 * H],
        }
    )


def test_match_uses_the_window_around_the_event() -> None:
    events, surges = match(_events(), _surges())
    assert events["detected"].tolist() == [True, False, True]
    assert events["delay_h"].iloc[0] == -2.0
    assert events["delay_h"].iloc[2] == 6.0
    assert surges["explained"].tolist() == [True, True, False, False]


def test_summarise_counts_false_alarms_per_county_month() -> None:
    events, surges = match(_events(), _surges())
    m = summarise(events, surges, county_months=10.0)
    assert m["events"] == 3 and m["recall"] == pytest.approx(2 / 3)
    assert m["surges"] == 4 and m["precision"] == pytest.approx(0.5)
    assert m["false_alarms"] == 2 and m["false_alarms_per_county_month"] == pytest.approx(0.2)
    assert m["delay_h_median"] == pytest.approx(2.0)
    assert m["by_tier"]["tropical"] == {"events": 1, "recall": 1.0}


def test_choose_takes_the_best_recall_within_the_false_alarm_budget() -> None:
    rows = [
        {"params": "a", "recall": 0.9, "false_alarms_per_county_month": 0.5, "delay_h_median": 1.0},
        {"params": "b", "recall": 0.6, "false_alarms_per_county_month": 0.09, "delay_h_median": 3.0},
        {"params": "c", "recall": 0.6, "false_alarms_per_county_month": 0.05, "delay_h_median": 2.0},
        {"params": "d", "recall": 0.4, "false_alarms_per_county_month": 0.01, "delay_h_median": 0.0},
    ]
    assert choose(rows, budget=0.1)["params"] == "c"
    with pytest.raises(ValueError):
        choose(rows, budget=0.001)


def test_paired_bootstrap_resamples_event_days() -> None:
    days = pd.Series(pd.date_range("2022-06-01", periods=40, freq="D", tz="UTC").repeat(3))
    a = np.ones(len(days), dtype=bool)
    b = np.zeros(len(days), dtype=bool)
    diff, low, high = paired_bootstrap(a, b, days, reps=200, seed=1)
    assert diff == 1.0 and low == 1.0 and high == 1.0
    same, low, high = paired_bootstrap(a, a, days, reps=200, seed=1)
    assert same == 0.0 and low <= 0.0 <= high
