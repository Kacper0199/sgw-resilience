from __future__ import annotations

import json

import numpy as np
import pytest

from sgw.models.hazard.ensemble import FIXTURES, advisory_members
from sgw.models.outage import forecast
from sgw.models.outage.forecast import advisory_risk, sections
from sgw.models.outage.plan_diff import plan_diff


def _truth_shares() -> list[int]:
    truth = json.loads((FIXTURES / "helene" / "truth_table.json").read_text(encoding="utf-8"))
    hinge = next(c for c in truth["seeded_cases"] if c["id"] == "HINGE-PS17-N-N1")
    return list(hinge["outcome"]["no_regret_share_ppm"])


def test_ps17_no_regret_share_reproduces_the_wp06_truth_table() -> None:
    n = {a.action_id: a for a in advisory_risk("helene", "N").actions}
    n1 = {a.action_id: a for a in advisory_risk("helene", "N+1").actions}
    expected = _truth_shares()
    assert [n["ACT-PS17-GENERATOR-HOOKUP"].share_ppm, n1["ACT-PS17-GENERATOR-HOOKUP"].share_ppm] == expected
    assert n1["ACT-PS17-GENERATOR-HOOKUP"].members == 40
    assert all(a.decision_case_ids for a in n1.values())


def test_asset_risk_never_reads_the_hidden_realised_capacity() -> None:
    assert "capacity_ms" not in sections("helene").columns


def test_county_fans_are_ordered_and_bands_follow_probability() -> None:
    c = advisory_risk("helene", "N+1").counties
    q = c[[col for col in c.columns if col.startswith("q") and col.endswith("_out")]].to_numpy()
    assert (np.diff(q, axis=1) >= 0).all()
    assert c["p_ppm"].between(0, 1_000_000).all()
    assert (c.sort_values("p_ppm")["band"].iloc[-1]) in {"high", "very_high"}


def test_asset_drivers_split_the_probit_argument_exactly() -> None:
    risk = advisory_risk("helene", "N+1")
    a = risk.assets.head(50)
    assert (a["county_drivers"].map(len) == 3).all()
    assert a["expected_impact"].is_monotonic_decreasing
    members = forecast.ensemble_members(advisory_members("helene", "N+1"))
    ids = list(members[0].features["point_id"])
    gust = np.stack([m.features["peak_gust_ms"].to_numpy() for m in members])
    beta = forecast.beta_total("helene")
    sec = sections("helene").set_index("section_id")
    for row in a.itertuples():
        col = ids.index(row.feeder_id) if row.feeder_id in ids else ids.index(row.fips)
        theta = sec.loc[row.section_id, "theta_known_ms"]
        expected = float(np.mean(np.log(gust[:, col] / theta)) / beta)
        assert row.hazard_z + row.asset_z == pytest.approx(expected, abs=2e-3)


def test_shares_and_fans_use_the_ensemble_without_the_official_member() -> None:
    members = advisory_members("helene", "N+1")
    ens = forecast.ensemble_members(members)
    assert len(ens) == len(members) - 1 and all(m.member != 0 for m in ens)
    actions = advisory_risk("helene", "N+1").actions
    assert {a.members for a in actions} == {len(ens)}
    assert "ACT-CREWS-STAGE-AIK" not in {a.action_id for a in actions}


def test_plan_diff_from_n_to_n1_flags_the_ps17_act_now_crossing() -> None:
    diff = plan_diff(advisory_risk("helene", "N"), advisory_risk("helene", "N+1"))
    gen = next(a for a in diff["actions"] if a["action_id"] == "ACT-PS17-GENERATOR-HOOKUP")
    assert gen["share_ppm"] == _truth_shares()
    assert gen["crossed_act_now_threshold"] is True
    assert diff["footprint_mean_out"][1] > diff["footprint_mean_out"][0]
    assert len(diff["counties"]) == 10


def test_a_model_trained_on_the_replayed_storm_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    real = forecast.serving_model()

    class Leaky:
        trained_on = [*real.trained_on, "helene"]

    monkeypatch.setattr(forecast, "serving_model", lambda name=None: Leaky())
    with pytest.raises(ValueError, match="would know the outcome"):
        forecast.advisory_risk.__wrapped__("helene", "N", "leaky")
