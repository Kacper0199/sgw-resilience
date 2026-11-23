from __future__ import annotations

from datetime import UTC, datetime

from sgw.models.outage.read import observed


def test_forecast_vs_actual_reads_the_outage_feed_up_to_the_scenario_clock() -> None:
    before, none = observed(datetime(2024, 9, 20, 0, tzinfo=UTC))
    assert before is None and none == {}
    later, peaks = observed(datetime(2024, 9, 30, 12, 0, tzinfo=UTC))
    assert later is not None
    assert (later.customers_out_now, later.peak_customers_out) == (168_598, 1_604_454)
    assert later.peak_at_utc == datetime(2024, 9, 27, 12, 0, tzinfo=UTC)
    assert sum(peaks.values()) >= later.peak_customers_out
    early, early_peaks = observed(datetime(2024, 9, 26, 15, 5, tzinfo=UTC))
    assert early is None or early.peak_customers_out < later.peak_customers_out
    assert all(early_peaks.get(f, 0) <= p for f, p in peaks.items())
