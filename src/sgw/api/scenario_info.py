"""What a scenario is, for people and for AI prompts (D-100 Q-06 and Q-08): its period in Eastern time,
its key moments and the demo moments a clock operator may jump to.

`scenario_period(name).statement` is the sentence an AI prompt context reads; `GET /api/scenario` serves the
same `period`. Jumps are the `sgw demo goto` bookmark times (`sgw.demo.bookmarks`) reached by seeking the
scenario clock; they move the clock, never the database."""

from __future__ import annotations

from datetime import datetime
from functools import cache
from zoneinfo import ZoneInfo

from sgw.contracts.api_models import ScenarioMoment, ScenarioPeriod

TIME_ZONE = "America/New_York"
ET = ZoneInfo(TIME_ZONE)
TITLE = {"helene": "Hurricane Helene", "helene_micro": "Hurricane Helene"}
DATA_NOTE = "Synthetic SGW utility data on the real storm's track and weather"
MOMENT_LABEL = {"landfall": "Landfall", "peak": "Peak outages", "etr": "90% of customers restored"}
MOMENT_KIND = {"landfall": "landfall", "peak": "peak", "etr": "restored"}
JUMP_LABEL = {
    "before-n": "Before the 5 AM advisory",
    "at-n": "5 AM advisory",
    "at-n1": "11 AM advisory: deadlines move",
    "morning-after": "Morning after landfall",
    "etr-published": "Restoration estimate published",
    "notices-lifted": "Boil-water notices lifted",
    "after-action": "After-action review",
}
JUMP_SCENARIOS = frozenset({"helene"})
HAZARD_SCENARIOS = frozenset({"helene"})


def _day(at: datetime) -> str:
    local = at.astimezone(ET)
    return f"{local.day} {local:%b %Y}"


def _label(start: datetime, end: datetime) -> str:
    a, b = start.astimezone(ET), end.astimezone(ET)
    if a.year != b.year:
        return f"{_day(a)} – {_day(b)}"
    return f"{a.day} {a:%b} – {b.day} {b:%b %Y}"


def _pack_period(name: str) -> ScenarioPeriod:
    from sgw.scenarios import packs

    pack = packs.load(name)
    start, end = pack.window_start, pack.window_end
    return ScenarioPeriod(
        title=pack.title,
        start_utc=start,
        end_utc=end,
        time_zone=TIME_ZONE,
        label=_label(start, end),
        data_note=pack.label,
        statement=(
            f"Scenario period: an exercise on {pack.title} from {_day(start)}"
            f" {start.astimezone(ET):%H:%M} ET to {_day(end)} {end.astimezone(ET):%H:%M} ET, on the real"
            " storm track with scripted synthetic SGW data. Every time in the platform is a scenario time"
            " inside this period; never compare it with today's date."
        ),
    )


def _pack_moments(name: str) -> tuple[ScenarioMoment, ...]:
    from sgw.scenarios import packs

    pack = packs.load(name)
    out = [
        ScenarioMoment(moment_id=f"advisory-{i}", kind="advisory", label="Advisory", scenario_time=a.issued)
        for i, a in enumerate(pack.advisories(), start=1)
    ]
    out += [
        ScenarioMoment(
            moment_id=key,
            kind=MOMENT_KIND[key],  # type: ignore[arg-type]
            label=MOMENT_LABEL[key],
            scenario_time=at,
        )
        for key, at in pack.bookmarks
        if key in MOMENT_LABEL
    ]
    return tuple(sorted(out, key=lambda m: m.scenario_time))


@cache
def scenario_period(name: str) -> ScenarioPeriod:
    from sgw.api.clock import scenario_def
    from sgw.scenarios import packs

    if packs.is_pack(name):
        return _pack_period(name)
    sdef = scenario_def(name)
    title = TITLE.get(name, name)
    start, end = sdef.window_start, sdef.window_end
    return ScenarioPeriod(
        title=title,
        start_utc=start,
        end_utc=end,
        time_zone=TIME_ZONE,
        label=_label(start, end),
        data_note=DATA_NOTE,
        statement=(
            f"Scenario period: a replay of {title} from {_day(start)} {start.astimezone(ET):%H:%M} ET to"
            f" {_day(end)} {end.astimezone(ET):%H:%M} ET, with synthetic SGW utility data. Every time in the"
            " platform is a scenario time inside this period; never compare it with today's date."
        ),
    )


@cache
def scenario_moments(name: str) -> tuple[ScenarioMoment, ...]:
    from sgw.api.clock import scenario_def
    from sgw.models.hazard.read import advisories
    from sgw.scenarios import packs

    if packs.is_pack(name):
        return _pack_moments(name)
    sdef = scenario_def(name)
    issued = [a.issued_utc for a in advisories(name, sdef.window_end)] if name in HAZARD_SCENARIOS else []
    out = [
        ScenarioMoment(moment_id=f"advisory-{i}", kind="advisory", label="Advisory", scenario_time=t)
        for i, t in enumerate(sorted(issued), start=1)
        if sdef.window_start <= t <= sdef.window_end
    ]
    restored = restored_utc(name, sdef.window_end)
    out += [
        ScenarioMoment(
            moment_id=key,
            kind=MOMENT_KIND[key],  # type: ignore[arg-type]
            label=MOMENT_LABEL[key],
            scenario_time=restored if key == "etr" and restored is not None else at,
        )
        for key, at in sdef.bookmarks
        if key in MOMENT_LABEL
    ]
    return tuple(sorted(out, key=lambda m: m.scenario_time))


def restored_utc(name: str, end: datetime) -> datetime | None:
    """When the outage feed got back to the ETR target share, the Restoration page's definition."""
    if name not in HAZARD_SCENARIOS:
        return None
    from sgw.api.readmodels import etr_actuals

    whole = etr_actuals.actuals(end).get(etr_actuals.GLOBAL)
    return whole.restored_utc if whole is not None else None


@cache
def scenario_jumps(name: str) -> tuple[ScenarioMoment, ...]:
    from sgw.scenarios import packs

    if packs.is_pack(name):
        return tuple(
            ScenarioMoment(moment_id=m.moment_id, kind="demo", label=m.label, scenario_time=m.at)
            for m in packs.load(name).moments
        )
    if name not in JUMP_SCENARIOS:
        return ()
    from sgw.demo.bookmarks import BY_ID

    return tuple(
        ScenarioMoment(
            moment_id=bid,
            kind="demo",
            label=label,
            scenario_time=datetime.fromisoformat(BY_ID[bid].scenario_time),
        )
        for bid, label in JUMP_LABEL.items()
    )
