"""Medium 3: the scenario menu's "90% of customers restored" is the time the outage feed got back to
the target share, the same definition the Restoration page reads (`etr_actuals`)."""

from __future__ import annotations

from datetime import UTC, datetime

from sgw.api.clock import scenario_def
from sgw.api.readmodels import etr_actuals
from sgw.api.scenario_info import scenario_moments


def test_the_restored_moment_is_the_outage_feed_time() -> None:
    restored = next(m for m in scenario_moments("helene") if m.kind == "restored")
    feed = etr_actuals.actuals(scenario_def("helene").window_end)[etr_actuals.GLOBAL].restored_utc
    assert feed == datetime(2024, 9, 30, 14, 0, tzinfo=UTC)
    assert restored.scenario_time == feed
    assert [m.scenario_time for m in scenario_moments("helene")] == sorted(
        m.scenario_time for m in scenario_moments("helene")
    )
