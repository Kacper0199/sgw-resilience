from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sgw.models.surge.detect import CusumParams
from sgw.models.surge.fit import params_dict
from sgw.models.surge.read import SurgeUnavailable, list_outage_surges
from sgw.models.surge.series import write_series

START = pd.Timestamp("2024-09-12", tz="UTC")
END = pd.Timestamp("2024-10-05", tz="UTC")
FIPS = ["45019", "45015", "13245"]
COEFS = {"features": ["a", "b"], "coef": [0.2, 1.0], "intercept": -1.0, "bands": {"high": 0.5, "medium": 0.2}}


def _artefact(directory: Path, end: pd.Timestamp = END) -> Path:
    times = pd.date_range(START, END, freq="15min", inclusive="left")
    gen = np.random.default_rng(4)
    x = np.column_stack([gen.poisson(60, len(times)) for _ in FIPS]).astype(float)
    landfall = times.get_loc(pd.Timestamp("2024-09-27 03:00", tz="UTC"))
    for j, lag in enumerate((0, 2, 40)):
        x[landfall + lag : landfall + lag + 400, j] += 9_000.0
    x[landfall - 300 : landfall - 296, :] = np.nan
    keep = times < end
    directory.mkdir(parents=True, exist_ok=True)
    write_series(directory / "helene_series.csv.gz", times[keep], x[keep], FIPS)
    meta = {
        "params": params_dict(CusumParams(min_customers=500, min_share=0.005, corroborate=1)),
        "confidence": COEFS,
        "counties": [
            {"fips": f, "name": n, "st": s, "mcc": 100_000}
            for f, n, s in zip(FIPS, ("Charleston", "Berkeley", "Richmond"), ("SC", "SC", "GA"), strict=True)
        ],
    }
    (directory / "params.json").write_text(json.dumps(meta), encoding="utf-8")
    return directory


@pytest.fixture(scope="module")
def full(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _artefact(tmp_path_factory.mktemp("full"))


def test_report_never_uses_data_after_as_of(full: Path, tmp_path: Path) -> None:
    for as_of in (datetime(2024, 9, 27, 3, 50, tzinfo=UTC), datetime(2024, 9, 27, 14, 7, tzinfo=UTC)):
        cut = _artefact(tmp_path / as_of.strftime("%H%M"), end=pd.Timestamp(as_of - timedelta(minutes=15)))
        a = list_outage_surges(as_of, directory=full)
        b = list_outage_surges(as_of, directory=cut)
        assert a.model_dump() == b.model_dump()
        assert a.data_through <= as_of - timedelta(minutes=15)
        assert all(s.detected_at <= a.data_through for s in a.surges)


def test_surges_appear_as_time_passes(full: Path) -> None:
    before = list_outage_surges(datetime(2024, 9, 27, 3, 0, tzinfo=UTC), directory=full)
    after = list_outage_surges(datetime(2024, 9, 27, 4, 0, tzinfo=UTC), directory=full)
    later = list_outage_surges(datetime(2024, 9, 29, 0, 0, tzinfo=UTC), directory=full)
    assert before.surges_total == 0 and before.first_detected_at is None
    assert after.counties_surging == 2 and {s.fips for s in after.surges} == {"45019", "45015"}
    assert later.surges_total == 3
    s = after.surges[0]
    assert s.surge_id.startswith("SRG-45019-240927T") and s.state == "SC" and s.county == "Charleston"
    assert s.status == "active" and s.peak_customers_out >= 9_000 and 0.0 < s.share_out <= 1.0
    assert s.onset_at <= s.detected_at


def test_filters_and_status(full: Path) -> None:
    at = datetime(2024, 10, 3, 0, 0, tzinfo=UTC)
    one = list_outage_surges(at, directory=full, fips=["13245"])
    assert one.counties_monitored == 1 and [s.fips for s in one.surges] == ["13245"]
    assert one.surges[0].status == "ended"
    assert list_outage_surges(at, directory=full, active_only=True).surges == []
    assert list_outage_surges(at, directory=full, limit=1).truncated


def test_rejects_naive_time_unknown_scenario_and_no_baseline(full: Path) -> None:
    with pytest.raises(ValueError):
        list_outage_surges(datetime(2024, 9, 27, 4, 0), directory=full)  # noqa: DTZ001
    with pytest.raises(SurgeUnavailable):
        list_outage_surges(datetime(2024, 9, 27, 4, 0, tzinfo=UTC), scenario="family_b", directory=full)
    with pytest.raises(SurgeUnavailable):
        list_outage_surges(datetime(2024, 9, 13, 0, 0, tzinfo=UTC), directory=full)
