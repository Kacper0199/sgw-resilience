"""Network construction, fragility derivations and the restoration scheduler."""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
import pytest
from scipy.stats import norm

from sgw.common import numbers as numbers_mod
from sgw.generator.config import Family, load_counties
from sgw.generator.network import age_ratio, build_network, cascade_factor, modifier_norm
from sgw.generator.restoration import median_t50
from sgw.generator.truth import Truth


def test_customers_are_conserved_per_county_and_in_total(truth: Truth) -> None:
    customers = np.asarray(truth.net.sections["customers"])
    fips = np.asarray(truth.net.sections["fips"])
    for c in load_counties():
        assert customers[fips == c.fips].sum() == c.customers
    assert customers.sum() == numbers_mod.value("electric_customers_total")


def test_named_assets_carry_the_micro_fixture_ids(truth: Truth) -> None:
    idx = truth.net.section_index()
    j = idx["FDR-AIK-2207-S1"]
    assert truth.net.sections["device"][j] == "BRK-FDR-AIK-2207"
    assert "PS-17" in truth.net.sections["critical"][j]
    feeders = dict(zip(truth.net.feeders["id"], truth.net.feeders["customers"], strict=True))
    assert feeders["FDR-AIK-2207"] == 1840 and feeders["FDR-AIK-2219"] == 3960
    assert {"STG-AIK-SANDHILL-YARD", "STG-RCH-MILLPOND-YARD"} <= {y["id"] for y in truth.net.yards}
    crews = {c.id for c in truth.crews}
    assert {"CRW-OSPREY-04", "CRW-OSPREY-07", "CRW-KESTREL-02", "CRW-MA-TALON-11"} <= crews


def test_cascade_factor_reproduces_the_county_curve_by_monte_carlo(fam_a: Family) -> None:
    beta = fam_a.f("fragility.beta")
    k = cascade_factor(fam_a)
    n = int(fam_a["network.sections_per_feeder"])
    r = np.random.default_rng(7)
    cap = k * np.exp(beta * r.standard_normal((200_000, n)))
    out_trunk = cap[:, 0] <= 1.0
    out = np.column_stack([out_trunk, out_trunk[:, None] | (cap[:, 1:] <= 1.0)])
    assert out.mean() == pytest.approx(0.5, abs=0.005)


def test_age_and_vegetation_modifiers_keep_the_population_median(fam_a: Family) -> None:
    lo, hi = fam_a["network.pole_age_range_years"]
    va, vb = fam_a["network.veg_beta_ab"]
    r = np.random.default_rng(3)
    age = r.uniform(lo, hi, 400_000)
    veg = r.beta(va, vb, 400_000)
    mod = age_ratio(age, fam_a) * (1.0 - fam_a.f("fragility.veg_median_reduction") * veg)
    assert mod.mean() / modifier_norm(fam_a) == pytest.approx(1.0, abs=0.003)


def test_network_build_is_deterministic(scenario: dict, fam_a: Family) -> None:
    a = build_network(load_counties(), fam_a, scenario, 61017)
    b = build_network(load_counties(), fam_a, scenario, 61017)
    assert np.array_equal(a.sections["capacity"], b.sections["capacity"])
    c = build_network(load_counties(), fam_a, scenario, 61018)
    assert not np.array_equal(a.sections["capacity"], c.sections["capacity"])


def test_capacities_respect_floor_and_pins(truth: Truth, fam_a: Family, scenario: dict) -> None:
    cap = np.asarray(truth.net.sections["capacity"])
    assert cap.min() >= fam_a.f("fragility.capacity_floor_gust_ms")
    idx = truth.net.section_index()
    for case in scenario["seeded"]:
        pin = case.get("pin")
        if isinstance(pin, dict) and "capacity_quantile" in pin:
            assert truth.net.sections["quantile"][idx[pin["section"]]] == pin["capacity_quantile"]


def test_causality_no_restore_before_fault_or_safe_work(truth: Truth) -> None:
    failed = ~np.isnan(truth.fault_t)
    assert not np.isnan(truth.restored_t[failed]).any()
    assert np.all(truth.restored_t[failed] > truth.fault_t[failed])
    assert np.all(truth.restored_t[failed] >= truth.work_ok[failed])
    assert np.isnan(truth.restored_t[~failed]).all()
    assert np.all(truth.effective_restore_t[failed] >= truth.restored_t[failed])


def test_a_crew_works_one_job_at_a_time(truth: Truth) -> None:
    by_crew = defaultdict(list)
    for a in truth.assignments:
        assert a.assigned <= a.arrive <= a.start < a.end
        by_crew[a.crew].append(a)
    for jobs in by_crew.values():
        jobs.sort(key=lambda a: a.assigned)
        for prev, nxt in zip(jobs, jobs[1:], strict=False):
            assert nxt.assigned >= prev.end


def test_mutual_aid_arrives_after_the_request(truth: Truth, scenario: dict) -> None:
    from sgw.generator.config import parse_utc
    from sgw.generator.wind import epoch

    request = epoch(parse_utc(scenario["detail"]["mutual_aid_request_utc"]))
    assert all(c.available_utc > request for c in truth.crews if c.mutual_aid)


def test_damage_never_improves_without_repair(truth: Truth) -> None:
    assert np.all(truth.ds[np.isnan(truth.fault_t)] == 0)
    assert np.all(truth.ds[~np.isnan(truth.fault_t)] >= 1)


def test_downstream_customers_are_out_while_the_trunk_is_out(truth: Truth) -> None:
    idx = truth.net.section_index()
    trunk = idx["FDR-AIK-2207-S1"]
    k = int(np.argmax(truth.times >= truth.fault_t[trunk] + 1800))
    for s in ("FDR-AIK-2207-S2", "FDR-AIK-2207-S3", "FDR-AIK-2207-S4"):
        assert truth.out[k, idx[s]]


def test_restoration_t50_is_in_the_acceptance_band(truth: Truth) -> None:
    t50 = median_t50(truth.county)
    assert 25.0 <= t50 <= 50.0
    assert t50 == pytest.approx(numbers_mod.value("helene_restoration_t50_hours"), abs=1.0)


def test_failures_follow_the_fragility_curve(truth: Truth, fam_a: Family) -> None:
    gust = truth.section_gust_peak
    theta = np.asarray(truth.net.sections["theta"])
    p = norm.cdf(np.log(gust / theta) / fam_a.f("fragility.beta"))
    failed = ~np.isnan(truth.fault_t)
    expected, observed = p.sum(), failed.sum()
    assert abs(observed - expected) < 4.0 * math.sqrt(expected) + 0.03 * expected
