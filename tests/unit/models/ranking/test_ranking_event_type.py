from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sgw.models.ranking.event_type import classify, footprint_customers, recommend

TOTAL = 4_248_290


def test_dc31_sanity_checks() -> None:
    assert footprint_customers() == TOTAL
    assert classify(2_230_592 / TOTAL)[0] == 1
    assert classify(412_885 / TOTAL)[0] == 2
    assert classify(249_387 / TOTAL)[0] == 2
    assert classify(0.004)[0] == 5
    assert classify(0.004, t90_h=30) == (3, "time to 90% restored")


def test_helene_scale_forecast_recommends_type_1_with_helene_first() -> None:
    rec = recommend(peak_customers_out_p50=1_900_000, peak_customers_out_p90=2_600_000, t90_h_p50=96)
    assert (rec.recommended_type, rec.recommended_name, rec.escalation_type) == (1, "Catastrophic", 1)
    assert [a.storm for a in rec.analogs] == ["Helene", "Michael", "Ian"]
    assert rec.analogs[0].implied_type == 1


def test_mixed_basis_analogs_have_no_implied_type_and_own_storm_is_excluded() -> None:
    rec = recommend(
        peak_customers_out_p50=1_900_000, peak_customers_out_p90=2_600_000, scenario_storm="Helene"
    )
    assert [a.storm for a in rec.analogs] == ["Michael", "Ian"]
    assert all(a.implied_type is None and a.basis == "sc_ga_statewide" for a in rec.analogs)
    ratio = 2_230_592 / 2_467_790
    assert rec.analogs[0].footprint_equivalent_share == pytest.approx(412_885 * ratio / TOTAL)


def test_escalation_reported_from_p90() -> None:
    rec = recommend(peak_customers_out_p50=300_000, peak_customers_out_p90=900_000)
    assert rec.recommended_type == 2 and rec.escalation_type == 1
    assert rec.analogs[0].storm == "Michael" and rec.analogs[0].implied_type is None


@given(st.floats(min_value=0, max_value=1), st.floats(min_value=0, max_value=1))
def test_type_is_monotone_in_share(a: float, b: float) -> None:
    lo, hi = sorted((a, b))
    assert classify(hi)[0] <= classify(lo)[0]


def test_bad_quantiles() -> None:
    with pytest.raises(ValueError):
        recommend(peak_customers_out_p50=10, peak_customers_out_p90=5)
