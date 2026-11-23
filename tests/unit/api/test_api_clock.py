from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sgw.api.clock import (
    ClockCommandError,
    ClockState,
    ClockView,
    ScenarioClock,
    apply_command,
    scenario_def,
)
from sgw.contracts.api_models import ScenarioCommand, ScenarioState
from sgw.contracts.vocab import RunMode, ScenarioMode

WALL0 = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


class FakeWall:
    def __init__(self, at: datetime = WALL0) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at


def _cmd(**kw: object) -> ScenarioCommand:
    return ScenarioCommand.model_validate(kw)


def test_helene_window_and_bookmarks_follow_dc43() -> None:
    h = scenario_def("helene")
    assert h.window_start == datetime(2024, 9, 23, 12, tzinfo=UTC)
    assert h.window_end == datetime(2024, 10, 6, 12, tzinfo=UTC), "DC-43 end moved to contain the ETR mark"
    marks = dict(h.bookmarks)
    assert marks["landfall"] == datetime(2024, 9, 27, 3, 10, tzinfo=UTC)
    assert marks["H0-72"] == marks["landfall"] - timedelta(hours=72)
    assert marks["etr"] == marks["peak"] + timedelta(hours=204)
    assert all(h.window_start <= at <= h.window_end for at in marks.values())


def test_initial_state_is_paused_at_window_start() -> None:
    sdef = scenario_def("helene")
    st = ClockState.initial(sdef, WALL0)
    assert st.speed == 0
    assert st.scenario_now(WALL0 + timedelta(hours=5), sdef) == sdef.window_start


def test_play_advances_at_speed_and_pause_freezes() -> None:
    sdef = scenario_def("helene")
    st = apply_command(ClockState.initial(sdef, WALL0), _cmd(action="play"), WALL0, sdef).state
    assert st.speed == 60
    t1 = WALL0 + timedelta(minutes=1)
    assert st.scenario_now(t1, sdef) == sdef.window_start + timedelta(hours=1)
    paused = apply_command(st, _cmd(action="pause"), t1, sdef).state
    assert paused.scenario_now(t1 + timedelta(hours=3), sdef) == sdef.window_start + timedelta(hours=1)
    resumed = apply_command(paused, _cmd(action="play"), t1, sdef).state
    assert resumed.speed == 60, "play resumes the last non-zero speed"


def test_speed_change_is_continuous_and_remembered() -> None:
    sdef = scenario_def("helene")
    st = apply_command(ClockState.initial(sdef, WALL0), _cmd(action="speed", speed=900), WALL0, sdef).state
    t1 = WALL0 + timedelta(seconds=4)
    at_t1 = st.scenario_now(t1, sdef)
    assert at_t1 == sdef.window_start + timedelta(hours=1)
    st2 = apply_command(st, _cmd(action="speed", speed=1), t1, sdef).state
    assert st2.scenario_now(t1, sdef) == at_t1
    assert st2.play_speed == 1
    st3 = apply_command(st2, _cmd(action="speed", speed=0), t1, sdef).state
    assert st3.speed == 0 and st3.play_speed == 1


def test_seek_and_bookmark() -> None:
    sdef = scenario_def("helene")
    st = ClockState.initial(sdef, WALL0)
    target = datetime(2024, 9, 25, tzinfo=UTC)
    assert (
        apply_command(st, _cmd(action="seek", scenario_time=target), WALL0, sdef).state.scenario_now(
            WALL0, sdef
        )
        == target
    )
    moved = apply_command(st, _cmd(action="bookmark", bookmark="landfall"), WALL0, sdef)
    assert moved.bookmark == "landfall"
    assert moved.state.scenario_now(WALL0, sdef) == dict(sdef.bookmarks)["landfall"]


@pytest.mark.parametrize(
    "kw",
    [
        {"action": "seek"},
        {"action": "seek", "scenario_time": "2024-01-01T00:00:00Z"},
        {"action": "speed"},
        {"action": "bookmark"},
        {"action": "bookmark", "bookmark": "nowhere"},
    ],
)
def test_invalid_commands_are_rejected(kw: dict[str, object]) -> None:
    sdef = scenario_def("helene")
    with pytest.raises(ClockCommandError):
        apply_command(ClockState.initial(sdef, WALL0), _cmd(**kw), WALL0, sdef)


def test_clock_clamps_at_window_end_and_reports_speed_zero() -> None:
    sdef = scenario_def("helene_micro")
    wall = FakeWall()
    st = apply_command(ClockState.initial(sdef, WALL0), _cmd(action="speed", speed=900), WALL0, sdef).state
    clock = ScenarioClock(sdef, st, wall)
    wall.at = WALL0 + timedelta(hours=10)
    snap = clock.snapshot()
    assert snap.scenario_time == sdef.window_end
    assert snap.speed == 0
    ScenarioState.model_validate(snap.model_dump(mode="json"))


def test_state_round_trips_through_json_and_rejects_bad_speed() -> None:
    sdef = scenario_def("helene")
    st = apply_command(ClockState.initial(sdef, WALL0), _cmd(action="play"), WALL0, sdef).state
    assert ClockState.from_json(st.to_json()) == st
    bad = st.to_json() | {"speed": 7}
    with pytest.raises(ClockCommandError):
        ClockState.from_json(bad)


def test_set_view_switches_scenario_definition() -> None:
    clock = ScenarioClock(
        scenario_def("helene"), ClockState.initial(scenario_def("helene"), WALL0), FakeWall()
    )
    micro = ClockState.initial(scenario_def("helene_micro"), WALL0)
    clock.set_view(ClockView(micro, ScenarioMode.EXERCISE, RunMode.REPLAY))
    snap = clock.snapshot()
    assert snap.scenario == "helene_micro" and snap.mode is ScenarioMode.EXERCISE
    assert clock.now() == scenario_def("helene_micro").window_start


def test_unknown_scenario() -> None:
    with pytest.raises(ClockCommandError):
        scenario_def("atlantis")
