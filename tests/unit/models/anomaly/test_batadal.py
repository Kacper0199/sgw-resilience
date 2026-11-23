from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sgw.models.anomaly.batadal import (
    calibrate_h,
    cusum_flags,
    fit,
    limit_flags,
    load,
    residual_z,
    score,
)


def _sensors(n: int, seed: int) -> pd.DataFrame:
    gen = np.random.default_rng(seed)
    base = np.sin(np.arange(n) * 2 * np.pi / 24)
    return pd.DataFrame(
        {
            "L_T1": 3 + base + gen.normal(0, 0.05, n),
            "F_PU1": 90 + 10 * base + gen.normal(0, 0.5, n),
            "P_J280": 30 - 2 * base + gen.normal(0, 0.1, n),
        }
    )


def test_residual_cusum_flags_a_broken_physical_relation() -> None:
    train, test = _sensors(2000, 1), _sensors(600, 2)
    test.loc[300:360, "P_J280"] += 1.0
    model = fit(train)
    flags = cusum_flags(residual_z(model, test), h=calibrate_h(residual_z(model, train)))
    assert flags[300:362].any()
    assert flags[:290].mean() < 0.02
    assert not limit_flags(train, test)[300:360].all()


def test_score_counts_hours_attacks_and_time_to_detection() -> None:
    labels = np.zeros(100, dtype=bool)
    labels[10:20] = True
    labels[50:60] = True
    flags = np.zeros(100, dtype=bool)
    flags[15:20] = True
    flags[80] = True
    s = score(flags, labels)
    assert s["attacks"] == 2 and s["attacks_detected"] == 1
    assert s["tpr"] == pytest.approx(0.25) and s["tnr_lower_bound"] == pytest.approx(79 / 80)
    assert s["ttd_share_of_window"] == [0.5, 1.0]
    assert s["s"] == pytest.approx((0.25 + (0.25 + 79 / 80) / 2) / 2)


def test_load_reads_the_batadal_layout(tmp_path: Path) -> None:
    path = tmp_path / "d.csv"
    path.write_text(
        "DATETIME, L_T1, S_PU1, P_J280, ATT_FLAG\n"
        "04/07/16 00, 2.44, 1.00, 36.38, -999\n"
        "04/07/16 01, 2.66, 1.00, 38.60, 1\n",
        encoding="utf-8",
    )
    times, x, labels = load(path)
    assert list(x.columns) == ["L_T1", "P_J280"]
    assert times[1] == pd.Timestamp("2016-07-04 01:00")
    assert labels.tolist() == [False, True]
