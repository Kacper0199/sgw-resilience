"""SC 103-314-style interruption report draft.

S.C. Code Ann. Regs. 103-314 (Interruption of Service; SC PSC electric rules, ch. 103 art. 3): the utility
keeps a record of any interruption affecting the entire system, a major division, or a major community, with
its time, duration and cause; notifies the Commission and the ORS as soon as practicable; and files a complete
report after restoration when the interruption lasted more than six hours. Source as read in this project: the
Oct 2024 copy of the SC PSC electric rules (R04 state-rules report, section 2). No SC rule prescribes ETR,
SAIDI or SAIFI content, so the draft states time, duration, cause and affected area only.

The records come from the replayed section outages (`outages.csv`, synthetic data): one record per South
Carolina county (a major community, assumption) and one for the SC system as a whole. Notification times are
not held by the platform and are left for the filer. The draft is never filed by the platform."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from sgw.reports.sources import OUTAGES
from sgw.reports.sources import county_codes as network_county_codes

CITATION = "S.C. Code Ann. Regs. 103-314 (Interruption of Service)"
SOURCE_NOTE = "SC PSC electric rules, ch. 103 art. 3 (copy dated Oct 2024)"
REPORT_THRESHOLD_H = 6.0
SC_FIPS_PREFIX = "45"
SYSTEM_ID = "SC-SYSTEM"
SYNTHETIC_LABEL = "Synthetic data: Helene replay on the SGW synthetic network. Draft, not filed."


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class InterruptionRecord(_Model):
    area_id: str
    area_kind: str
    county_code: str | None
    started_at: datetime
    restored_at: datetime | None = Field(description="null while the area is still out at the review time")
    duration_h: float
    customers_interrupted: int
    sections: int
    max_gust_ms: float
    damage_states: dict[str, int]
    cause: str
    report_required: bool


class InterruptionReport(_Model):
    citation: str
    source_note: str
    label: str
    threshold_h: float
    event_name: str
    system: InterruptionRecord
    counties: list[InterruptionRecord]

    @property
    def reportable(self) -> list[InterruptionRecord]:
        return [r for r in self.counties if r.report_required]


def _t(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _cause(event: str, gust: float, states: Counter[str]) -> str:
    worst = ", ".join(f"{k} {v}" for k, v in sorted(states.items()))
    return (
        f"{event}: wind and tree damage to distribution sections (peak gust at a damaged section "
        f"{gust:.0f} m/s; damage states: {worst})"
    )


def _record(
    area_id: str,
    kind: str,
    code: str | None,
    rows: list[dict[str, str]],
    event: str,
    as_of: datetime | None = None,
) -> InterruptionRecord:
    start = min(_t(r["fault_utc"]) for r in rows)
    backs = [_t(r["customers_back_utc"]) if r["customers_back_utc"] else None for r in rows]
    known = [b for b in backs if b is not None and (as_of is None or b <= as_of)]
    end = max(known) if len(known) == len(backs) else None
    until = end if end is not None else (as_of or start)
    gust = max(float(r["peak_gust_ms"]) for r in rows)
    states = Counter(r["damage_state"] for r in rows)
    duration = round((until - start).total_seconds() / 3600.0, 1)
    return InterruptionRecord(
        area_id=area_id,
        area_kind=kind,
        county_code=code,
        started_at=start,
        restored_at=end,
        duration_h=duration,
        customers_interrupted=sum(int(r["customers"]) for r in rows),
        sections=len(rows),
        max_gust_ms=round(gust, 1),
        damage_states=dict(sorted(states.items())),
        cause=_cause(event, gust, states),
        report_required=duration > REPORT_THRESHOLD_H,
    )


def build(
    outages: Path = OUTAGES,
    county_codes: dict[str, str] | None = None,
    event_name: str = "Hurricane Helene",
    as_of: datetime | None = None,
) -> InterruptionReport:
    """The records known at `as_of` (the review's scenario time): sections faulted by then, and an area is
    restored only once all of them are back by then; with no `as_of`, the whole replay."""
    by_county: dict[str, list[dict[str, str]]] = defaultdict(list)
    with outages.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r["fips"].startswith(SC_FIPS_PREFIX) or not r["customers_back_utc"]:
                continue
            if as_of is not None and _t(r["fault_utc"]) > as_of:
                continue
            by_county[r["fips"]].append(r)
    if not by_county:
        raise ValueError("no South Carolina section outages in the replay")
    codes = county_codes if county_codes is not None else network_county_codes()
    counties = [
        _record(f"SC-{fips}", "county", codes.get(fips), rows, event_name, as_of)
        for fips, rows in sorted(by_county.items())
    ]
    every = [r for rows in by_county.values() for r in rows]
    return InterruptionReport(
        citation=CITATION,
        source_note=SOURCE_NOTE,
        label=SYNTHETIC_LABEL,
        threshold_h=REPORT_THRESHOLD_H,
        event_name=event_name,
        system=_record(SYSTEM_ID, "system", None, every, event_name, as_of),
        counties=sorted(counties, key=lambda r: (-r.customers_interrupted, r.area_id)),
    )


def _restored(r: InterruptionRecord) -> str:
    return f"{r.restored_at:%Y-%m-%d %H:%MZ}" if r.restored_at is not None else "not yet"


def _row(r: InterruptionRecord) -> str:
    area = r.area_id + (f" ({r.county_code})" if r.county_code else "")
    return (
        f"| {area} | {r.started_at:%Y-%m-%d %H:%MZ} | {_restored(r)} | {r.duration_h:.1f} h"
        f" | {r.customers_interrupted:,} | {'yes' if r.report_required else 'no'} |"
    )


def interruption_summary(report: InterruptionReport) -> str:
    """Interruption-only summary for the filing, written by code: what the rule asks (time, duration, cause,
    area), nothing from the wider after-action review."""
    s = report.system
    longest = max(report.counties, key=lambda r: (r.duration_h, r.area_id))
    return (
        f"{report.event_name} interrupted service to {s.customers_interrupted:,} customers in the South"
        f" Carolina service area from {s.started_at:%Y-%m-%d %H:%MZ} "
        + (
            f"until the last damaged section was back at {_restored(s)} ({s.duration_h:.1f} h)."
            if s.restored_at is not None
            else f"and is not yet restored ({s.duration_h:.1f} h so far)."
        )
        + f" {len(report.reportable)} of"
        f" {len(report.counties)} affected counties were interrupted for more than {report.threshold_h:.0f}"
        f" hours; the longest was {longest.area_id}"
        + (f" ({longest.county_code})" if longest.county_code else "")
        + f" at {longest.duration_h:.1f} h. Cause: {s.cause}."
    )


def render_markdown(report: InterruptionReport, banner: str | None = None, limit: int = 15) -> str:
    """The draft as Markdown. Every number is formatted here by code; the summary covers the interruption
    only. `banner` (a broken audit chain) is printed first."""
    reportable = report.reportable
    lines = [
        *([banner, ""] if banner else []),
        f"# {report.event_name}: interruption report draft under {report.citation}",
        "",
        report.label,
        "",
        f"Rule: {report.citation}. {report.source_note}. The rule asks for a record of time, duration and"
        " cause, notice to the Commission and the ORS as soon as practicable, and a complete report after"
        f" restoration for an interruption longer than {report.threshold_h:.0f} hours.",
        "",
        "## Summary",
        "",
        interruption_summary(report),
        "",
        "## System record",
        "",
        "| Area | Started | Restored | Duration | Customers interrupted | Over 6 h |",
        "| --- | --- | --- | --- | --- | --- |",
        _row(report.system),
        "",
        f"Cause: {report.system.cause}.",
        "",
        f"## Counties over {report.threshold_h:.0f} hours ({len(reportable)} of {len(report.counties)})",
        "",
        "| Area | Started | Restored | Duration | Customers interrupted | Over 6 h |",
        "| --- | --- | --- | --- | --- | --- |",
        *[_row(r) for r in reportable[:limit]],
    ]
    if len(reportable) > limit:
        lines.append(f"| {len(reportable) - limit} more counties in the attached records | | | | | |")
    lines += [
        "",
        "## For the filer",
        "",
        "- Notice to the Commission and the ORS: times are not held by the platform; enter them before"
        " filing.",
        "- Restored means the last customer of the area's damaged sections back on supply in the replay.",
        "- Counties stand in for the rule's major communities (assumption); the filer confirms the areas.",
    ]
    return "\n".join(lines) + "\n"
