"""Medium 2: a surge belongs to the replay only when it began inside the scenario window, so the
Briefing's "surges began at ..." never names a day before the replay starts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sgw.models.surge.read import list_outage_surges, scenario_data


@pytest.mark.parametrize(
    "at",
    [
        datetime(2024, 9, 26, 15, 5, tzinfo=UTC),
        datetime(2024, 9, 27, 12, 0, tzinfo=UTC),
        datetime(2024, 9, 30, 12, 0, tzinfo=UTC),
    ],
)
def test_every_surge_began_inside_the_scenario_window(at: datetime) -> None:
    start = scenario_data("helene").window_start
    report = list_outage_surges(at, active_only=True)
    assert report.surges, "the story has surges at each demo moment"
    assert min(s.onset_at for s in report.surges) >= start
    assert report.counties_surging == len({s.fips for s in report.surges if s.status == "active"})
