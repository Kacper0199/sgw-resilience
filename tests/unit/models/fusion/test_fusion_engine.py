from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sgw.models.fusion.engine import (
    Branch,
    FusionConfig,
    FusionMode,
    Priors,
    Signal,
    coverage_ln_lr,
    fuse,
    n_eff,
    root_value,
)

LN = st.floats(min_value=-6.0, max_value=6.0, allow_nan=False, allow_infinity=False)
POS = st.floats(min_value=0.01, max_value=6.0, allow_nan=False, allow_infinity=False)
RHO = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
OSR_TREE = Priors(p_hazard=0.25, p_loss_given_hazard=0.60, p_loss_given_no_hazard=0.01)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([math.log(6)], 1.792),
        ([math.log(6), math.log(1.2)], 1.801),
        ([math.log(6), 0.0], 1.792),
        ([math.log(6), math.log(6)], 1.886),
        ([math.log(6)] * 40, 1.985),
        ([math.log(6), -math.log(6)], 0.0),
    ],
)
def test_osr_same_root_table_rho_0_9(values: list[float], expected: float) -> None:
    assert root_value(values, rho=0.9) == pytest.approx(expected, abs=5e-4)


def test_osr_split_vs_flat_golden() -> None:
    gauge = Signal("gauge-a", math.log(4))
    second = Signal("gauge-b", math.log(4))
    flat = FusionConfig(mode=FusionMode.FLAT, cap=10)
    split = FusionConfig(mode=FusionMode.SPLIT, cap=10)
    assert OSR_TREE.p_loss == pytest.approx(0.1575)
    assert fuse([gauge], OSR_TREE, flat).p_loss == pytest.approx(0.428, abs=5e-4)
    assert fuse([gauge], OSR_TREE, split).p_loss == pytest.approx(0.347, abs=5e-4)
    assert fuse([gauge, second], OSR_TREE, flat).p_loss == pytest.approx(0.749, abs=5e-4)
    assert fuse([gauge, second], OSR_TREE, split).p_loss == pytest.approx(0.507, abs=5e-4)


def test_osr_silence_golden() -> None:
    def three_of_400(reach: float) -> float:
        return coverage_ln_lr(
            fired=3, silent=397, reach=reach, p_report_if_event=0.7, p_report_if_no_event=0.002
        )

    assert three_of_400(1.0) == pytest.approx(-460, abs=1)
    assert three_of_400(0.05) == pytest.approx(3.5, abs=0.05)
    assert three_of_400(0.01) == pytest.approx(14.8, abs=0.05)


@given(st.lists(LN, max_size=12), RHO, st.randoms(use_true_random=False))
def test_order_invariance(values: list[float], rho: float, rnd) -> None:  # type: ignore[no-untyped-def]
    shuffled = values[:]
    rnd.shuffle(shuffled)
    assert root_value(values, rho) == root_value(shuffled, rho)


@given(st.lists(LN, max_size=10), POS, RHO)
def test_adding_a_supporting_signal_never_lowers_the_root(
    values: list[float], extra: float, rho: float
) -> None:
    assert root_value([*values, extra], rho) >= root_value(values, rho) - 1e-12


@given(st.lists(LN, max_size=10), RHO)
def test_neutral_signal_changes_nothing(values: list[float], rho: float) -> None:
    assert root_value([*values, 0.0], rho) == root_value(values, rho)


@given(st.lists(LN, max_size=10), RHO)
def test_sign_symmetry(values: list[float], rho: float) -> None:
    assert root_value([-v for v in values], rho) == pytest.approx(-root_value(values, rho), abs=1e-12)


@given(st.lists(POS, min_size=1, max_size=40), st.floats(min_value=0.05, max_value=1.0))
def test_root_bounded_by_strongest_over_rho(values: list[float], rho: float) -> None:
    assert root_value(values, rho) <= max(values) / rho + 1e-9


@given(st.lists(POS, min_size=1, max_size=10))
def test_rho_limits_strongest_and_sum(values: list[float]) -> None:
    assert root_value(values, 1.0) == pytest.approx(max(values))
    assert root_value(values, 0.0) == pytest.approx(math.fsum(values))


@given(st.lists(LN, max_size=20), RHO, st.floats(min_value=0.1, max_value=5.0))
def test_cap_holds(values: list[float], rho: float, cap: float) -> None:
    assert abs(root_value(values, rho, cap)) <= cap


@given(st.integers(min_value=1, max_value=50), RHO)
def test_equal_values_scale_by_n_eff(k: int, rho: float) -> None:
    assert root_value([1.5] * k, rho) == pytest.approx(1.5 * n_eff(k, rho))


@given(
    st.lists(st.tuples(st.sampled_from("abcd"), LN, st.sampled_from(list(Branch))), max_size=8),
    st.sampled_from(list(FusionMode)),
)
@settings(max_examples=60)
def test_shapley_efficiency(raw: list[tuple[str, float, Branch]], mode: FusionMode) -> None:
    signals = [Signal(r, v, b) for r, v, b in raw]
    res = fuse(signals, OSR_TREE, FusionConfig(mode=mode))
    assert math.fsum(res.shapley_pp.values()) == pytest.approx(100 * (res.p_loss - res.p_prior), abs=1e-9)


@given(st.lists(POS, min_size=1, max_size=10), st.floats(min_value=0.01, max_value=0.99))
def test_split_never_exceeds_fragility(values: list[float], p_f: float) -> None:
    priors = Priors(p_hazard=0.3, p_loss_given_hazard=p_f, p_loss_given_no_hazard=min(p_f, 0.01))
    signals = [Signal(f"r{i}", v, Branch.HAZARD) for i, v in enumerate(values)]
    assert fuse(signals, priors, FusionConfig(mode=FusionMode.SPLIT), attribution=False).p_loss <= p_f + 1e-12


@given(st.floats(min_value=0.0, max_value=1.0), st.integers(min_value=1, max_value=500))
def test_silence_never_supports_loss_when_reports_are_likelier_under_loss(reach: float, silent: int) -> None:
    rates = {"p_report_if_event": 0.7, "p_report_if_no_event": 0.002}
    assert coverage_ln_lr(fired=0, silent=silent, reach=reach, **rates) <= 0.0
    assert coverage_ln_lr(fired=0, silent=silent, reach=0.0, **rates) == 0


def test_own_action_signals_do_not_raise_risk() -> None:
    base = [Signal("advisory", 1.0)]
    ours = Signal("work-orders", 2.0, caused_by_action_id="PRP-HALYARD-0007")
    p0 = fuse(base, OSR_TREE).p_loss
    res = fuse([*base, ours], OSR_TREE)
    assert res.p_loss == p0
    assert {r.root_id: r.excluded_own_action for r in res.roots}["work-orders"] == 1


def test_canonical_sum_is_replay_stable() -> None:
    signals = [Signal(f"root-{i % 5}", (i * 0.37) % 2 - 0.9) for i in range(40)]
    a = fuse(signals, OSR_TREE)
    b = fuse(list(reversed(signals)), OSR_TREE)
    assert a.p_loss == b.p_loss
    assert a.shapley_pp == b.shapley_pp


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        Signal("x", math.inf)
    with pytest.raises(ValueError):
        Priors(0.0, 0.5, 0.5)
    with pytest.raises(ValueError):
        FusionConfig(rho=1.5)
