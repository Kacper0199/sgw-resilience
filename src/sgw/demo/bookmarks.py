"""Demo bookmarks of the PS-17 story ("one pump station, one hospital, one clock"): named moments that
`sgw demo goto <id>` restores in seconds. Each bookmark is a template database built by `sgw demo build`
from one driven story run, so proposal ids, runs and the ledger agree across every bookmark.

Every bookmark is snapshotted just before its key run: the run the presenter starts there (`run_graph`,
`run_input`, after seeking to `run_at` where it differs from the bookmark clock). That run's K4 frames are
captured to `data/fixtures/eventlog/<id>.jsonl` (K19) and played back in DEMO_MODE on a database at that
bookmark when the LLM gateway cannot serve the run. The storm-night bookmarks (zone rules) have no key
run: their decisions are raised by rules on the clock and signed by people, not by an agent run."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

ADVISORY_N = "2024-09-26T09:05:00Z"
ADVISORY_N1 = "2024-09-26T15:05:00Z"
BEFORE_N = "2024-09-26T08:00:00Z"
MORNING_AFTER = "2024-09-27T12:00:00Z"
ETR_TIME = "2024-09-28T18:00:00Z"
NOTICES_LIFTED = "2024-09-30T12:00:00Z"
REVIEW_TIME = "2024-10-06T02:00:00Z"
TEMPLATE_PREFIX = "sgw_demo_bm_"
TEMPLATE_PREFIX_ENV = "SGW_DEMO_TEMPLATE_PREFIX"
PRIVATE_PREFIX = re.compile(r"^sgw_demo_[a-z0-9]+_$")
ETR_QUESTION = "When do I have to revise a global ETR that is already out?"


def template_prefix() -> str:
    """The shared `sgw_demo_bm_` templates, or a developer's own set
    (`SGW_DEMO_TEMPLATE_PREFIX=sgw_demo_<x>_`)
    so a branch build leaves the stack's templates alone."""
    chosen = os.environ.get(TEMPLATE_PREFIX_ENV, "").strip()
    if not chosen:
        return TEMPLATE_PREFIX
    if not PRIVATE_PREFIX.match(chosen):
        raise ValueError(f"{TEMPLATE_PREFIX_ENV} must look like sgw_demo_<letters or digits>_")
    return chosen


@dataclass(frozen=True)
class Bookmark:
    id: str
    title: str
    scenario_time: str
    state: str
    run_graph: str | None
    run_module: str | None
    run_at: str
    run_input: dict[str, Any] = field(default_factory=dict)

    @property
    def has_key_run(self) -> bool:
        return self.run_graph is not None

    @property
    def template(self) -> str:
        return template_prefix() + self.id.replace("-", "_")


BOOKMARKS: tuple[Bookmark, ...] = (
    Bookmark(
        "before-n",
        "Before advisory N",
        BEFORE_N,
        "Seeded world; the clock stands before advisory N; nothing proposed by an agent yet.",
        "water_continuity",
        "water",
        ADVISORY_N,
        {"advisory": "N"},
    ),
    Bookmark(
        "at-n",
        "Advisory N",
        ADVISORY_N,
        "Advisory N in force: PS-17 decide-by 27 Sep 04:45Z, wait; water continuity raised nothing.",
        "assess",
        "decisions",
        ADVISORY_N,
        {"advisory": "N"},
    ),
    Bookmark(
        "at-n1",
        "Advisory N+1, just after the reorder",
        ADVISORY_N1,
        "Advisory N+1: PS-17 moves to 03:29Z, decide now; the crew proposal signed at N is re-planned"
        " and its command signature voided.",
        "water_continuity",
        "water",
        ADVISORY_N1,
        {"advisory": "N+1"},
    ),
    Bookmark(
        "signed",
        "PS-17 priority and boil-water notice signed",
        ADVISORY_N1,
        "Command and water operations signed the PS-17 priority, water operations and compliance the"
        " boil-water notice; both executed.",
        "assess",
        "decisions",
        ADVISORY_N1,
        {"advisory": "N+1"},
    ),
    Bookmark(
        "morning-after",
        "Morning after landfall",
        MORNING_AFTER,
        "27 Sep 08:00 ET: Cedarfall and Laurelspur are below the pressure floor. SGW rules raised the"
        " hospital"
        " tanker (decide by 10:05 ET), the Laurelspur boil-water advisory, the D7 restoration order,"
        " the PS-17"
        " fuel truck and a patrol for a dark AMI section; nothing signed yet.",
        None,
        None,
        MORNING_AFTER,
    ),
    Bookmark(
        "etr-published",
        "ETR published",
        ETR_TIME,
        "The crew was staged by break-glass and co-signed; the global ETR was approved and published. Next:"
        " the copilot answers when a published ETR must be revised.",
        "copilot",
        "ask",
        ETR_TIME,
        {"question": ETR_QUESTION},
    ),
    Bookmark(
        "notices-lifted",
        "Boil-water notices lifted",
        NOTICES_LIFTED,
        "30 Sep 08:00 ET: the Cedarfall notice was lifted at 04:45 ET after two clean coliform sets; SGW"
        " rules propose lifting Laurelspur (due 10:30 ET) and Copperleaf (due 17:41 ET); the Deerwater"
        " notice, signed on time on 28 Sep, is still sampling.",
        None,
        None,
        NOTICES_LIFTED,
    ),
    Bookmark(
        "after-action",
        "After-action review",
        REVIEW_TIME,
        "The storm is over; the review time is set. Next: the after-action draft with clocks met and missed,"
        " the break-glass use and the SC 103-314 draft.",
        "after_action",
        "after_action",
        REVIEW_TIME,
        {},
    ),
)
BY_ID = {b.id: b for b in BOOKMARKS}


def bookmark(bookmark_id: str) -> Bookmark:
    try:
        return BY_ID[bookmark_id]
    except KeyError:
        raise KeyError(f"unknown bookmark {bookmark_id!r}; known: {', '.join(BY_ID)}") from None
