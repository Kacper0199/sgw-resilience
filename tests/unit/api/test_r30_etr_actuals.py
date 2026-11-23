from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sgw.api.readmodels import etr
from sgw.api.readmodels import etr_actuals as ea
from sgw.models.restoration.publish import EtrEstimate

ISSUED = datetime(2024, 9, 28, 17, 30, tzinfo=UTC)
P10 = datetime(2024, 10, 1, 6, 0, tzinfo=UTC)
P50 = datetime(2024, 10, 2, 0, 54, tzinfo=UTC)
P90 = datetime(2024, 10, 2, 4, 54, tzinfo=UTC)
SHARE_AT_ISSUE = 829_605 / 1_603_753


def at(day: int, hour: int) -> datetime:
    return datetime(2024, 9 if day > 9 else 10, day, hour, tzinfo=UTC)


def test_actuals_come_from_the_outage_feed_at_the_scenario_clock() -> None:
    found = ea.actuals(at(30, 12))
    whole = found[ea.GLOBAL]
    assert (whole.out_now, whole.peak, whole.restored_utc) == (168_598, 1_604_454, None)
    assert found[ea.GLOBAL].as_of == at(30, 12)
    assert ea.actuals(at(30, 15))[ea.GLOBAL].restored_utc == at(30, 14)
    charleston = found["OPA-CHS-ASHLEYFERRY"]
    assert charleston.restored_utc == at(28, 22)
    assert set(ea.county_areas().values()) <= {a for a in found if a != ea.GLOBAL}
    assert len({a for a in found if a != ea.GLOBAL}) == 11


def test_nothing_after_the_scenario_clock_is_used() -> None:
    early = ea.actuals(at(28, 12))["OPA-CHS-ASHLEYFERRY"]
    assert early.restored_utc is None and early.as_of == at(28, 12)


@pytest.mark.parametrize(
    ("restored", "now", "expected"),
    [
        (None, at(30, 12), "waiting"),
        (None, P50 + timedelta(hours=1), "past_p50"),
        (None, P90 + timedelta(hours=1), "late"),
        (at(29, 0), at(30, 12), "restored_early"),
        (P50, P90, "restored"),
        (P90 + timedelta(hours=2), P90 + timedelta(hours=3), "restored_late"),
    ],
)
def test_outcome_against_the_published_range(restored: datetime | None, now: datetime, expected: str) -> None:
    actual = ea.AreaActual(now, 100, 1000, restored)
    assert ea.outcome(P10, P50, P90, actual, now) == expected


def test_a_published_etr_is_due_for_revision_once_restoration_is_more_than_12_h_ahead() -> None:
    whole = ea.actuals(at(30, 12))[ea.GLOBAL]
    ahead = ea.ahead_hours(ISSUED, SHARE_AT_ISSUE, P50, whole, at(30, 12))
    assert 30 < ahead < 40
    reason = ea.revision_reason(ahead, P50, whole, at(30, 12))
    assert reason.startswith(
        "Restoration runs 36 h ahead of the published estimate: 11% of the peak is still out"
    )
    assert reason.endswith("Revise when the likely time moves by more than 12 h.")
    just_out = ea.actuals(at(28, 18))[ea.GLOBAL]
    assert abs(ea.ahead_hours(ISSUED, SHARE_AT_ISSUE, P50, just_out, at(28, 18))) < ea.margin_h()


def test_once_restored_the_gap_is_measured_from_the_restored_time() -> None:
    whole = ea.actuals(at(1, 0))[ea.GLOBAL]
    ahead = ea.ahead_hours(ISSUED, SHARE_AT_ISSUE, P50, whole, at(1, 0))
    assert ahead == pytest.approx((P50 - at(30, 14)).total_seconds() / 3600)
    assert "was back to 90% restored at Sep 30, 10:00 ET" in ea.revision_reason(ahead, P50, whole, at(1, 0))


def _stored_global() -> EtrEstimate:
    times = {
        "p10_utc": P10,
        "p25_utc": P50 - timedelta(hours=2),
        "p50_utc": P50,
        "p75_utc": P50 + timedelta(hours=2),
        "p90_utc": P90,
    }
    return EtrEstimate(
        estimate_id="ETR-HELENE-GLOBAL-20240928T1730Z",
        scope="global",
        region_id="GLOBAL",
        as_of_utc=ISSUED,
        target="90 percent of the peak customers out restored",
        peak_customers_out=1_603_753,
        customers_out_now=829_605,
        hours_from_as_of={},
        model_version="sgw-etr-a6@1.0.0",
        calibrated=True,
        label="S",
        replay_overlay_allowed=False,
        basis="WP-17",
        **times,
    )


def test_a_revision_publishes_the_revised_estimate_and_ends_the_revise_loop() -> None:
    now = at(30, 12)
    whole = ea.actuals(now)[ea.GLOBAL]
    stored = _stored_global()
    revised = etr._rebased(stored, P50, whole, now)
    ahead = ea.ahead_hours(ISSUED, SHARE_AT_ISSUE, P50, whole, now)
    assert revised.p50_utc == ea.revised_p50(ahead, P50, whole)
    assert revised.estimate_id == "ETR-HELENE-GLOBAL-20240930T1200Z"
    assert revised.as_of_utc == now and revised.customers_out_now == 168_598
    assert min(revised.p10_utc, revised.p25_utc) >= now
    shown = etr.area(revised, {})
    share = shown.customers_out_now / shown.peak_customers_out
    after = ea.ahead_hours(revised.as_of_utc, share, revised.p50_utc, whole, now)
    assert abs(after) < ea.margin_h()
    assert ea.revision_reason(after, revised.p50_utc, whole, now).startswith(
        "Restoration runs on pace with the published estimate"
    )
