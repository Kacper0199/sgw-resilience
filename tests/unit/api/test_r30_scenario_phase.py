from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sgw.api import scenario_phase
from sgw.api.clock import scenario_def


def t(day: int, hour: int, minute: int = 0) -> datetime:
    month = 9 if day > 9 else 10
    return datetime(2024, month, day, hour, minute, tzinfo=UTC)


def test_helene_phases_follow_landfall_peak_and_ninety_percent_restored() -> None:
    spans = scenario_phase.phases("helene")
    assert [s.phase for s in spans] == ["before_landfall", "storm", "restoration", "recovery"]
    sdef = scenario_def("helene")
    assert spans[0].starts_utc == sdef.window_start
    assert spans[1].starts_utc == sdef.bookmark("landfall") == t(27, 3, 10)
    assert spans[2].starts_utc == sdef.bookmark("peak")
    assert spans[3].starts_utc == sdef.bookmark("etr")
    assert [s.label for s in spans] == ["Before landfall", "Storm", "Restoration", "Recovery"]


@pytest.mark.parametrize(
    ("at", "phase"),
    [
        (t(26, 15, 5), "before_landfall"),
        (t(27, 3, 9), "before_landfall"),
        (t(27, 3, 10), "storm"),
        (t(27, 12), "storm"),
        (t(30, 12), "restoration"),
        (t(6, 2), "recovery"),
    ],
)
def test_phase_at_the_demo_moments(at: datetime, phase: str) -> None:
    assert scenario_phase.phase_at("helene", at) == phase


def test_the_final_advisory_is_the_one_that_names_no_next_advisory() -> None:
    assert scenario_phase.final_advisory_utc("helene") == t(27, 9)


def test_a_scenario_without_peak_or_restored_moment_stops_at_the_storm() -> None:
    spans = scenario_phase.phases("helene_micro")
    assert [s.phase for s in spans] == ["before_landfall", "storm"]
    assert scenario_phase.final_advisory_utc("helene_micro") is None


def test_the_scenario_state_carries_the_phase_timeline() -> None:
    from sgw.api.clock import ClockState, ScenarioClock, SystemWallClock, apply_command
    from sgw.contracts.api_models import ScenarioCommand

    sdef = scenario_def("helene")
    wall = SystemWallClock().now()
    seek = ScenarioCommand(action="seek", scenario_time=t(30, 12))
    clock = ScenarioClock(sdef, apply_command(ClockState.initial(sdef, wall), seek, wall, sdef).state)
    state = clock.snapshot()
    assert state.phase == "restoration"
    assert [p.phase for p in state.phases] == ["before_landfall", "storm", "restoration", "recovery"]
    assert state.final_advisory_utc == t(27, 9)
