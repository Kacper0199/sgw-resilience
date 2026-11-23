from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sgw.models.ranking.ce import (
    ImpactInput,
    QueueEntry,
    RankPolicy,
    expected_impact,
    rank_by_impact,
    rank_changes,
    rank_queue,
)
from sgw.models.ranking.params import critical_weights, equity_weight

ENABLED = RankPolicy(equity_weight=0.5)
T0 = datetime(2024, 9, 26, 12, tzinfo=UTC)

items = st.builds(
    ImpactInput,
    entity_id=st.text(alphabet="ABCDEFGHJK", min_size=3, max_size=6),
    p_loss=st.floats(min_value=0, max_value=1),
    customers=st.integers(min_value=0, max_value=50_000),
    duration_share=st.floats(min_value=0, max_value=1),
    critical_facilities=st.lists(st.sampled_from(["hospital", "shelter", "dialysis"]), max_size=3),
    residential_customers=st.just(0),
    svi_percentile=st.none() | st.floats(min_value=0, max_value=1),
)


def test_defaults_come_from_numbers_yaml() -> None:
    assert equity_weight() == 0
    assert critical_weights()["hospital"] == 2000
    assert RankPolicy.default() == RankPolicy(equity_weight=0.0, critical_weights_enabled=True)


def test_golden_breakdown() -> None:
    zone = ImpactInput(
        "WZ-PS17-CEDARFALL",
        p_loss=0.45,
        customers=6200,
        duration_share=0.5,
        critical_facilities=("hospital", "dialysis"),
        residential_customers=5400,
        svi_percentile=0.8,
    )
    off = expected_impact(zone, RankPolicy.default())
    assert (off.customers_ce, off.critical_ce, off.equity_ce) == (6200, 2500, 0)
    assert off.expected_impact == pytest.approx(0.45 * 8700 * 0.5)
    on = expected_impact(zone, ENABLED)
    assert on.equity_ce == pytest.approx(5400 * 0.5 * 0.8)
    assert on.expected_impact == pytest.approx(0.45 * (8700 + 2160) * 0.5)
    no_crit = expected_impact(zone, RankPolicy(critical_weights_enabled=False))
    assert no_crit.critical_ce == 0 and no_crit.critical_detail == {}


@st.composite
def portfolios(draw: st.DrawFn) -> list[ImpactInput]:
    n = draw(st.integers(min_value=2, max_value=12))
    out = []
    for i in range(n):
        customers = draw(st.integers(min_value=0, max_value=40_000))
        out.append(
            ImpactInput(
                f"AST-{i:02d}",
                p_loss=draw(st.floats(min_value=0, max_value=1)),
                customers=customers,
                duration_share=draw(st.floats(min_value=0.05, max_value=1)),
                critical_facilities=tuple(
                    draw(st.lists(st.sampled_from(["hospital", "shelter"]), max_size=2))
                ),
                residential_customers=draw(st.integers(min_value=0, max_value=customers)),
                svi_percentile=draw(st.floats(min_value=0, max_value=1)),
            )
        )
    return out


@given(portfolios(), st.randoms(use_true_random=False))
@settings(max_examples=150)
def test_equity_zero_ignores_svi_entirely(items_: list[ImpactInput], rnd) -> None:  # type: ignore[no-untyped-def]
    policy = RankPolicy.default()
    base = [b.entity_id for b in rank_by_impact([expected_impact(i, policy) for i in items_])]
    svis = [i.svi_percentile for i in items_]
    rnd.shuffle(svis)
    permuted = [
        ImpactInput(
            i.entity_id,
            i.p_loss,
            i.customers,
            i.duration_share,
            i.critical_facilities,
            i.residential_customers,
            s,
        )
        for i, s in zip(items_, svis, strict=True)
    ]
    again = [expected_impact(i, policy) for i in permuted]
    assert [b.entity_id for b in rank_by_impact(again)] == base
    assert all(b.equity_ce == 0 for b in again)


@given(portfolios())
@settings(max_examples=150)
def test_enabling_equity_never_lowers_impact(items_: list[ImpactInput]) -> None:
    for i in items_:
        assert expected_impact(i, ENABLED).expected_impact >= expected_impact(i, RankPolicy()).expected_impact


def test_equity_option_changes_rank_only_when_enabled() -> None:
    affluent = ImpactInput("FDR-AIK-2211", 0.5, 10_000, 1.0, (), 9_000, 0.05)
    vulnerable = ImpactInput("FDR-AIK-2219", 0.5, 8_000, 1.0, (), 7_800, 0.95)
    off = [
        b.entity_id
        for b in rank_by_impact([expected_impact(x, RankPolicy()) for x in (affluent, vulnerable)])
    ]
    on = [b.entity_id for b in rank_by_impact([expected_impact(x, ENABLED) for x in (affluent, vulnerable)])]
    assert off == ["FDR-AIK-2211", "FDR-AIK-2219"]
    assert on == ["FDR-AIK-2219", "FDR-AIK-2211"]
    assert rank_changes(off, on) == {"FDR-AIK-2219": 1, "FDR-AIK-2211": -1}


@given(st.lists(items, min_size=1, max_size=8, unique_by=lambda i: i.entity_id))
def test_impact_monotone_in_probability_and_bounded(xs: list[ImpactInput]) -> None:
    for x in xs:
        b = expected_impact(x, RankPolicy.default())
        assert 0 <= b.expected_impact <= b.customers_ce + b.critical_ce + b.equity_ce + 1e-9
        higher = ImpactInput(
            x.entity_id,
            min(1.0, x.p_loss + 0.1),
            x.customers,
            x.duration_share,
            x.critical_facilities,
            x.residential_customers,
            x.svi_percentile,
        )
        assert expected_impact(higher, RankPolicy.default()).expected_impact >= b.expected_impact


def test_queue_orders_by_decide_by_then_impact() -> None:
    small = expected_impact(ImpactInput("A", 0.2, 100), RankPolicy())
    big = expected_impact(ImpactInput("B", 0.9, 9000), RankPolicy())
    entries = [
        QueueEntry("DC-LATE-BIG", T0 + timedelta(hours=2), big),
        QueueEntry("DC-EARLY-SMALL", T0, small),
        QueueEntry("DC-EARLY-BIG", T0, big),
    ]
    assert [e.case_id for e in rank_queue(entries)] == ["DC-EARLY-BIG", "DC-EARLY-SMALL", "DC-LATE-BIG"]


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        ImpactInput("x", 1.2, 10)
    with pytest.raises(ValueError):
        ImpactInput("x", 0.5, 10, residential_customers=11)
    with pytest.raises(ValueError):
        RankPolicy(equity_weight=2)
    with pytest.raises(KeyError):
        expected_impact(ImpactInput("x", 0.5, 10, critical_facilities=("casino",)), RankPolicy())
