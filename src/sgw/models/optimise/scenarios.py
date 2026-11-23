"""SAA scenarios for crew pre-positioning, built from the WP-11 forecast and the WP-06 scenario.

One scenario = one A1 hazard ensemble member (official forecast excluded) passed through the A2 serving model
(trained without the replayed storm), times a storm-scale factor k, plus independent mutual-aid arrival draws.

Why k: the A2 hindcast (`loso_detail.json`) over-predicts the three small storms about 2x and under-predicts
Helene about 3x, so the forecast's storm total cannot be trusted in either direction. k is log-uniform over a
band symmetric in log, whose half-width is the largest |log(observed / predicted)| among the storms OTHER than
the replayed one (an operator in September 2024 knew Michael, Ian and Debby only; using Helene's own error to
plan the Helene replay would be leakage, the same rule as P-11-01). The band is not used to correct the bias:
three storms that all over-predict would push the plan down, and Helene then went the other way.

Requirement in persons per cluster = sum over its counties of min(1, k x member mean fraction out) x customers
x personnel per 1,000 outages / 1,000 (project fact base, Georgia Power Helene ratio). Delays in hours:

- yard hold: crews at a yard cannot roll while gusts there are >= 20 m/s (`wind_hold_feature`), and a blocked
  access road adds the expected debris clearance p_tree(gust) x median clearance (WP-06 access model);
- travel: great-circle distance at the WP-06 convoy speed;
- early mutual aid (requested at the advisory): max(0, issue + arrival draw - landfall);
- late mutual aid (requested when damage is seen, WP-06 `mutual_aid_request_utc`): request + arrival
  draw - landfall.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from scipy.stats import norm
from sklearn.cluster import KMeans

from sgw.common import numbers as numbers_mod
from sgw.generator.config import County, Family, load_counties, load_family, load_scenario
from sgw.models.hazard.ensemble import FIXTURES, advisory_members, scenario_hazard
from sgw.models.outage.backtest import ARTEFACT_DIR, SERVING_MODEL
from sgw.models.outage.dataset import with_exposure
from sgw.models.outage.forecast import serving_model

PARAMS_PATH = Path(__file__).with_name("saa_params.yaml")
LOSO_DETAIL = ARTEFACT_DIR / "loso_detail.json"
EARTH_KM = 6371.0


@cache
def saa_params() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))
    return data


def param(key: str) -> Any:
    entry = saa_params()["params"][key]
    if "number" in entry:
        return numbers_mod.value(str(entry["number"]))
    return entry["value"]


def family_value(fam: Family, key: str) -> float:
    return fam.f(saa_params()["family_keys"][key])


def parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def haversine_km(lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlat, dlon = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
    return np.asarray(2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0))))


@dataclass(frozen=True)
class Yard:
    yard_id: str
    fips: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Geography:
    counties: tuple[County, ...]
    cluster_of: np.ndarray
    cluster_lat: np.ndarray
    cluster_lon: np.ndarray
    cluster_customers: np.ndarray
    cluster_names: tuple[str, ...]
    yards: tuple[Yard, ...]
    travel_h: np.ndarray

    @property
    def n_clusters(self) -> int:
        return len(self.cluster_lat)


@cache
def geography(name: str = "helene", n_clusters: int | None = None) -> Geography:
    fam = load_family(str(load_scenario(name).get("family", "A")))
    counties = tuple(load_counties())
    k = int(n_clusters or param("clusters"))
    lat = np.array([c.lat for c in counties])
    lon = np.array([c.lon for c in counties])
    cust = np.array([c.customers for c in counties], dtype=float)
    xy = np.column_stack([lat, lon * math.cos(math.radians(float(lat.mean())))])
    km = KMeans(n_clusters=k, n_init=10, random_state=int(param("seed"))).fit(xy, sample_weight=cust)
    labels = np.asarray(km.labels_)
    order = np.lexsort((lon_of(labels, lon, k), -lat_of(labels, lat, k)))
    relabel = np.empty(k, dtype=int)
    relabel[order] = np.arange(k)
    labels = relabel[labels]
    c_lat = np.array([np.average(lat[labels == j], weights=cust[labels == j]) for j in range(k)])
    c_lon = np.array([np.average(lon[labels == j], weights=cust[labels == j]) for j in range(k)])
    c_cust = np.array([cust[labels == j].sum() for j in range(k)])
    names = tuple(
        f"CL-{j:02d} {counties[int(np.argmax(np.where(labels == j, cust, -1.0)))].name}" for j in range(k)
    )
    scen = load_scenario(name)
    yards = tuple(
        Yard(yid, str(v["fips"]), float(v["lat"]), float(v["lon"]))
        for yid, v in sorted(scen["named"]["yards"].items())
    )
    dist = haversine_km(
        np.array([y.lat for y in yards])[:, None],
        np.array([y.lon for y in yards])[:, None],
        c_lat[None, :],
        c_lon[None, :],
    )
    travel = dist / family_value(fam, "travel_kmh")
    return Geography(counties, labels, c_lat, c_lon, c_cust, names, yards, travel)


def lat_of(labels: np.ndarray, lat: np.ndarray, k: int) -> np.ndarray:
    return np.array([lat[labels == j].mean() for j in range(k)])


def lon_of(labels: np.ndarray, lon: np.ndarray, k: int) -> np.ndarray:
    return np.array([lon[labels == j].mean() for j in range(k)])


@dataclass(frozen=True)
class MemberInputs:
    """Per ensemble member: county mean fraction out, and the yard hold hours (wind + expected debris)."""

    members: tuple[int, ...]
    county_frac: np.ndarray
    yard_hold_h: np.ndarray


@cache
def member_inputs(name: str, advisory: str, model_name: str = SERVING_MODEL) -> MemberInputs:
    hz = scenario_hazard(name)
    fam = hz.family
    model = serving_model(model_name)
    if name in model.trained_on:
        raise ValueError(f"serving model {model_name} was trained on {name}: it would know the outcome")
    geo = geography(name)
    customers = np.array([c.customers for c in geo.counties], dtype=float)
    fips = [c.fips for c in geo.counties]
    cust_series = pd.Series(customers)
    soil = float(hz.scenario["antecedent_soil_multiplier"]["value"])
    tree_median = family_value(fam, "access_tree_median_gust_ms") * soil
    tree_beta = family_value(fam, "access_tree_beta")
    clearance = family_value(fam, "access_clearance_median_h")
    hold_col = str(param("wind_hold_feature"))
    ids: list[int] = []
    fracs: list[np.ndarray] = []
    holds: list[np.ndarray] = []
    for mh in advisory_members(name, advisory):
        if mh.member == 0:
            continue
        feats = mh.features.set_index("point_id")
        county_feats = feats.loc[fips].reset_index()
        fc = model.predict(with_exposure(county_feats, cust_series))
        fracs.append(np.clip(np.asarray(fc.mean, dtype=float), 0.0, 1.0))
        yard_feats = feats.loc[[y.fips for y in geo.yards]]
        gust = yard_feats["peak_gust_ms"].to_numpy(dtype=float)
        p_tree = norm.cdf(np.log(np.maximum(gust, 1e-6) / tree_median) / tree_beta)
        holds.append(yard_feats[hold_col].to_numpy(dtype=float) + p_tree * clearance)
        ids.append(mh.member)
    return MemberInputs(tuple(ids), np.stack(fracs), np.stack(holds))


def scale_band(replayed: str, path: Path = LOSO_DETAIL) -> tuple[float, float, dict[str, float]]:
    detail = json.loads(path.read_text(encoding="utf-8"))
    ratios = {
        s["storm"]: s["observed_total_out"] / s["model"]["predicted_total_out"]
        for s in detail["storms"]
        if s["storm"] != replayed
    }
    half = max(abs(math.log(r)) for r in ratios.values())
    return math.exp(-half), math.exp(half), ratios


def observed_ratio(storm: str, path: Path = LOSO_DETAIL) -> float:
    detail = json.loads(path.read_text(encoding="utf-8"))
    s = next(s for s in detail["storms"] if s["storm"] == storm)
    return float(s["observed_total_out"] / s["model"]["predicted_total_out"])


@dataclass(frozen=True)
class ScenarioSet:
    """Arrays for the MILP. need: (S, C) persons; hold: (S, D) h. Times in hours after landfall:
    early_arrival (signed: negative = before landfall), late_delay (first-wave post-landfall aid),
    overflow_delay (aid beyond the first wave, one arrival time later)."""

    need: np.ndarray
    hold: np.ndarray
    early_arrival: np.ndarray
    late_delay: np.ndarray
    overflow_delay: np.ndarray
    k: np.ndarray
    member: np.ndarray
    label: str

    @property
    def n(self) -> int:
        return int(self.need.shape[0])

    @property
    def early_delay(self) -> np.ndarray:
        return np.maximum(0.0, self.early_arrival)

    def subset(self, idx: np.ndarray, label: str) -> ScenarioSet:
        return ScenarioSet(
            self.need[idx],
            self.hold[idx],
            self.early_arrival[idx],
            self.late_delay[idx],
            self.overflow_delay[idx],
            self.k[idx],
            self.member[idx],
            label,
        )


@dataclass(frozen=True)
class Context:
    """Everything fixed for one planning run: scenario, advisory, geography, crews, arrival timing."""

    scenario: str
    advisory: str
    issued_utc: datetime
    landfall_utc: datetime
    late_request_utc: datetime
    geo: Geography
    inputs: MemberInputs
    persons_per_outage: float
    own_groups: int
    own_group_size: int
    ma_group_size: int
    ma_median_h: float
    ma_sigma: float
    k_low: float
    k_high: float
    loso_ratios: dict[str, float]
    customers_per_person: float
    home_groups: np.ndarray
    late_first_wave_persons: float
    late_scarcity_exponent: float

    @property
    def lead_h(self) -> float:
        return (self.landfall_utc - self.issued_utc).total_seconds() / 3600.0

    @property
    def late_request_h(self) -> float:
        return (self.late_request_utc - self.landfall_utc).total_seconds() / 3600.0


def home_groups(geo: Geography, own_persons_per_customer: float, own_groups: int) -> np.ndarray:
    """Own crew groups per yard: each county's own crews belong to its nearest yard (largest remainder)."""
    ylat = np.array([y.lat for y in geo.yards])
    ylon = np.array([y.lon for y in geo.yards])
    persons = np.zeros(len(geo.yards))
    for c in geo.counties:
        d = haversine_km(np.full(len(ylat), c.lat), np.full(len(ylon), c.lon), ylat, ylon)
        persons[int(np.argmin(d))] += c.customers * own_persons_per_customer
    share = persons / persons.sum() * own_groups
    out = np.floor(share).astype(int)
    for i in np.argsort(-(share - out))[: own_groups - int(out.sum())]:
        out[i] += 1
    return out


def build_context(name: str = "helene", advisory: str = "N") -> Context:
    scen = load_scenario(name)
    fam = load_family(str(scen.get("family", "A")))
    hz = scenario_hazard(name)
    adv = hz.advisory(advisory)
    geo = geography(name)
    ratio = family_value(fam, "personnel_per_1000_outages") / 1000.0
    total_customers = float(sum(c.customers for c in geo.counties))
    per_customer = family_value(fam, "internal_personnel_per_1000_customers") / 1000.0
    own_size = int(family_value(fam, "internal_group_headcount"))
    own_groups = int(total_customers * per_customer // own_size)
    k_low, k_high, ratios = scale_band(name)
    return Context(
        scenario=name,
        advisory=advisory,
        issued_utc=adv.issued.astimezone(UTC) if adv.issued.tzinfo else adv.issued.replace(tzinfo=UTC),
        landfall_utc=parse_utc(str(scen["storm"]["landfall_utc"])),
        late_request_utc=parse_utc(str(scen["detail"]["mutual_aid_request_utc"])),
        geo=geo,
        inputs=member_inputs(name, advisory),
        persons_per_outage=ratio,
        own_groups=own_groups,
        own_group_size=own_size,
        ma_group_size=int(family_value(fam, "mutual_aid_group_headcount")),
        ma_median_h=family_value(fam, "mutual_aid_median_h"),
        ma_sigma=family_value(fam, "mutual_aid_sigma"),
        k_low=k_low,
        k_high=k_high,
        loso_ratios=ratios,
        customers_per_person=1.0 / ratio,
        home_groups=home_groups(geo, per_customer, own_groups),
        late_first_wave_persons=float(param("late_first_wave_persons")),
        late_scarcity_exponent=float(param("late_scarcity_exponent")),
    )


def _county_to_cluster(ctx: Context, county_out: np.ndarray) -> np.ndarray:
    k = ctx.geo.n_clusters
    out = np.zeros((county_out.shape[0], k))
    for j in range(k):
        out[:, j] = county_out[:, ctx.geo.cluster_of == j].sum(axis=1)
    return out


def county_customers(ctx: Context) -> np.ndarray:
    return np.array([c.customers for c in ctx.geo.counties], dtype=float)


def timed(
    ctx: Context,
    need: np.ndarray,
    hold: np.ndarray,
    early_h: np.ndarray,
    late_h: np.ndarray,
    k: np.ndarray,
    member: np.ndarray,
    label: str,
) -> ScenarioSet:
    """Arrival times after landfall. Early aid: issue + draw. Late aid: request + draw x max(1, k)^gamma
    (scarcity when the storm is bigger than forecast); overflow beyond the first wave: one median arrival
    later."""
    k = np.asarray(k, dtype=float)
    scarcity = np.maximum(1.0, k) ** ctx.late_scarcity_exponent
    late = ctx.late_request_h + np.asarray(late_h, dtype=float) * scarcity
    return ScenarioSet(
        need=need,
        hold=hold,
        early_arrival=np.asarray(early_h, dtype=float) - ctx.lead_h,
        late_delay=late,
        overflow_delay=late + ctx.ma_median_h * scarcity,
        k=k,
        member=np.asarray(member),
        label=label,
    )


def sample(ctx: Context, n: int, seed: int, label: str) -> ScenarioSet:
    """n scenarios: members stratified (each once per full cycle), k log-uniform, arrivals lognormal."""
    rng = np.random.default_rng(seed)
    m_count = len(ctx.inputs.members)
    cycles = -(-n // m_count)
    member_idx = np.concatenate([rng.permutation(m_count) for _ in range(cycles)])[:n]
    k = np.exp(rng.uniform(math.log(ctx.k_low), math.log(ctx.k_high), size=n))
    early = rng.lognormal(math.log(ctx.ma_median_h), ctx.ma_sigma, size=n)
    late = rng.lognormal(math.log(ctx.ma_median_h), ctx.ma_sigma, size=n)
    return assemble(ctx, member_idx, k, early, late, label)


def assemble(
    ctx: Context, member_idx: np.ndarray, k: np.ndarray, early_h: np.ndarray, late_h: np.ndarray, label: str
) -> ScenarioSet:
    cust = county_customers(ctx)
    frac = np.minimum(ctx.inputs.county_frac[member_idx] * k[:, None], 1.0)
    need = _county_to_cluster(ctx, frac * cust[None, :]) * ctx.persons_per_outage
    members = np.asarray([ctx.inputs.members[i] for i in member_idx])
    return timed(ctx, need, ctx.inputs.yard_hold_h[member_idx], early_h, late_h, k, members, label)


def p50_need(ctx: Context) -> np.ndarray:
    frac = np.median(ctx.inputs.county_frac, axis=0)
    return _county_to_cluster(ctx, (frac * county_customers(ctx))[None, :]) * ctx.persons_per_outage


def p50_scenario(ctx: Context) -> ScenarioSet:
    """Deterministic P50 plan input: per-county median member forecast, k = 1, median arrivals and holds."""
    med = np.array([ctx.ma_median_h])
    hold = np.median(ctx.inputs.yard_hold_h, axis=0)[None, :]
    return timed(ctx, p50_need(ctx), hold, med, med, np.array([1.0]), np.array([-1]), "p50")


def mean_scenario(scen: ScenarioSet) -> ScenarioSet:
    """Expected-value problem input (Birge's EV): every random quantity replaced by its sample mean."""
    return ScenarioSet(
        need=scen.need.mean(axis=0, keepdims=True),
        hold=scen.hold.mean(axis=0, keepdims=True),
        early_arrival=np.array([scen.early_arrival.mean()]),
        late_delay=np.array([scen.late_delay.mean()]),
        overflow_delay=np.array([scen.overflow_delay.mean()]),
        k=np.array([float(np.exp(np.log(scen.k).mean()))]),
        member=np.array([-1]),
        label="ev",
    )


def synthetic_truth(ctx: Context, path: Path | None = None) -> ScenarioSet:
    """The generator's realised world (WP-06 `county_hourly.csv` peak per county; synthetic), with median
    mutual-aid arrivals and the median member's yard holds. Evaluation only, never a planning input.
    k is the realised requirement over the P50 forecast requirement."""
    path = path or FIXTURES / ctx.scenario / "county_hourly.csv"
    peak: dict[str, int] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            peak[row["fips"]] = max(peak.get(row["fips"], 0), int(row["customers_out"]))
    out = np.array([[peak.get(c.fips, 0) for c in ctx.geo.counties]], dtype=float)
    need = _county_to_cluster(ctx, out) * ctx.persons_per_outage
    k = np.array([float(need.sum() / max(1.0, p50_need(ctx).sum()))])
    med = np.array([ctx.ma_median_h])
    hold = np.median(ctx.inputs.yard_hold_h, axis=0)[None, :]
    return timed(ctx, need, hold, med, med, k, np.array([-1]), "synthetic_truth")
