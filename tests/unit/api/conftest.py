from __future__ import annotations

import pytest

from sgw.api.ledger import ControlSnapshot
from sgw.contracts.vocab import DegradedMode, KillLevel, RunMode, ScenarioMode

from .api_testkit import FakeSource


@pytest.fixture
def source() -> FakeSource:
    return FakeSource(
        control_snap=ControlSnapshot(KillLevel.K0, DegradedMode.M0, RunMode.REPLAY, ScenarioMode.REPLAY, {})
    )
