"""Scenario clock: the one injectable time source for scenario time (DC-43).

Scenario time is a pure function of wall time and an anchor: `anchor_scenario + (wall - anchor_wall) * speed`,
clamped to the scenario window. Engines take a `TimeSource` and never read wall time themselves. The state is
persisted in `control_state.scenario_clock` so every process derives the same scenario time.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast, get_args

from sgw.common.numbers import value as number
from sgw.contracts.api_models import Bookmark, ScenarioCommand, ScenarioState
from sgw.contracts.golden import SCENARIO_END as MICRO_END
from sgw.contracts.golden import SCENARIO_START as MICRO_START
from sgw.contracts.vocab import RunMode, ScenarioMode

Speed = Literal[0, 1, 60, 900]
SPEEDS: tuple[int, ...] = get_args(Speed)
DEFAULT_PLAY_SPEED: Speed = 60


class TimeSource(Protocol):
    def now(self) -> datetime: ...


class SystemWallClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class ClockCommandError(ValueError):
    pass


@dataclass(frozen=True)
class ScenarioDef:
    name: str
    window_start: datetime
    window_end: datetime
    bookmarks: tuple[tuple[str, datetime], ...]

    def bookmark(self, name: str) -> datetime:
        for key, at in self.bookmarks:
            if key == name:
                return at
        raise ClockCommandError(f"unknown bookmark {name!r} for scenario {self.name}")

    def clamp(self, at: datetime) -> datetime:
        return min(max(at, self.window_start), self.window_end)


def _helene() -> ScenarioDef:
    first_record = datetime(2024, 9, 23, 12, 0, tzinfo=UTC)
    landfall = datetime(2024, 9, 27, 3, 10, tzinfo=UTC)
    peak = datetime(2024, 9, 27, 14, 0, tzinfo=UTC)
    etr = peak + timedelta(hours=float(number("helene_hours_to_ninety_pct_restored")))
    return ScenarioDef(
        name="helene",
        window_start=first_record,
        window_end=datetime(2024, 10, 6, 12, 0, tzinfo=UTC),
        bookmarks=(
            ("H0-72", landfall - timedelta(hours=72)),
            ("H0-24", landfall - timedelta(hours=24)),
            ("H0", landfall),
            ("landfall", landfall),
            ("peak", peak),
            ("peak+24h", peak + timedelta(hours=24)),
            ("etr", etr),
        ),
    )


def _helene_micro() -> ScenarioDef:
    return ScenarioDef(
        name="helene_micro",
        window_start=MICRO_START,
        window_end=MICRO_END,
        bookmarks=(
            ("H0-24", datetime(2024, 9, 26, 3, 40, tzinfo=UTC)),
            ("landfall", datetime(2024, 9, 27, 3, 10, tzinfo=UTC)),
        ),
    )


def _ian() -> ScenarioDef:
    from sgw.scenarios import packs

    pack = packs.load("ian")
    return ScenarioDef(
        name=pack.scenario,
        window_start=pack.window_start,
        window_end=pack.window_end,
        bookmarks=pack.bookmarks,
    )


SCENARIOS: dict[str, Callable[[], ScenarioDef]] = {
    "helene": _helene,
    "helene_micro": _helene_micro,
    "ian": _ian,
}


def scenario_def(name: str) -> ScenarioDef:
    try:
        return SCENARIOS[name]()
    except KeyError:
        raise ClockCommandError(f"unknown scenario {name!r}; known: {sorted(SCENARIOS)}") from None


@dataclass(frozen=True)
class ClockState:
    scenario: str
    anchor_wall: datetime
    anchor_scenario: datetime
    speed: int
    play_speed: int

    def scenario_now(self, wall_now: datetime, sdef: ScenarioDef) -> datetime:
        elapsed = (wall_now - self.anchor_wall) * self.speed
        return sdef.clamp(self.anchor_scenario + elapsed)

    def effective_speed(self, wall_now: datetime, sdef: ScenarioDef) -> int:
        return 0 if self.scenario_now(wall_now, sdef) >= sdef.window_end else self.speed

    def to_json(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "anchor_wall": self.anchor_wall.isoformat(),
            "anchor_scenario": self.anchor_scenario.isoformat(),
            "speed": self.speed,
            "play_speed": self.play_speed,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> ClockState:
        speed, play = int(raw["speed"]), int(raw.get("play_speed", DEFAULT_PLAY_SPEED))
        if speed not in SPEEDS or play not in SPEEDS or play == 0:
            raise ClockCommandError("stored scenario clock has an invalid speed")
        return cls(
            scenario=str(raw["scenario"]),
            anchor_wall=datetime.fromisoformat(raw["anchor_wall"]).astimezone(UTC),
            anchor_scenario=datetime.fromisoformat(raw["anchor_scenario"]).astimezone(UTC),
            speed=speed,
            play_speed=play,
        )

    @classmethod
    def initial(cls, sdef: ScenarioDef, wall_now: datetime) -> ClockState:
        return cls(sdef.name, wall_now, sdef.window_start, 0, DEFAULT_PLAY_SPEED)


@dataclass(frozen=True)
class Transition:
    state: ClockState
    bookmark: str | None


def apply_command(
    state: ClockState, cmd: ScenarioCommand, wall_now: datetime, sdef: ScenarioDef
) -> Transition:
    """Pure state transition; re-anchors at `wall_now` so scenario time is continuous across commands."""
    here = replace(state, anchor_wall=wall_now, anchor_scenario=state.scenario_now(wall_now, sdef))
    if cmd.action == "play":
        return Transition(replace(here, speed=here.play_speed), None)
    if cmd.action == "pause":
        return Transition(replace(here, speed=0), None)
    if cmd.action == "speed":
        if cmd.speed is None:
            raise ClockCommandError("action 'speed' needs 'speed'")
        if cmd.speed == 0:
            return Transition(replace(here, speed=0), None)
        return Transition(replace(here, speed=cmd.speed, play_speed=cmd.speed), None)
    if cmd.action == "seek":
        if cmd.scenario_time is None:
            raise ClockCommandError("action 'seek' needs 'scenario_time'")
        if not sdef.window_start <= cmd.scenario_time <= sdef.window_end:
            raise ClockCommandError(
                f"scenario_time outside the window {sdef.window_start.isoformat()}.."
                f"{sdef.window_end.isoformat()}"
            )
        return Transition(replace(here, anchor_scenario=cmd.scenario_time), None)
    if cmd.action == "bookmark":
        if not cmd.bookmark:
            raise ClockCommandError("action 'bookmark' needs 'bookmark'")
        return Transition(replace(here, anchor_scenario=sdef.bookmark(cmd.bookmark)), cmd.bookmark)
    raise ClockCommandError(f"unknown action {cmd.action!r}")


@dataclass(frozen=True)
class ClockView:
    state: ClockState
    mode: ScenarioMode
    run_mode: RunMode


class ScenarioClock:
    """Process-wide scenario time source. `now()` never touches the database; the state is swapped in by the
    clock service after each command and by the ledger poller when another process changed it."""

    def __init__(self, sdef: ScenarioDef, state: ClockState, wall: TimeSource | None = None) -> None:
        self._wall = wall or SystemWallClock()
        self._sdef = sdef
        self._view = ClockView(state, ScenarioMode.REPLAY, RunMode.REPLAY)

    @property
    def wall(self) -> TimeSource:
        return self._wall

    @property
    def definition(self) -> ScenarioDef:
        return self._sdef

    @property
    def view(self) -> ClockView:
        return self._view

    def set_view(self, view: ClockView) -> None:
        if view.state.scenario != self._sdef.name:
            self._sdef = scenario_def(view.state.scenario)
        self._view = view

    def now(self) -> datetime:
        return self._view.state.scenario_now(self._wall.now(), self._sdef)

    def snapshot(self) -> ScenarioState:
        from sgw.api import scenario_phase
        from sgw.api.scenario_info import scenario_jumps, scenario_moments, scenario_period

        wall_now = self._wall.now()
        st = self._view.state
        now = st.scenario_now(wall_now, self._sdef)
        return ScenarioState(
            scenario=st.scenario,
            mode=self._view.mode,
            run_mode=self._view.run_mode,
            scenario_time=now,
            speed=cast(Speed, st.effective_speed(wall_now, self._sdef)),
            bookmarks=[Bookmark(name=n, scenario_time=at) for n, at in self._sdef.bookmarks],  # type: ignore[arg-type]
            window_start=self._sdef.window_start,
            window_end=self._sdef.window_end,
            period=scenario_period(st.scenario),
            moments=list(scenario_moments(st.scenario)),
            jumps=list(scenario_jumps(st.scenario)),
            phase=scenario_phase.phase_at(st.scenario, now),
            phases=list(scenario_phase.phases(st.scenario)),
            final_advisory_utc=scenario_phase.final_advisory_utc(st.scenario),
        )
