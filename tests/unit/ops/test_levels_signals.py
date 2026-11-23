"""Pure rules: capability matrix per kill level and mode, `FAULT_*` flags, signal hysteresis and probes."""

from __future__ import annotations

import httpx
import pytest

from sgw.contracts.vocab import DegradedMode, KillLevel
from sgw.ops import levels
from sgw.ops.control import floor_for
from sgw.ops.levels import Capability
from sgw.ops.probes import GatewayProbe, OpaProbe, configured_probes
from sgw.ops.reconciler import enabled
from sgw.ops.signals import Reading, SignalState, evaluate, fault_flags, step


def test_each_kill_level_removes_at_least_what_the_level_below_removes() -> None:
    order = list(KillLevel)
    for lower, higher in zip(order, order[1:], strict=False):
        assert levels.KILL_REMOVES[lower] <= levels.KILL_REMOVES[higher]
    assert levels.KILL_REMOVES[KillLevel.K4] == frozenset(Capability)


def test_capabilities_follow_the_threat_model_table() -> None:
    k1 = levels.capabilities(KillLevel.K1, DegradedMode.M0)
    assert not k1[Capability.APPROVE_AND_EXECUTE]
    assert k1[Capability.VIEW_DASHBOARDS] and k1[Capability.AGENT_RUNS] and k1[Capability.LLM_CALLS]
    k2 = levels.capabilities(KillLevel.K2, DegradedMode.M2)
    assert not k2[Capability.AGENT_RUNS] and not k2[Capability.LLM_CALLS]
    assert k2[Capability.VIEW_DASHBOARDS] and k2[Capability.INGEST_EXTERNAL]
    k3 = levels.capabilities(KillLevel.K3, DegradedMode.M3)
    assert not k3[Capability.INGEST_EXTERNAL] and not k3[Capability.CREATE_PROPOSALS]
    assert k3[Capability.VIEW_DASHBOARDS] and k3[Capability.MANUAL_WORKFLOW]
    assert not any(levels.capabilities(KillLevel.K4, DegradedMode.M4).values())
    m2 = levels.capabilities(KillLevel.K0, DegradedMode.M2)
    assert not m2[Capability.LLM_CALLS]
    assert m2[Capability.MANUAL_WORKFLOW] and m2[Capability.APPROVE_AND_EXECUTE] and m2[Capability.AGENT_RUNS]


def test_kill_levels_set_a_mode_floor() -> None:
    assert floor_for(KillLevel.K1, {}) is DegradedMode.M0
    assert floor_for(KillLevel.K2, {}) is DegradedMode.M2
    assert floor_for(KillLevel.K4, {}) is DegradedMode.M4
    llm = {"llm_down": SignalState("llm_down", active=True)}
    assert floor_for(KillLevel.K0, llm) is DegradedMode.M2
    assert floor_for(KillLevel.K3, llm) is DegradedMode.M3
    assert floor_for(KillLevel.K0, {}, DegradedMode.M1) is DegradedMode.M1


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_fault_flags_are_truthy_strings(value: str) -> None:
    assert fault_flags({"FAULT_LLM_DOWN": value}) == {"llm_down"}


def test_fault_flags_ignore_false_values_and_feed_faults() -> None:
    env = {"FAULT_LLM_DOWN": "0", "FAULT_OPA_DOWN": "", "FAULT_FEED_GAP": "oms", "FAULT_TELEMETRY_SPOOF": "1"}
    assert fault_flags(env) == {"telemetry_unverified"}


def test_flag_acts_at_once_both_ways() -> None:
    off = SignalState("llm_down")
    on = step(off, flagged=True, reading=None)
    assert on.active and on.source == "fault_flag"
    assert not step(on, flagged=False, reading=None).active


def test_probe_needs_two_failures_to_enter_and_three_successes_to_exit() -> None:
    state = SignalState("llm_down")
    down = Reading("llm_down", True, "breaker open")
    up = Reading("llm_down", False, "breaker closed")
    state = step(state, flagged=False, reading=down)
    assert not state.active
    state = step(state, flagged=False, reading=down)
    assert state.active and state.source == "probe"
    for _ in range(2):
        state = step(state, flagged=False, reading=up)
        assert state.active
    state = step(state, flagged=False, reading=down)
    assert state.active and state.ok_streak == 0
    for _ in range(3):
        state = step(state, flagged=False, reading=up)
    assert not state.active


def test_flagged_signal_still_failing_its_probe_stays_after_the_flag_goes() -> None:
    down = Reading("llm_down", True, "unreachable")
    state = step(SignalState("llm_down"), flagged=True, reading=down)
    state = step(state, flagged=False, reading=down)
    assert state.active and state.source == "probe"


def test_evaluate_covers_every_rule_and_ignores_unknown_readings() -> None:
    out = evaluate({}, frozenset({"opa_down"}), [Reading("nonsense", True, "x")])
    assert set(out) == {r.signal for r in levels.SIGNAL_RULES}
    assert [n for n, s in out.items() if s.active] == ["opa_down"]


def _client(status: int, body: object) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_gateway_probe_reads_breaker_and_budget() -> None:
    ok = GatewayProbe("http://gw", _client(200, {"breaker": {"state": "closed"}, "budget": {"level": "ok"}}))
    assert [r.failing for r in ok.read()] == [False, False]
    half = GatewayProbe(
        "http://gw", _client(200, {"breaker": {"state": "half_open"}, "budget": {"level": "ok"}})
    )
    assert [r.failing for r in half.read()] == [False, True]
    opened = GatewayProbe(
        "http://gw", _client(200, {"breaker": {"state": "open"}, "budget": {"level": "ok"}})
    )
    assert [r.failing for r in opened.read()] == [True, True]
    broken = GatewayProbe("http://gw", _client(503, {}))
    assert all(r.failing for r in broken.read())


def test_unreachable_services_read_as_down() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(refuse))
    assert all(r.failing for r in GatewayProbe("http://gw", client).read())
    assert [r.failing for r in OpaProbe("http://opa", client).read()] == [True]
    assert [r.failing for r in OpaProbe("http://opa", _client(200, {})).read()] == [False]


def test_reconciler_starts_only_when_something_can_raise_a_signal() -> None:
    assert not enabled({})
    assert not enabled({"FAULT_FEED_GAP": "oms"})
    assert enabled({"FAULT_LLM_DOWN": "0"})
    assert enabled({"SGW_OPS_GATEWAY_URL": "http://127.0.0.1:8100"})
    assert [p.name for p in configured_probes({"SGW_OPS_OPA_URL": "http://o"})] == ["opa"]
