"""One status per feed: a feed with nothing delivered by the scenario time is "no data yet",
never "on time", so the key number "on time" counts only feeds that delivered within their limit."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sgw.contracts.vocab import FeedMode
from sgw.ops.freshness import FeedAtClock, feed_health
from sgw.pipeline.dq import freshness_check

AT = datetime(2024, 9, 26, 15, 5, tzinfo=UTC)


def _feed(source_id: str, event: datetime | None) -> FeedAtClock:
    known = None if event is None else event + timedelta(seconds=30)
    check = freshness_check(source_id, event, AT, last_known_at=known)
    return FeedAtClock(source_id, FeedMode.SYNTHETIC, event, known, check)


def test_no_data_is_its_own_status() -> None:
    item = feed_health(_feed("nhc-advisory-synthetic", None), AT, "Hurricane advisories")
    assert item.ingest_lag_s is None and item.product_age_s is None
    assert item.status == "no_data"


def test_a_quiet_feed_that_reports_on_change_is_neither_late_nor_missing() -> None:
    for source_id in ("ami-headend", "eam", "scada-electric", "oms"):
        item = feed_health(_feed(source_id, None), AT, source_id)
        assert (item.status, item.stale, item.measured_by) == ("quiet", False, "delay"), source_id


def test_delivered_feeds_are_on_time_or_late_as_stale_says() -> None:
    fresh = feed_health(_feed("scada-water", AT - timedelta(minutes=5)), AT, "Water system sensors")
    assert (fresh.status, fresh.stale) == ("on_time", False)
    old = feed_health(_feed("nhc-advisory-synthetic", AT - timedelta(days=2)), AT, "Hurricane advisories")
    assert old.stale and old.status == "late"
