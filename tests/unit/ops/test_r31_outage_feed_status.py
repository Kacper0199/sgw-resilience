"""Medium 5: in a replay, "Outage reports" is on time as soon as the outage curve the Briefing reads
has customers out, also before the first outage event of the story reaches the ledger."""

from __future__ import annotations

from datetime import UTC, datetime

from sgw.contracts.vocab import FeedMode
from sgw.ops import freshness

AT_N1 = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)


def test_the_outage_curve_hour_is_the_last_whole_hour_with_customers_out() -> None:
    assert freshness.outage_curve_hour(AT_N1) == datetime(2024, 9, 26, 15, 0, tzinfo=UTC)
    assert freshness.outage_curve_hour(datetime(2024, 9, 23, 12, 0, tzinfo=UTC)) is None


def test_outage_reports_read_the_curve_when_the_ledger_has_nothing_yet() -> None:
    feed = freshness.with_outage_curve("oms", FeedMode.SYNTHETIC, None, None, AT_N1)
    item = freshness.feed_health(feed, AT_N1, "Outage reports")
    assert item.status == "on_time" and item.product_age_s == 300 and item.ingest_lag_s == 0


def test_a_later_ledger_event_wins_and_other_feeds_are_untouched() -> None:
    later = datetime(2024, 9, 27, 1, 16, tzinfo=UTC)
    at = datetime(2024, 9, 27, 1, 30, tzinfo=UTC)
    known = datetime(2024, 9, 27, 1, 18, tzinfo=UTC)
    feed = freshness.with_outage_curve("oms", FeedMode.SYNTHETIC, later, known, at)
    assert (feed.last_event_time, feed.last_known_at) == (later, known)
    quiet = freshness.with_outage_curve("ami-headend", FeedMode.SYNTHETIC, None, None, AT_N1)
    assert quiet.last_event_time is None
