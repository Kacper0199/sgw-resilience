"""What the pages read for a scenario pack: the Brief, county outages and the hazard advisories,
from the pack's scripted data and the decisions its injects raised. Same contracts as the Helene reads; every
number is labelled scripted exercise data (synthetic)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sgw.api.readmodels import brief as helene_brief
from sgw.contracts.api_models import (
    AfterActionView,
    BriefAdvisory,
    BriefNumber,
    CountyOutage,
    CountyOutagesNow,
    CrewItem,
    EtrScorecard,
    ExecutiveBrief,
    HazardAdvisory,
    HazardAdvisoryDetail,
    HazardCone,
    ProposalSummary,
    Provenance,
    SurgeReport,
)
from sgw.contracts.vocab import CrewStatus, NumberLabel, ProposalState, Tier
from sgw.reports.sources import ReplayStatus
from sgw.scenarios.packs import Pack

TREND_WINDOW = timedelta(hours=6)
NOTICE_ACTION = "boil_water_notice"
DECIDED = frozenset({ProposalState.APPROVED.value, ProposalState.EXECUTED.value})


class NotIssued(LookupError):
    pass


def caveat(pack: Pack) -> str:
    return (
        f"{pack.label}: an exercise on the real track of {pack.title} ({pack.track_source}). Customers out,"
        " facilities, crews and decisions are scripted for the exercise, not modelled."
    )


def status(pack: Pack, at: datetime) -> ReplayStatus | None:
    hour = pack.feed_hour(at)
    if hour is None:
        return None
    now = pack.customers_out(hour)
    before = pack.customers_out(hour - TREND_WINDOW)
    peak_at, peak = pack.peak()
    if peak_at > hour:
        peak_at, peak = hour, max(now, before)
    trend = "rising" if now > before else "falling" if now < before else "steady"
    return ReplayStatus(
        as_of=hour,
        customers_out_now=now,
        peak_customers_out=peak,
        peak_at=peak_at,
        counties_out=len(pack.counties_out(hour)),
        customers_out_before=before,
        trend=trend,
    )


def county_outages(pack: Pack, at: datetime) -> CountyOutagesNow:
    hour = pack.feed_hour(at)
    if hour is None:
        return CountyOutagesNow(as_of=None, customers_out_now=0, counties=[])
    counties = [CountyOutage(fips=f, customers_out=n) for f, n in pack.counties_out(hour).items()]
    return CountyOutagesNow(
        as_of=hour, customers_out_now=sum(c.customers_out for c in counties), counties=counties
    )


def advisories(pack: Pack, at: datetime) -> list[HazardAdvisory]:
    return [
        HazardAdvisory(advisory_label=a.label, issued_utc=a.issued, next_advisory_utc=a.next_issued)
        for a in pack.advisories()
        if a.issued <= at
    ]


def advisory(pack: Pack, label: str, at: datetime) -> HazardAdvisoryDetail:
    item = next((a for a in advisories(pack, at) if a.advisory_label == label), None)
    if item is None:
        raise NotIssued(f"advisory {label} of {pack.scenario} is not issued at {at:%Y-%m-%dT%H:%MZ}")
    here = pack.position(item.issued_utc)
    analysis = [
        (f.at.strftime("%Y-%m-%dT%H:%M:%SZ"), f.lat, f.lon, f.vmax_kt)
        for f in pack.track
        if f.at <= item.issued_utc
    ]
    return HazardAdvisoryDetail(
        **item.model_dump(),
        forecast_id=None,
        analysis_track=analysis,
        official_track=[(0.0, here.lat, here.lon, here.vmax_kt)] if here is not None else [],
        cone=HazardCone(lead_h=[], radius_nmi=[]),
        county_peak_gust_ms={},
        provenance=Provenance(
            source=f"{pack.source_dir}/pack.yaml",
            as_of=item.issued_utc,
            label=NumberLabel.S,
            detail=f"{pack.track_source}; the track to the issue time only, no forecast cone",
        ),
    )


def last_advisory(pack: Pack, at: datetime) -> BriefAdvisory | None:
    issued = advisories(pack, at)
    if not issued:
        return None
    last = issued[-1]
    return BriefAdvisory(
        label=last.advisory_label,
        issued_utc=last.issued_utc,
        landfall_eta_utc=pack.landfall if last.issued_utc < pack.landfall else None,
        next_advisory_utc=last.next_advisory_utc,
    )


def water_counts(summaries: Sequence[ProposalSummary]) -> tuple[int, int]:
    notices = [p for p in summaries if p.action_type == NOTICE_ACTION]
    issued = sum(1 for p in notices if p.state.value in DECIDED)
    expected = sum(1 for p in notices if p.state in helene_brief.OPEN_STATES or p.state.value in DECIDED)
    return issued, expected


def brief(pack: Pack, at: datetime, summaries: Sequence[ProposalSummary]) -> ExecutiveBrief:
    """The executive Brief of a pack at the scenario time; `summaries` are the pack's own decisions."""
    at = at.astimezone(UTC)
    open_t3 = sorted(
        (p for p in summaries if p.tier is Tier.T3 and p.state in helene_brief.OPEN_STATES),
        key=lambda p: (p.effective_decide_by_utc, p.proposal_id),
    )
    st = status(pack, at)
    facilities = pack.facilities_out(at)
    issued, expected = water_counts(summaries)
    crew = Counter(pack.crew_counts(at))
    adv = last_advisory(pack, at)
    word, basis = helene_brief.status_word(open_t3, st, adv, at)
    source = f"{pack.source_dir} ({pack.label})"
    numbers = [
        BriefNumber(
            key="customers_out",
            label="Customers out",
            actual=st.customers_out_now if st else None,
            forecast=None,
            forecast_basis=None,
            unit="customers",
            provenance=Provenance(source=source, as_of=st.as_of if st else None, label=NumberLabel.S),
        ),
        BriefNumber(
            key="critical_facilities",
            label="Critical facilities affected",
            actual=len(facilities),
            forecast=None,
            forecast_basis=None,
            unit="facilities",
            breakdown={f: 1 for f in facilities},
            provenance=Provenance(source=source, as_of=at, label=NumberLabel.S),
        ),
        BriefNumber(
            key="water_zones_advisory",
            label="Water zones under advisory",
            actual=issued,
            forecast=expected,
            forecast_basis="zones with a boil-water notice proposed or issued in this exercise",
            unit="zones",
            provenance=Provenance(source=source, as_of=at, label=NumberLabel.S),
        ),
        BriefNumber(
            key="crews_working",
            label="Crews working",
            actual=sum(crew[s.value] for s in helene_brief.WORKING),
            forecast=None,
            forecast_basis=None,
            unit="crews",
            breakdown=dict(sorted(crew.items())),
            provenance=Provenance(source=source, as_of=at, label=NumberLabel.S),
        ),
    ]
    return ExecutiveBrief(
        as_of=at,
        status_word=word,  # type: ignore[arg-type]
        status_basis=basis,
        numbers=numbers,
        open_t3=open_t3,
        functions=helene_brief.function_lines(open_t3, st, (issued, expected), crew, at),
        last_advisory=adv,
        caveat=caveat(pack),
        label=NumberLabel.S,
    )


def no_surges(pack: Pack, at: datetime) -> SurgeReport:
    """The outage surge detector runs on the Helene outage feed only: an empty report, said plainly."""
    return SurgeReport(
        as_of=at,
        scenario=pack.scenario,
        data_through=at,
        counties_monitored=0,
        counties_surging=0,
        surges_total=0,
        first_detected_at=None,
        model_version="not-modelled",
        source=f"Not modelled for this scenario ({pack.label})",
        label="S",
        truncated=False,
        surges=[],
    )


def crews(pack: Pack, at: datetime, status: CrewStatus | None = None) -> list[CrewItem]:
    """The scripted crew roster at the scenario time; read-only (no dispatch actions for scripted crews)."""
    provenance = Provenance(
        source=f"{pack.source_dir}/pack.yaml", as_of=at, label=NumberLabel.S, detail=pack.label
    )
    items = [
        CrewItem(
            crew_id=c.crew_id,
            status=CrewStatus(c.status),
            location_id=c.location_id,
            headcount=c.headcount,
            shift_end=None,
            provenance=provenance,
            region_id=c.region_id,
        )
        for c in pack.roster(at)
    ]
    return [i for i in items if status is None or i.status is status]


def after_action(pack: Pack, view: AfterActionView, since_seq: int | None) -> AfterActionView:
    """The after-action review of the exercise only: its own decision deadlines and emergency approvals,
    the audit records from `since_seq` (the record of the exercise load) on, no ETR scorecard and no
    regulator report (the Helene models make those)."""
    return view.model_copy(
        update={
            "clocks": [c for c in view.clocks if pack.owns_case(c.decision_case_id)],
            "break_glass": [b for b in view.break_glass if pack.owns(b.proposal_id)],
            "timeline": [t for t in view.timeline if since_seq is not None and t.seq >= since_seq],
            "scorecard": EtrScorecard(
                name="Not modelled for this scenario",
                label=NumberLabel.S,
                actual_label=pack.label,
                source="none",
                as_of=None,
                resolved=0,
                total=0,
                resolved_label="0 of 0 resolved",
                metrics=[],
                estimates=[],
            ),
            "sc_report": None,
            "provenance": view.provenance.model_copy(update={"detail": pack.label}),
        }
    )


def load_seq(conn: Any, scenario: str) -> int | None:
    """The audit sequence of the record that loaded the scenario (the clock switch of the scenario load)."""
    row = conn.execute(
        "SELECT min(seq) FROM audit_event WHERE kind = 'scenario_clock_changed' AND subject = %s",
        (f"scenario:{scenario}",),
    ).fetchone()
    return None if row is None or row[0] is None else int(row[0])
