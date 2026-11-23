"""Reference rows the D4 global ETR proposal needs (called by `sgw seed`): the service-territory asset the
publication targets and the decision case `DC-D4-ETR-GLOBAL` with a WP-12 clock (`build_clock`).

The D4 clock is a rule deadline under an SGW policy (assumed, synthetic): the global ETR issued at the story's
declared peak + 24 h (2024-09-28 17:30Z, WP-17 story of record) is to be published within four hours, so the
evening partner briefing carries it; publishing needs an hour (two approvals plus the customer channels).

A revision of a published ETR is its own decision (`DC-D4-ETR-REV-<scenario time>`), created when the planner
drafts it: its clock starts then, with the policy window `policy_etr_revise_publish_within_h`, never at the
first publication's deadline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from sgw.common.numbers import value as number
from sgw.contracts import golden
from sgw.contracts.clocks import ClockBasis, DecisionClock, build_clock
from sgw.contracts.vocab import ClockKind, DecisionStep, Domain

ETR_CASE = "DC-D4-ETR-GLOBAL"
TERRITORY = "SGW-ELECTRIC-TERRITORY"
ETR_ISSUE_UTC = datetime(2024, 9, 28, 17, 30, tzinfo=UTC)
PUBLISH_WITHIN = timedelta(hours=4)
PUBLISH_LEAD_MIN = 60
TITLE = "Publish the global estimated time of restoration (90 percent restored)"
REVISION_PREFIX = "DC-D4-ETR-REV-"
REVISION_TITLE = "Publish the revised global estimated time of restoration"
REVISE_WITHIN_KEY = "policy_etr_revise_publish_within_h"
_PUBLISH_RULE = ClockBasis(
    kind=ClockKind.RULE_DEADLINE,
    basis_id="policy.etr_publish_window",
    basis_version="0.1-assumed",
    citation="SGW policy (assumed): global ETR published within 4 h of issue",
)
_PUBLISH_LEAD = ClockBasis(
    kind=ClockKind.MODEL_ESTIMATE,
    basis_id="lead_time.etr_approve_and_publish",
    basis_version="0.1-assumed",
    citation=None,
)


def etr_clock(issue: datetime = ETR_ISSUE_UTC) -> DecisionClock:
    due = issue + PUBLISH_WITHIN
    return build_clock(
        consequence_p10_utc=due,
        consequence_utc=due,
        consequence_p90_utc=due,
        consequence_basis=_PUBLISH_RULE,
        action_lead_time_min=PUBLISH_LEAD_MIN,
        lead_time_basis=_PUBLISH_LEAD,
        if_late="The evening partner briefing and the customer channels go out without a global ETR.",
    )


def revise_within() -> timedelta:
    return timedelta(hours=float(number(REVISE_WITHIN_KEY)))


def revision_clock(found_at: datetime) -> DecisionClock:
    due = found_at + revise_within()
    hours = f"{revise_within().total_seconds() / 3600:g}"
    return build_clock(
        consequence_p10_utc=due,
        consequence_utc=due,
        consequence_p90_utc=due,
        consequence_basis=ClockBasis(
            kind=ClockKind.RULE_DEADLINE,
            basis_id="policy.etr_revise_publish_window",
            basis_version="0.1-assumed",
            citation=f"SGW policy (assumed): a revised global ETR published within {hours} h of the drift",
        ),
        action_lead_time_min=PUBLISH_LEAD_MIN,
        lead_time_basis=_PUBLISH_LEAD,
        if_late="Customers and partners keep planning on a global ETR that restoration has left behind.",
    )


def revision_case_id(found_at: datetime) -> str:
    return f"{REVISION_PREFIX}{found_at.astimezone(UTC):%Y%m%dT%H%M}Z"


def ensure_revision_case(conn: psycopg.Connection[Any], found_at: datetime) -> str:
    """The decision case of a revision drafted at `found_at` (scenario time), created once."""
    case_id = revision_case_id(found_at)
    _insert_case(conn, case_id, REVISION_TITLE, revision_clock(found_at))
    return case_id


def seed_etr_reference(conn: psycopg.Connection[Any], issue: datetime = ETR_ISSUE_UTC) -> None:
    conn.execute(
        "INSERT INTO asset (asset_id, domain, kind, region_id, name, customers_served, attributes)"
        " VALUES (%s, 'electric', 'service_territory', %s, %s, 0, %s) ON CONFLICT (asset_id) DO NOTHING",
        (
            TERRITORY,
            golden.REGION_AIKEN,
            "SGW electric service territory (synthetic)",
            Jsonb({"customers_source": "synthetic", "synthetic": True, "scope": "global_etr"}),
        ),
    )
    _insert_case(conn, ETR_CASE, TITLE, etr_clock(issue))


def _insert_case(conn: psycopg.Connection[Any], case_id: str, title: str, c: DecisionClock) -> None:
    conn.execute(
        "INSERT INTO decision_case (decision_case_id, step, title, region_id, domain, clock_kind,"
        " consequence_utc, consequence_p10_utc, consequence_p90_utc, consequence_basis,"
        " action_lead_time_min, lead_time_basis, decide_by_utc, decide_by_p10_utc, decide_by_p90_utc,"
        " effective_decide_by_utc, on_critical_path, next_advisory_utc, if_late) VALUES (%s, %s, %s, %s, %s,"
        " %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false, NULL, %s)"
        " ON CONFLICT (decision_case_id) DO NOTHING",
        (
            case_id,
            DecisionStep.D4.value,
            title,
            golden.REGION_AIKEN,
            Domain.ELECTRIC.value,
            c.clock_kind.value,
            c.consequence_utc,
            c.consequence_p10_utc,
            c.consequence_p90_utc,
            Jsonb(c.consequence_basis.model_dump(mode="json")),
            c.action_lead_time_min,
            Jsonb(c.lead_time_basis.model_dump(mode="json")),
            c.decide_by_utc,
            c.decide_by_p10_utc,
            c.decide_by_p90_utc,
            c.decide_by_utc,
            c.if_late,
        ),
    )
