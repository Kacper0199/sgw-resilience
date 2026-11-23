"""Read of the A1 hazard per advisory for the API (WP-06 `ensemble.json` official forecast, the scenario's
analysis track, the family's NHC cone table): the advisories issued by a scenario time and, for one advisory,
the analysis track up to its issue, the official track, the cone and the county peak gusts of the official
forecast. Nothing issued after the scenario time is returned."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import cache
from typing import Any

from sgw.contracts.api_models import HazardAdvisory, HazardAdvisoryDetail, HazardCone, Provenance
from sgw.contracts.vocab import NumberLabel
from sgw.generator.config import load_family, load_scenario
from sgw.models.hazard.hurdat2 import REPO_ROOT

FIXTURES = REPO_ROOT / "data" / "fixtures"
CONE_LEAD = "forecast.cone_lead_h"
CONE_RADIUS = "forecast.cone_radius_nmi"
DETAIL = "official forecast of the WP-06 synthetic Helene replay; cone radii NHC 2025 (family parameters)"


class NotIssued(LookupError):
    """No such advisory, or not issued by the scenario time."""


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


@cache
def _ensemble(scenario: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / scenario / "ensemble.json").read_text(encoding="utf-8"))
    return data


def _index(scenario: str) -> list[HazardAdvisory]:
    advs = sorted(_ensemble(scenario)["advisories"], key=lambda a: a["issued_utc"])
    return [
        HazardAdvisory(
            advisory_label=a["advisory_label"],
            issued_utc=_utc(a["issued_utc"]),
            next_advisory_utc=_utc(advs[i + 1]["issued_utc"]) if i + 1 < len(advs) else None,
        )
        for i, a in enumerate(advs)
    ]


def advisories(scenario: str, at: datetime) -> list[HazardAdvisory]:
    return [a for a in _index(scenario) if a.issued_utc <= at]


def advisory(scenario: str, label: str, at: datetime) -> HazardAdvisoryDetail:
    item = next((a for a in advisories(scenario, at) if a.advisory_label == label), None)
    if item is None:
        raise NotIssued(f"advisory {label} of {scenario} is not issued at {at:%Y-%m-%dT%H:%MZ}")
    ens = _ensemble(scenario)
    raw = next(a for a in ens["advisories"] if a["advisory_label"] == label)
    points = ens["points"]
    gusts = raw["official"]["peak_gust_ms"]
    counties = {
        pid: float(g)
        for pid, kind, g in zip(points["ids"], points["kinds"], gusts, strict=True)
        if kind == "county"
    }
    issued = raw["issued_utc"]
    scen = load_scenario(scenario)
    fam = load_family(str(scen.get("family", "A")))
    analysis = [
        (str(r[0]), float(r[1]), float(r[2]), float(r[3])) for r in scen["storm"]["track"] if r[0] <= issued
    ]
    return HazardAdvisoryDetail(
        **item.model_dump(),
        forecast_id=raw.get("forecast_id"),
        analysis_track=analysis,
        official_track=[
            (float(r[0]), float(r[1]), float(r[2]), float(r[3])) for r in raw["official"]["track"]
        ],
        cone=HazardCone(
            lead_h=[float(v) for v in fam[CONE_LEAD]], radius_nmi=[float(v) for v in fam[CONE_RADIUS]]
        ),
        county_peak_gust_ms=counties,
        provenance=Provenance(
            source=f"data/fixtures/{scenario}/ensemble.json",
            model_id=raw.get("forecast_id"),
            as_of=item.issued_utc,
            label=NumberLabel.S,
            detail=DETAIL,
        ),
    )
