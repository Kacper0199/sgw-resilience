"""Per-advisory risk picture for a replay scenario: county outage fans, asset risk with drivers, and the
no-regret share per action, all computed from the A1 hazard ensemble members.

County forecast: the A2 serving model (trained without the replayed storm) runs once per member; the members'
conformal fans are mixed (average of the members' piecewise-linear CDFs through the 7 fan points) and the
mixture is read at the fan levels, so the fan carries both hazard spread and model error.
County risk p = P(peak fraction out >= `COUNTY_EVENT_FRAC`) under that mixture.

Asset risk: P(section fails) averaged over members, with the generator's capacity law at the forecaster's
known median (`theta_known_ms`) and the total dispersion (fragility beta with county and feeder effects);
never the hidden realised capacity. Drivers: the exact additive split of the probit argument into a hazard
term ln(gust / fleet median) / beta and an asset term ln(fleet median / theta) / beta, plus the top TreeSHAP
drivers of the county outage model for the asset's county.

No-regret share per action = fraction of ensemble members in which the action is needed, each with its
rule: PS-17 chain actions are needed when the member's P(PS-17 power loss) reaches the family's
`clocks.no_regret_member_p_loss` (the WP-06 reference rule). Crew staging has no share here: no sourced,
capacity-tied staging threshold exists yet, and reusing the T2 small-staging limit would make the share 1.0
by construction (review fix). Every distribution uses the 40 ensemble members; the official forecast
(member 0) is excluded everywhere. County drivers are TreeSHAP contributions averaged over the members.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from functools import cache
from typing import Any

import numpy as np
import pandas as pd

from sgw.contracts.base import ppm_from_fraction
from sgw.contracts.vocab import risk_band_for
from sgw.generator.config import load_counties
from sgw.generator.ensemble import loss_probability
from sgw.models.hazard.ensemble import FIXTURES, MemberHazard, advisory_members, scenario_hazard
from sgw.models.outage.backtest import ARTEFACT_DIR, SERVING_MODEL
from sgw.models.outage.dataset import with_exposure
from sgw.models.outage.model import OutageModel, load

COUNTY_EVENT_FRAC = 0.10
FAN_LEVELS: tuple[float, ...] = (0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975)
GRID = np.linspace(0.0, 1.0, 2001)
TOP_ASSETS = 500
TOP_EVENT_ENTITIES = 25
PS17_FEEDER = "FDR-AIK-2207"
ENGINE_VERSION = "a1a2-risk-1.0"


@dataclass(frozen=True)
class ActionShare:
    action_id: str
    decision_case_ids: tuple[str, ...]
    share_ppm: int
    members_needed: int
    members: int
    rule: str


@dataclass
class AdvisoryRisk:
    scenario: str
    advisory_label: str
    forecast_id: str
    issued_utc: str
    next_advisory_utc: str | None
    counties: pd.DataFrame
    assets: pd.DataFrame
    actions: list[ActionShare]
    model_name: str
    meta: dict[str, Any] = field(default_factory=dict)


@cache
def serving_model(name: str = SERVING_MODEL) -> OutageModel:
    return load(ARTEFACT_DIR / name)


@cache
def sections(scenario: str) -> pd.DataFrame:
    with (FIXTURES / scenario / "sections.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    frame = pd.DataFrame(
        {
            "section_id": [r["section_id"] for r in rows],
            "feeder_id": [r["feeder_id"] for r in rows],
            "fips": [r["fips"] for r in rows],
            "customers": [int(r["customers"]) for r in rows],
            "theta_known_ms": [float(r["theta_known_ms"]) for r in rows],
            "critical_ids": [r["critical_ids"] for r in rows],
        }
    )
    return frame


def _member_cdf(points: np.ndarray) -> np.ndarray:
    """Piecewise-linear CDF on GRID through (fan value, level), 0 below the lowest and 1 above the highest."""
    xs = np.maximum.accumulate(points) + np.arange(len(points)) * 1e-9
    return np.interp(GRID, xs, np.asarray(FAN_LEVELS), left=0.0, right=1.0)


def _fan_points(fc: Any, i: int) -> np.ndarray:
    lo95, hi95 = fc.intervals["95"]
    lo80, hi80 = fc.intervals["80"]
    lo50, hi50 = fc.intervals["50"]
    return np.array([lo95[i], lo80[i], lo50[i], fc.p50[i], hi50[i], hi80[i], hi95[i]])


def county_forecast(members: tuple[MemberHazard, ...], model: OutageModel) -> pd.DataFrame:
    is_county = _county_mask(members[0])
    counties = load_counties()
    customers = pd.Series([c.customers for c in counties], dtype=float)
    ensemble = ensemble_members(members)
    cdfs = np.zeros((len(counties), len(GRID)))
    means = np.zeros(len(counties))
    shap_sum: pd.DataFrame | None = None
    for mh in ensemble:
        feats = mh.features[is_county].reset_index(drop=True)
        x = with_exposure(feats, customers)
        fc = model.predict(x)
        means += fc.mean
        for i in range(len(counties)):
            cdfs[i] += _member_cdf(_fan_points(fc, i))
        contrib = model.shap(x)
        shap_sum = contrib if shap_sum is None else shap_sum + contrib
    cdfs /= len(ensemble)
    means /= len(ensemble)
    assert shap_sum is not None
    shap_sum = shap_sum / len(ensemble)
    out = pd.DataFrame(
        {"fips": [c.fips for c in counties], "name": [c.name for c in counties], "customers": customers}
    )
    for level in FAN_LEVELS:
        frac = np.array([GRID[min(np.searchsorted(c, level, side="left"), len(GRID) - 1)] for c in cdfs])
        out[f"q{int(round(level * 1000)):04d}_out"] = np.round(frac * customers).astype(int)
    out["mean_out"] = np.round(means * customers).astype(int)
    event_idx = np.searchsorted(GRID, COUNTY_EVENT_FRAC)
    p_event = np.clip(1.0 - cdfs[:, event_idx - 1], 0.0, 1.0)
    out["p_ppm"] = [ppm_from_fraction(float(p)) for p in p_event]
    out["band"] = [risk_band_for(int(p)).value for p in out["p_ppm"]]
    out["drivers"] = [_top_drivers(shap_sum.iloc[i]) for i in range(len(counties))]
    return out


def _top_drivers(row: pd.Series, k: int = 3) -> list[dict[str, float | str]]:
    top = row.abs().sort_values(ascending=False).index[:k]
    return [{"feature": str(f), "shap_log": round(float(row[f]), 4)} for f in top]


def beta_total(name: str) -> float:
    fam = scenario_hazard(name).family
    return float(
        np.sqrt(
            fam.f("fragility.beta") ** 2
            + fam.f("fragility.county_effect_sigma") ** 2
            + fam.f("fragility.feeder_effect_sigma") ** 2
        )
    )


def member_gust_matrix(members: tuple[MemberHazard, ...]) -> tuple[list[str], np.ndarray]:
    ids = list(members[0].features["point_id"])
    gust = np.stack([m.features["peak_gust_ms"].to_numpy() for m in ensemble_members(members)])
    return ids, gust


def asset_risk(name: str, members: tuple[MemberHazard, ...], counties: pd.DataFrame) -> pd.DataFrame:
    hz = scenario_hazard(name)
    sec = sections(name)
    ids, gust = member_gust_matrix(members)
    col = {pid: j for j, pid in enumerate(ids)}
    point = [col.get(fid, col[fips]) for fid, fips in zip(sec["feeder_id"], sec["fips"], strict=True)]
    g = gust[:, point]
    beta = beta_total(name)
    floor = hz.family.f("fragility.capacity_floor_gust_ms")
    theta = sec["theta_known_ms"].to_numpy()
    p = loss_probability(g, theta[None, :], beta, floor).mean(axis=0)
    fleet = hz.family.f("fragility.median_gust_ms")
    hazard_z = np.log(np.maximum(g, 1e-6) / fleet).mean(axis=0) / beta
    asset_z = np.log(fleet / theta) / beta
    out = sec[["section_id", "feeder_id", "fips", "customers", "critical_ids"]].copy()
    out["p_ppm"] = [ppm_from_fraction(float(min(max(v, 0.0), 1.0))) for v in p]
    out["band"] = [risk_band_for(int(v)).value for v in out["p_ppm"]]
    out["expected_impact"] = np.round(p * out["customers"].to_numpy()).astype(int)
    out["gust_p50_ms"] = np.round(np.median(g, axis=0), 1)
    out["hazard_z"] = np.round(hazard_z, 3)
    out["asset_z"] = np.round(asset_z, 3)
    drivers = dict(zip(counties["fips"], counties["drivers"], strict=True))
    out["county_drivers"] = [drivers.get(f, []) for f in out["fips"]]
    return out.sort_values(["expected_impact", "p_ppm", "section_id"], ascending=[False, False, True])


def action_shares(
    name: str, label: str, members: tuple[MemberHazard, ...], model: OutageModel
) -> list[ActionShare]:
    fam = scenario_hazard(name).family
    ens = ensemble_members(members)
    sec = sections(name)
    theta = float(sec.loc[sec["section_id"] == f"{PS17_FEEDER}-S1", "theta_known_ms"].iloc[0])
    j = list(ens[0].features["point_id"]).index(PS17_FEEDER)
    gust = np.array([m.forecast_peak_gust[j] for m in ens])
    p_loss = loss_probability(gust, theta, beta_total(name), fam.f("fragility.capacity_floor_gust_ms"))
    threshold = fam.f("clocks.no_regret_member_p_loss")
    ps_needed = p_loss >= threshold
    ps_rule = f"member P(PS-17 power loss) >= {threshold:g} (clocks.no_regret_member_p_loss)"

    def share(action: str, case: str, needed: np.ndarray, rule: str) -> ActionShare:
        return ActionShare(
            action, (case,), ppm_from_fraction(float(needed.mean())), int(needed.sum()), len(needed), rule
        )

    del label
    return [
        share("ACT-PS17-GENERATOR-HOOKUP", "DC-D3-PS17-POWER", ps_needed, ps_rule),
        share("ACT-PS17-FUEL-TRUCK", "DC-D3-PS17-FUEL", ps_needed, ps_rule),
        share("ACT-PS17-PRESSURE-HOLD", "DC-D3-PS17-PRESSURE", ps_needed, ps_rule),
        share("ACT-HSP-TALLOWBRANCH-TANKER", "DC-D3-HSP-TALLOWBRANCH-WATER", ps_needed, ps_rule),
    ]


def ensemble_members(members: tuple[MemberHazard, ...]) -> tuple[MemberHazard, ...]:
    """The ensemble without the official forecast (member 0): every distribution, share and driver average
    in this module uses exactly these members, as WP-06's reference clocks do."""
    return tuple(m for m in members if m.member != 0)


def _county_mask(m: MemberHazard) -> np.ndarray:
    return np.asarray(m.features["point_id"].str.fullmatch(r"\d{5}").to_numpy(), dtype=bool)


@cache
def advisory_risk(name: str, label: str, model_name: str = SERVING_MODEL) -> AdvisoryRisk:
    hz = scenario_hazard(name)
    adv = hz.advisory(label)
    model = serving_model(model_name)
    if name in model.trained_on:
        raise ValueError(f"serving model {model_name} was trained on {name}: it would know the outcome")
    members = advisory_members(name, label)
    counties = county_forecast(members, model)
    assets = asset_risk(name, members, counties)
    return AdvisoryRisk(
        scenario=name,
        advisory_label=label,
        forecast_id=adv.forecast_id,
        issued_utc=adv.issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
        next_advisory_utc=adv.next_issued.strftime("%Y-%m-%dT%H:%M:%SZ") if adv.next_issued else None,
        counties=counties,
        assets=assets,
        actions=action_shares(name, label, members, model),
        model_name=model_name,
        meta={"members": len(members) - 1, "trained_on": model.trained_on, "engine_version": ENGINE_VERSION},
    )
