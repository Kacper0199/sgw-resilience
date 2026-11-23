from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sgw.demo import bookmarks, snapshots, story
from sgw.models.clocks.service import compute_queue
from sgw.models.clocks.zone_cases import case_spec
from sgw.rules import zones


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _clocks() -> dict[str, tuple[datetime, datetime]]:
    """Case id -> (known at, effective decide-by) of every zone rule case with its own clock."""
    out: dict[str, tuple[datetime, datetime]] = {}
    for hit in zones.timeline():
        if hit.clock is None:
            continue
        case = compute_queue([case_spec(hit, "SC-45003")], now=hit.known_at).cases[hit.case_id].case
        out[hit.case_id] = (hit.known_at, case.effective_decide_by_utc)
    return out


@pytest.mark.parametrize(
    ("case_id", "signed_at"),
    [
        (story.COPPERLEAF_CASE, story.COPPERLEAF_SIGNED),
        (story.DEERWATER_CASE, story.DEERWATER_SIGNED),
        (story.CEDARFALL_LIFT_CASE, story.CEDARFALL_LIFTED),
    ],
)
def test_the_water_team_signs_each_notice_before_its_deadline(case_id: str, signed_at: str) -> None:
    known, due = _clocks()[case_id]
    assert known <= _utc(signed_at) < due


def test_notices_lifted_opens_with_lifts_due_after_the_moment() -> None:
    clocks = _clocks()
    moment = _utc(bookmarks.NOTICES_LIFTED)
    waiting = story.LIFT_CASES - {story.CEDARFALL_LIFT_CASE}
    assert waiting == {"DC-D3-PS23-LAURELSPUR-BWA-LIFT", "DC-D3-PS38-COPPERLEAF-BWA-LIFT"}
    for case_id in waiting:
        known, due = clocks[case_id]
        assert known <= moment < due, case_id
    assert (min(clocks[c][1] for c in waiting) - moment).total_seconds() < 6 * 3600


def test_story_signing_times_follow_the_clock() -> None:
    order = [
        bookmarks.MORNING_AFTER,
        story.COPPERLEAF_SIGNED,
        bookmarks.ETR_TIME,
        story.DEERWATER_SIGNED,
        story.CEDARFALL_LIFTED,
        bookmarks.NOTICES_LIFTED,
    ]
    assert order == sorted(order)
    names = [name for name, _ in story.STEPS]
    assert names.index("night 2: Copperleaf notice signed on time") < names.index(
        "ETR published; copilot on revising it"
    )


def test_a_private_template_prefix_leaves_the_shared_templates_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    bm = bookmarks.bookmark("notices-lifted")
    assert bm.template == "sgw_demo_bm_notices_lifted"
    monkeypatch.setenv(bookmarks.TEMPLATE_PREFIX_ENV, "sgw_demo_pl_")
    assert bm.template == "sgw_demo_pl_notices_lifted"
    for bad in ("sgw_", "sgw_demo_pl", "postgres_", "sgw_demo_x;drop_"):
        monkeypatch.setenv(bookmarks.TEMPLATE_PREFIX_ENV, bad)
        with pytest.raises(ValueError):
            _ = bm.template
    with pytest.raises(snapshots.TargetRefused):
        snapshots.check_target("sgw_demo_pl_notices_lifted")
