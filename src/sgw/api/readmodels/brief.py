"""Executive Brief read model: everything as known at the scenario time, rendered by code.

Four numbers, each with Actual and (where a model exists) Forecast:
- customers out: actual from the replayed county curve (`sgw.reports.sources.replay_status`, the sitrep's own
  source); forecast = the sum of county P50 peaks of the latest WP-11 publication in K1 `forecast`
  (`county_peak_customers_out`) issued by then, else none;
- critical facilities affected: distinct `critical_facility_ids` on OMS outages open at the scenario time
  (latest event per outage known by then, `oms.jsonl`); no forecast;
- water zones under advisory: actual = register rows `issued`; forecast = zones whose latest assessment is at
  or above the policy line or whose advisory is due/proposed/issued (`sgw.api.readmodels.water.register`);
  only the counts leave the C2 register;
- crews working: the latest FSM status per crew known by then (`fsm.jsonl`): enroute + onsite, with every
  status in the breakdown; no forecast.

Status word (P-BEUI3-02): the worst queue severity of an open T3 decision (critical Emergency, severe Warning,
elevated Watch); otherwise Restoring while customers are out and the 6 h trend is falling, Watch while
customers are out or an advisory is in force before landfall, else Normal."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from sgw.common.sources import display_name
from sgw.contracts.api_models import (
    BriefAdvisory,
    BriefFunctionLine,
    BriefNumber,
    ExecutiveBrief,
    ProposalSummary,
    Provenance,
)
from sgw.contracts.vocab import ApprovalFunction, CrewStatus, NumberLabel, ProposalState, Tier, UiSeverity
from sgw.reports.sources import REPO_ROOT, ReplayStatus, replay_status

FIXTURES = REPO_ROOT / "data" / "fixtures"
FORECAST_TARGET = "county_peak_customers_out"
P50_KEY = "0500"
OPEN_STATES = (ProposalState.PROPOSED, ProposalState.IN_REVIEW, ProposalState.ESCALATED)
WORKING = (CrewStatus.ENROUTE, CrewStatus.ONSITE)
SEVERITY_WORD = {UiSeverity.CRITICAL: "Emergency", UiSeverity.SEVERE: "Warning", UiSeverity.ELEVATED: "Watch"}
SEVERITY_ORDER = (UiSeverity.CRITICAL, UiSeverity.SEVERE, UiSeverity.ELEVATED)
CAVEAT = (
    "Synthetic Helene replay on the SGW network. Forecast numbers are model medians and can be wrong: the"
    " outage forecast is the fitted wind-fragility curve (machine-learning models were tested and did worse),"
    " and it under-calls large storms. Actual numbers are what the systems reported by this time."
)


@dataclass(frozen=True)
class FixtureEvent:
    type: str
    known_at: datetime
    issued_at: datetime | None
    payload: dict[str, Any]


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


@lru_cache(maxsize=16)
def _events(path: Path) -> tuple[FixtureEvent, ...]:
    if not path.is_file():
        return ()
    out: list[FixtureEvent] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if "type" not in row:
                continue
            issued = _utc(row["issued_at"]) if row.get("issued_at") else None
            out.append(FixtureEvent(row["type"], _utc(row["scenario_known_at"]), issued, row["payload"]))
    return tuple(out)


def all_events(path: Path, kind: str) -> list[FixtureEvent]:
    return [e for e in _events(path) if e.type == kind]


def known(path: Path, kind: str, at: datetime) -> list[FixtureEvent]:
    return [e for e in _events(path) if e.type == kind and e.known_at <= at]


def _latest(events: Iterable[FixtureEvent], key: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for e in events:
        out[str(e.payload[key])] = e.payload
    return out


def critical_facilities(at: datetime, scenario: str) -> list[str]:
    latest = _latest(known(FIXTURES / scenario / "oms.jsonl", "OutageEvent", at), "outage_id")
    return sorted(
        {f for p in latest.values() if p["status"] != "restored" for f in p["critical_facility_ids"]}
    )


def crews(at: datetime, scenario: str, conn: psycopg.Connection[Any] | None = None) -> Counter[str]:
    """Crew statuses as the Crews page reads them (the event store, dispatch moves included; an available crew
    with an open assignment is not available); the fixture only when the store holds no crew status yet."""
    if conn is not None:
        from sgw.dispatch.read import ACTIVE_STATES
        from sgw.models.restoration.field import _CREWS, MAX_ROWS, PUBLIC_CLASSES

        rows = conn.execute(_CREWS, {"at": at, "classes": list(PUBLIC_CLASSES), "limit": MAX_ROWS}).fetchall()
        if rows:
            held = {
                str(r[0])
                for r in conn.execute(
                    "SELECT crew_id FROM crew_assignment WHERE state = ANY(%s) AND proposed_at <= %s",
                    (list(ACTIVE_STATES), at),
                ).fetchall()
            }
            return Counter(
                "assigned" if str(r[1]) == CrewStatus.AVAILABLE.value and str(r[0]) in held else str(r[1])
                for r in rows
            )
    latest = _latest(known(FIXTURES / scenario / "fsm.jsonl", "CrewStatus", at), "crew_id")
    return Counter(str(p["status"]) for p in latest.values())


def last_advisory(at: datetime, scenario: str) -> BriefAdvisory | None:
    issued = known(FIXTURES / scenario / "weather.jsonl", "WeatherForecastIssued", at)
    if not issued:
        return None
    last = issued[-1]
    p = last.payload
    return BriefAdvisory(
        label=str(p["advisory_label"]),
        issued_utc=last.issued_at or last.known_at,
        landfall_eta_utc=_utc(p["landfall_eta_utc"]) if p.get("landfall_eta_utc") else None,
        next_advisory_utc=_utc(p["next_advisory_utc"]) if p.get("next_advisory_utc") else None,
    )


@dataclass(frozen=True)
class OutageForecast:
    p50_sum: int
    issued_at: datetime
    model_version: str


def forecast_customers_out(conn: psycopg.Connection[Any], at: datetime) -> OutageForecast | None:
    """The latest publication known by `at` (issued and known by then), one model version only."""
    row = conn.execute(
        "SELECT issued_at, model_version FROM forecast"
        " WHERE target = %s AND issued_at <= %s AND known_at <= %s"
        " ORDER BY issued_at DESC, known_at DESC, model_version DESC LIMIT 1",
        (FORECAST_TARGET, at, at),
    ).fetchone()
    if row is None:
        return None
    issued, version = row[0], str(row[1])
    total = conn.execute(
        "SELECT coalesce(sum((quantiles->>%s)::bigint), 0) FROM forecast"
        " WHERE target = %s AND issued_at = %s AND model_version = %s AND known_at <= %s",
        (P50_KEY, FORECAST_TARGET, issued, version, at),
    ).fetchone()
    return OutageForecast(int(total[0]) if total else 0, issued, version)


_BWA_PROPOSALS = """
SELECT DISTINCT ON (z.zone_id) z.zone_id, p.proposal_id, p.decision_case_id, p.state::text AS state
FROM proposal p CROSS JOIN LATERAL unnest(p.targets) AS z(zone_id)
WHERE p.action_type = %s AND z.zone_id = ANY(%s)
  AND EXISTS (SELECT 1 FROM audit_event a WHERE a.kind = 'proposal_created' AND a.subject = p.proposal_id
              AND a.occurred_at <= %s)
ORDER BY z.zone_id, p.created_at DESC, p.proposal_id DESC
"""


def bwa_proposals(
    conn: psycopg.Connection[Any], zone_ids: list[str], at: datetime, action: str = "boil_water_notice"
) -> dict[str, Any]:
    """The latest notice (or lift) proposal per zone among those proposed by `at` (scenario clock)."""
    from sgw.api.readmodels import water

    found: dict[str, water.BwaProposal | None] = dict.fromkeys(zone_ids)
    for zone_id, pid, case, state in conn.execute(_BWA_PROPOSALS, (action, zone_ids, at)).fetchall():
        found[str(zone_id)] = water.BwaProposal(str(pid), str(case), ProposalState(state))
    return found


def water_counts(conn: psycopg.Connection[Any], at: datetime) -> tuple[int, int, datetime | None]:
    """(zones under a notice now, zones expected under advisory, as-of of the latest assessment), read from
    the register the Water page shows: a signed notice counts as issued until its lift is signed."""
    from sgw.api.readmodels import water

    zones = water.zone_ids()
    register = water.register(
        at, bwa_proposals(conn, zones, at), bwa_proposals(conn, zones, at, water.LIFT_ACTION)
    )
    issued = {a.zone_id for a in register.advisories if a.status == "issued"}
    expected = {
        a.zone_id
        for a in register.advisories
        if a.status in ("due", "proposed", "issued")
        or (a.assessments and a.assessments[-1].at_or_above_policy)
    }
    latest = max((a.provenance.as_of for a in register.advisories if a.provenance.as_of), default=None)
    return len(issued), len(expected), latest


def status_word(
    open_t3: Sequence[ProposalSummary],
    status: ReplayStatus | None,
    advisory: BriefAdvisory | None,
    at: datetime,
) -> tuple[str, str]:
    """The headline level: the most urgent open two-team decision, raised to Warning while a major outage is
    on (R34 V1-20: the level fell to Watch as 1.6 million customers were out)."""
    word, lead = _decision_status_word(open_t3, status, advisory, at)
    if (
        status is not None
        and status.customers_out_now >= MAJOR_OUTAGE_CUSTOMERS
        and WORD_RANK.get(word, 0) < WORD_RANK["Warning"]
    ):
        return "Warning", f"{status.customers_out_now:,} customers are out"
    return word, lead


MAJOR_OUTAGE_CUSTOMERS = 100_000
WORD_RANK = {"Normal": 0, "Restoring": 1, "Watch": 1, "Warning": 2, "Emergency": 3}


def _decision_status_word(
    open_t3: Sequence[ProposalSummary],
    status: ReplayStatus | None,
    advisory: BriefAdvisory | None,
    at: datetime,
) -> tuple[str, str]:
    for level in SEVERITY_ORDER:
        hit = [p for p in open_t3 if p.severity is level]
        if hit:
            return SEVERITY_WORD[level], lead_sentence(open_t3, hit[0])
    if status is not None and status.customers_out_now > 0:
        if status.trend == "falling":
            return "Restoring", "customers are out and the 6-hour trend is falling"
        return "Watch", f"customers are out and the 6-hour trend is {status.trend}"
    if advisory is not None and advisory.landfall_eta_utc is not None and advisory.landfall_eta_utc > at:
        return "Watch", f"advisory {advisory.label} is in force before landfall"
    return "Normal", "no open T3 decision, no customers out, no advisory before landfall"


ET = ZoneInfo("America/New_York")
NUMBER_WORDS = ("No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten")


def _count(n: int) -> str:
    return NUMBER_WORDS[n] if 0 <= n < len(NUMBER_WORDS) else str(n)


def lead_sentence(open_t3: Sequence[ProposalSummary], lead: ProposalSummary) -> str:
    """The plain lead of the Brief: how many decisions wait for sign-off and which comes first, by title
    only; no ids, tiers or severity words in the sentence."""
    teams = _count(len(lead.functions_required)).lower()
    title = lead.title.rstrip(".")
    if len(open_t3) == 1:
        return f"One decision needs {teams} teams to sign: {title}."
    return f"{_count(len(open_t3))} decisions need {teams} teams to sign; the most urgent: {title}."


def _clock(t: datetime) -> str:
    """ET first, UTC second, as everywhere in the app: "26 Sep 19:45 ET (23:45Z)"."""
    return f"{t.astimezone(ET):%d %b %H:%M} ET ({t.astimezone(UTC):%H:%M}Z)"


def duration(minutes: int) -> str:
    """The app's duration words: "2 h 30 m", "40 h 15 m", "3 d 12 h" from two days on."""
    h, m = divmod(abs(minutes), 60)
    if h >= 48:
        d, rest = divmod(h, 24)
        return f"{d} d" if rest == 0 else f"{d} d {rest} h"
    if h == 0:
        return f"{m} m"
    return f"{h} h" if m == 0 else f"{h} h {m} m"


def deadline_clause(due: datetime, at: datetime) -> str:
    """The earliest deadline against the scenario clock, with its date: a passed one is never "next"."""
    minutes = round((due - at).total_seconds() / 60)
    if minutes < 0:
        return f"the earliest deadline, {_clock(due)}, passed {duration(minutes)} ago"
    return f"the next deadline is {_clock(due)}, in {duration(minutes)}"


def function_lines(
    open_t3: Sequence[ProposalSummary],
    status: ReplayStatus | None,
    water: tuple[int, int],
    crew: Counter[str],
    at: datetime,
) -> list[BriefFunctionLine]:
    if open_t3:
        first = min(open_t3, key=lambda p: p.effective_decide_by_utc)
        n = len(open_t3)
        command = (
            f"{_count(n)} decision{'s need' if n != 1 else ' needs'} two teams to sign;"
            f" {deadline_clause(first.effective_decide_by_utc, at)} ({first.title})."
        )
    else:
        command = "No decision is waiting for two teams to sign."
    if status is None:
        operations = "No outage report yet."
    else:
        operations = (
            f"{status.customers_out_now:,} customers out in {status.counties_out} counties,"
            f" {status.trend} over 6 hours."
        )
    issued, expected = water
    water_line = (
        f"{issued} water zone{'s' if issued != 1 else ''} under a boil-water advisory;"
        f" {expected} expected to need one."
    )
    working = sum(crew[s.value] for s in WORKING)
    logistics = (
        f"{working} crews working, {crew[CrewStatus.STAGED.value]} staged,"
        f" {crew[CrewStatus.AVAILABLE.value]} available."
    )
    return [
        BriefFunctionLine(function=ApprovalFunction.COMMAND, sentence=command),
        BriefFunctionLine(function=ApprovalFunction.OPERATIONS, sentence=operations),
        BriefFunctionLine(function=ApprovalFunction.WATER_OPERATIONS, sentence=water_line),
        BriefFunctionLine(function=ApprovalFunction.LOGISTICS, sentence=logistics),
    ]


def brief(
    conn: psycopg.Connection[Any], at: datetime, scenario: str, summaries: Sequence[ProposalSummary]
) -> ExecutiveBrief:
    at = at.astimezone(UTC)
    open_t3 = sorted(
        (p for p in summaries if p.tier is Tier.T3 and p.state in OPEN_STATES),
        key=lambda p: (p.effective_decide_by_utc, p.proposal_id),
    )
    try:
        status: ReplayStatus | None = replay_status(at)
    except ValueError:
        status = None
    fc = forecast_customers_out(conn, at)
    facilities = critical_facilities(at, scenario)
    issued, expected, water_as_of = water_counts(conn, at)
    crew = crews(at, scenario, conn)
    advisory = last_advisory(at, scenario)
    word, basis = status_word(open_t3, status, advisory, at)
    numbers = [
        BriefNumber(
            key="customers_out",
            label="Customers out",
            actual=status.customers_out_now if status else None,
            forecast=fc.p50_sum if fc else None,
            forecast_basis=(
                f"sum of county P50 peaks, forecast issued {_clock(fc.issued_at)}" if fc else None
            ),
            unit="customers",
            provenance=Provenance(
                source=f"{display_name('oms')} by county; outage forecast",
                model_id=fc.model_version if fc else None,
                as_of=status.as_of if status else None,
                label=NumberLabel.S,
            ),
        ),
        BriefNumber(
            key="critical_facilities",
            label="Critical facilities affected",
            actual=len(facilities),
            forecast=None,
            forecast_basis=None,
            unit="facilities",
            breakdown={f: 1 for f in facilities},
            provenance=Provenance(
                source=f"{display_name('oms')} (open outages)", as_of=at, label=NumberLabel.S
            ),
        ),
        BriefNumber(
            key="water_zones_advisory",
            label="Water zones under advisory",
            actual=issued,
            forecast=expected,
            forecast_basis="zones at or above the policy line, or with an advisory due, proposed or issued",
            unit="zones",
            provenance=Provenance(
                source="Water advisory register",
                rule_id="rule.sc_bwa_pre_landfall",
                as_of=water_as_of,
                label=NumberLabel.S,
            ),
        ),
        BriefNumber(
            key="crews_working",
            label="Crews working",
            actual=sum(crew[s.value] for s in WORKING),
            forecast=None,
            forecast_basis=None,
            unit="crews",
            breakdown=dict(sorted(crew.items())),
            provenance=Provenance(
                source=f"{display_name('fsm-crews')} (latest status per crew)", as_of=at, label=NumberLabel.S
            ),
        ),
    ]
    return ExecutiveBrief(
        as_of=at,
        status_word=word,  # type: ignore[arg-type]
        status_basis=basis,
        numbers=numbers,
        open_t3=open_t3,
        functions=function_lines(open_t3, status, (issued, expected), crew, at),
        last_advisory=advisory,
        caveat=CAVEAT,
        label=NumberLabel.S,
    )
