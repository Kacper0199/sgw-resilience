"""Actual restoration against the published ETR: what the ETR planner checks after the estimate is out.

Actuals are the outage feed's county curve at the scenario clock (`county_hourly.csv`, the Brief's source),
summed per crew-yard area by each county's nearest yard (the area a crew yard serves, as the restoration
model assigns sections) and over all counties for the whole service area. The replay and the ETR model are
different restoration processes, so actual and estimate are compared as shares of each one's own peak, never
as customer counts.

- outcome: restored once an area is back to 10 percent of its observed peak after that peak (early before
  P10, late after P90); otherwise waiting, past the P50, or late after the P90;
- pace: the straight line from the estimate's share out at issue to the target share at its P50 gives the
  time the estimate expected today's actual share; the gap is how far restoration runs ahead (positive) or
  behind. DOM 14.206 Rev K section 6.4.2 revises a published ETR when the P50 moves by more than 12 h."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from zoneinfo import ZoneInfo

import numpy as np

from sgw.common.numbers import value as number
from sgw.contracts.api_models import EtrOutcome
from sgw.reports.sources import REPO_ROOT, county_series

GLOBAL = "GLOBAL"
NETWORK = REPO_ROOT / "data" / "fixtures" / "helene" / "network.json"
RULE = "DOM 14.206 Rev K section 6.4.2"
RULE_NAME = "ETR revision rule"
ET = ZoneInfo("America/New_York")
HOUR_S = 3600.0


def target_share() -> float:
    return 1.0 - float(number("policy_etr_restore_fraction_pct")) / 100.0


def margin_h() -> float:
    return float(number("dom_etr_revise_margin_h"))


@dataclass(frozen=True)
class AreaActual:
    as_of: datetime
    out_now: int
    peak: int
    restored_utc: datetime | None

    @property
    def share_now(self) -> float:
        return self.out_now / self.peak if self.peak > 0 else 0.0


@cache
def county_areas() -> dict[str, str]:
    """County FIPS -> the operating area of its nearest crew yard (`OPA-<county code>-<yard>`)."""
    from sgw.generator.config import load_counties
    from sgw.generator.network import distance_km
    from sgw.models.restoration.world import region_code

    yards = json.loads(NETWORK.read_text(encoding="utf-8"))["yards"]
    counties = load_counties()
    lat = np.array([c.lat for c in counties])[:, None]
    lon = np.array([c.lon for c in counties])[:, None]
    ylat = np.array([y["lat"] for y in yards])[None, :]
    ylon = np.array([y["lon"] for y in yards])[None, :]
    nearest = np.argmin(distance_km(lat, lon, ylat, ylon), axis=1)
    return {c.fips: region_code(str(yards[int(i)]["id"])) for c, i in zip(counties, nearest, strict=True)}


@cache
def _area_series() -> dict[str, dict[datetime, int]]:
    areas = county_areas()
    out: dict[str, dict[datetime, int]] = defaultdict(lambda: defaultdict(int))
    for hour, by_county in county_series().items():
        for fips, customers in by_county.items():
            out[GLOBAL][hour] += customers
            area = areas.get(fips)
            if area is not None:
                out[area][hour] += customers
    return {k: dict(v) for k, v in out.items()}


def actuals(at: datetime) -> dict[str, AreaActual]:
    """Per area id (and `GLOBAL`): customers out at the last whole hour at or before `at`, the peak so far
    and the first hour after that peak back at the target share, all known by `at`."""
    at = at.astimezone(UTC)
    out: dict[str, AreaActual] = {}
    for area, series in _area_series().items():
        hours = sorted(t for t in series if t <= at)
        if not hours:
            continue
        peak_at = max(hours, key=lambda t: (series[t], -t.timestamp()))
        peak = series[peak_at]
        limit = target_share() * peak
        restored = next((t for t in hours if t > peak_at and series[t] <= limit), None)
        out[area] = AreaActual(hours[-1], series[hours[-1]], peak, restored)
    return out


def outcome(p10: datetime, p50: datetime, p90: datetime, actual: AreaActual, at: datetime) -> EtrOutcome:
    if actual.restored_utc is not None:
        if actual.restored_utc < p10:
            return "restored_early"
        return "restored_late" if actual.restored_utc > p90 else "restored"
    if at > p90:
        return "late"
    return "past_p50" if at > p50 else "waiting"


def ahead_hours(
    issued: datetime, share_at_issue: float, p50: datetime, actual: AreaActual, at: datetime
) -> float:
    """Hours restoration runs ahead of the estimate's straight-line pace (negative: behind)."""
    if actual.restored_utc is not None:
        return (p50 - actual.restored_utc).total_seconds() / HOUR_S
    span = (p50 - issued).total_seconds()
    drop = share_at_issue - target_share()
    if span <= 0 or drop <= 0:
        return 0.0
    expected_at = issued.timestamp() + (share_at_issue - actual.share_now) / drop * span
    return (expected_at - at.timestamp()) / HOUR_S


def clock(t: datetime) -> str:
    local = t.astimezone(ET)
    return f"{local:%b} {local.day}, {local:%H:%M} ET"


def revised_p50(ahead_h: float, p50: datetime, actual: AreaActual) -> datetime:
    """The published likely time moved by the actual pace; the restored time once restoration got there."""
    if actual.restored_utc is not None:
        return actual.restored_utc
    moved = p50 - timedelta(hours=ahead_h)
    return moved.replace(second=0, microsecond=0)


def revision_reason(ahead_h: float, p50: datetime, actual: AreaActual, at: datetime) -> str:
    pace = "ahead of" if ahead_h >= 0 else "behind"
    hours = round(abs(ahead_h))
    if actual.restored_utc is not None:
        lead = (
            f"The whole service area was back to 90% restored at {clock(actual.restored_utc)}, {hours} h"
            f" {'before' if ahead_h >= 0 else 'after'} the published likely time ({clock(p50)})."
        )
    else:
        runs = f"{hours} h {pace}" if hours else "on pace with"
        lead = (
            f"Restoration runs {runs} the published estimate: {round(actual.share_now * 100)}% of"
            f" the peak is still out at {clock(at)}."
        )
    return f"{lead} Revise when the likely time moves by more than {margin_h():.0f} h."
