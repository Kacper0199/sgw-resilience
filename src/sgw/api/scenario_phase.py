"""The storm's phases on the scenario clock: what the screens may present as current at a scenario time.

- before landfall: from the window start to the observed landfall (scenario bookmark `landfall`);
- storm: landfall to the observed outage peak (`peak`); forecasts of the peak still look ahead;
- restoration: the peak to 90 percent of the peak customers restored (`etr`); the screens show what was
  observed and the restoration, the forecast only as "forecast vs actual";
- recovery: after that.

A phase starts only at a bookmark the scenario defines, so a scenario without a peak ends at the storm. The
final advisory is the first issued advisory that names no next advisory (the weather feed, as the Brief reads
it); from its issue time no "next advisory" exists."""

from __future__ import annotations

from datetime import datetime
from functools import cache

from sgw.contracts.api_models import ScenarioPhase, ScenarioPhaseName

PHASE_LABEL: dict[ScenarioPhaseName, str] = {
    "before_landfall": "Before landfall",
    "storm": "Storm",
    "restoration": "Restoration",
    "recovery": "Recovery",
}
STARTS_AT: tuple[tuple[ScenarioPhaseName, str], ...] = (
    ("storm", "landfall"),
    ("restoration", "peak"),
    ("recovery", "etr"),
)


@cache
def phases(scenario: str) -> tuple[ScenarioPhase, ...]:
    from sgw.api.clock import scenario_def

    sdef = scenario_def(scenario)
    marks = dict(sdef.bookmarks)
    out = [
        ScenarioPhase(
            phase="before_landfall", label=PHASE_LABEL["before_landfall"], starts_utc=sdef.window_start
        )
    ]
    for phase, mark in STARTS_AT:
        if mark not in marks:
            break
        out.append(ScenarioPhase(phase=phase, label=PHASE_LABEL[phase], starts_utc=marks[mark]))
    return tuple(out)


def phase_at(scenario: str, at: datetime) -> ScenarioPhaseName:
    current = phases(scenario)[0].phase
    for span in phases(scenario):
        if span.starts_utc <= at:
            current = span.phase
    return current


@cache
def final_advisory_utc(scenario: str) -> datetime | None:
    from sgw.api.readmodels.brief import FIXTURES, all_events
    from sgw.scenarios import packs

    if packs.is_pack(scenario):
        return packs.load(scenario).advisories()[-1].issued
    for event in all_events(FIXTURES / scenario / "weather.jsonl", "WeatherForecastIssued"):
        if not event.payload.get("next_advisory_utc"):
            return event.issued_at or event.known_at
    return None
