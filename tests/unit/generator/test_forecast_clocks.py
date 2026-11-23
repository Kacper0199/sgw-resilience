"""Advisories, the forecast error model, and the PS-17 hinge as a consequence of the forecast change."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from sgw.contracts.clocks import DecisionCase
from sgw.contracts.golden import ADVISORY_N, ADVISORY_N1
from sgw.generator import clocks as ck
from sgw.generator.config import Family
from sgw.generator.ensemble import run_ensembles
from sgw.generator.forecast import _sigma_km, advisories, forecast_track, lead_grid
from sgw.generator.scenario import GenerationResult
from sgw.generator.truth import Truth


def test_advisory_schedule_matches_the_micro_fixture(scenario: dict) -> None:
    advs = {a.label: a for a in advisories(scenario)}
    assert advs["N"].issued == ADVISORY_N.issued and advs["N+1"].issued == ADVISORY_N1.issued
    assert advs["N"].forecast_id == "ADV-HELENE-SYN-N" and advs["N+1"].forecast_id == "ADV-HELENE-SYN-NP1"
    assert advs["N-1"].forecast_id == "ADV-HELENE-SYN-N-1"
    assert advs["N"].next_issued == advs["N+1"].issued


def test_cone_sigma_puts_two_thirds_of_errors_inside_the_cone(fam_a: Family) -> None:
    lead = np.array([24.0, 48.0, 72.0])
    sigma = _sigma_km(lead, fam_a)
    radius = np.interp(lead, fam_a.arr("forecast.cone_lead_h"), fam_a.arr("forecast.cone_radius_nmi")) * 1.852
    z = np.random.default_rng(11).standard_normal((2, 200_000))
    inside = [np.mean(np.hypot(*(z * s)) <= r) for s, r in zip(sigma, radius, strict=True)]
    assert inside == pytest.approx([2 / 3] * 3, abs=0.005)


def test_zero_error_forecast_reproduces_the_truth_track(truth: Truth, scenario: dict, fam_a: Family) -> None:
    adv = advisories(scenario)[0]
    lead = lead_grid(fam_a)
    zero = {k: np.zeros(len(lead)) for k in ("along_z", "cross_z", "intensity_z")}
    fc = forecast_track(truth.track, adv.issued, fam_a, zero, lead)
    st = truth.track.at(fc.t)
    assert (
        np.allclose(fc.lat, st["lat"]) and np.allclose(fc.lon, st["lon"]) and np.allclose(fc.vmax, st["vmax"])
    )


def test_hinge_decide_by_moves_earlier_from_n_to_n1(generated: GenerationResult) -> None:
    hinge = next(c for c in generated.truth_table["seeded_cases"] if c["id"] == "HINGE-PS17-N-N1")["outcome"]
    assert hinge["shift_min"] < 0
    assert hinge["decide_by_N1_utc"] < hinge["decide_by_N_utc"]
    assert hinge["verdict"] == ["wait_for_next_advisory", "act_now"]
    assert hinge["ps17_p_loss_ppm"][1] > hinge["ps17_p_loss_ppm"][0]


def test_hinge_comes_from_the_forecast_change_not_from_a_constant(truth: Truth, fam_a: Family) -> None:
    """Counterfactual: give advisory N the same official error as N+1; the shift must collapse."""
    sc = copy.deepcopy(truth.scenario)
    sc["advisories"]["official_error_overrides"]["N"] = dict(
        sc["advisories"]["official_error_overrides"]["N+1"]
    )
    cf = copy.copy(truth)
    cf.scenario = sc
    pts, ens = run_ensembles(cf)
    clocks = {
        e.advisory.label: ck.advisory_clocks(e, pts, fam_a) for e in ens if e.advisory.label in ("N", "N+1")
    }
    pts0, ens0 = run_ensembles(truth)
    base = {
        e.advisory.label: ck.advisory_clocks(e, pts0, fam_a) for e in ens0 if e.advisory.label in ("N", "N+1")
    }
    seeded_shift = ck.shift_minutes(base["N"], base["N+1"])
    counterfactual_shift = ck.shift_minutes(clocks["N"], clocks["N+1"])
    assert abs(counterfactual_shift) < abs(seeded_shift) / 2


def test_reference_clocks_satisfy_the_k16_contract(generated: GenerationResult) -> None:
    for label, adv in generated.truth_table["clocks_by_advisory"].items():
        for cid, case in adv["cases"].items():
            parsed = DecisionCase.model_validate(case)
            assert parsed.decision_case_id == cid, label
            assert parsed.effective_decide_by_utc <= parsed.clock.decide_by_utc


def test_critical_path_chain_binds_upstream_cases(generated: GenerationResult) -> None:
    n1 = generated.truth_table["clocks_by_advisory"]["N+1"]
    assert n1["bound_by"][ck.CASE_FUEL] == ck.CASE_POWER
    assert n1["bound_by"][ck.CASE_CREWS] == ck.CASE_POWER
    assert n1["bound_by"][ck.CASE_POWER] == ck.CASE_PRESSURE
    edges = generated.truth_table["critical_path"]["edges"]
    assert [ck.CASE_FUEL, ck.CASE_POWER] in edges and [ck.CASE_PRESSURE, ck.CASE_HOSPITAL] in edges
    assert all(n1["cases"][c]["on_critical_path"] for c in (ck.CASE_FUEL, ck.CASE_POWER, ck.CASE_PRESSURE))
