"""Per-advisory ensembles evaluated at the decision points: footprint counties, Aiken feeder trunks, yards.

For each advisory: the official forecast and `forecast.members` perturbed members, each with its track, the
forecast 1-min wind on a 15-min grid from issue to issue + horizon, and per point the peak gust and the
tropical-storm onset. For the PS-17 trunk section each member also carries the loss-probability path
P_m(t) = P(capacity <= G_m(t)) under the truth model's capacity law (lognormal at theta_known, beta_total,
tails cut, floor), with G_m the running peak gust and beta_total the fragility
dispersion including the county and feeder random effects the forecaster cannot know.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
from scipy.stats import norm

from sgw.generator.config import Family
from sgw.generator.forecast import Advisory, advisories, member_tracks
from sgw.generator.network import QUANTILE_MAX, QUANTILE_MIN, Network
from sgw.generator.truth import Truth, wind_kwargs
from sgw.generator.wind import TS_MS, Track, epoch, first_crossing, sustained_wind

STEP_S = 900.0


@dataclass
class PointSet:
    ids: list[str]
    kinds: list[str]
    lat: np.ndarray
    lon: np.ndarray


@dataclass
class MemberResult:
    track: Track
    peak_gust: np.ndarray
    onset_t: np.ndarray
    p_loss_path: np.ndarray


@dataclass
class AdvisoryEnsemble:
    advisory: Advisory
    times: np.ndarray
    pinned: bool
    official: MemberResult
    members: list[MemberResult]


def decision_points(truth: Truth) -> PointSet:
    net: Network = truth.net
    detail = set(truth.scenario["detail"]["electric_fips"])
    ids, kinds, lat, lon = [], [], [], []
    for c in net.counties:
        ids.append(c.fips)
        kinds.append("county")
        lat.append(c.lat)
        lon.append(c.lon)
    for sid, fips, la, lo, trunk in zip(
        net.sections["id"],
        net.sections["fips"],
        net.sections["lat"],
        net.sections["lon"],
        net.sections["trunk"],
        strict=True,
    ):
        if trunk and fips in detail:
            ids.append(sid.removesuffix("-S1"))
            kinds.append("feeder")
            lat.append(float(la))
            lon.append(float(lo))
    for y in net.yards:
        ids.append(y["id"])
        kinds.append("yard")
        lat.append(y["lat"])
        lon.append(y["lon"])
    return PointSet(ids, kinds, np.array(lat), np.array(lon))


def loss_params(truth: Truth, section_id: str) -> tuple[float, float]:
    fam = truth.family
    j = truth.net.section_index()[section_id]
    theta = float(truth.net.sections["theta_known"][j])
    beta_total = float(
        np.sqrt(
            fam.f("fragility.beta") ** 2
            + fam.f("fragility.county_effect_sigma") ** 2
            + fam.f("fragility.feeder_effect_sigma") ** 2
        )
    )
    return theta, beta_total


def loss_probability(gust: np.ndarray, theta: float, beta: float, floor: float) -> np.ndarray:
    """P(capacity <= gust) for the truncated capacity law of the truth model (quantiles cut to [0.01, 0.99],
    no failure below the floor)."""
    p = (norm.cdf(np.log(np.maximum(gust, 1e-6) / theta) / beta) - QUANTILE_MIN) / (
        QUANTILE_MAX - QUANTILE_MIN
    )
    return np.where(gust >= floor, np.clip(p, 0.0, 1.0), 0.0)


def _evaluate(
    track: Track, times: np.ndarray, pts: PointSet, fam: Family, ps_col: int, theta: float, beta: float
) -> MemberResult:
    v = sustained_wind(track, times, pts.lat, pts.lon, **wind_kwargs(fam))
    gust = fam.f("wind.gust_factor") * v
    run_max = np.maximum.accumulate(gust[:, ps_col])
    p_path = loss_probability(run_max, theta, beta, fam.f("fragility.capacity_floor_gust_ms"))
    return MemberResult(track, gust.max(axis=0), first_crossing(v, times, TS_MS), p_path)


def run_ensembles(
    truth: Truth, ps_feeder: str = "FDR-AIK-2207", labels: tuple[str, ...] | None = None
) -> tuple[PointSet, list[AdvisoryEnsemble]]:
    fam = truth.family
    pts = decision_points(truth)
    ps_col = pts.ids.index(ps_feeder)
    theta, beta = loss_params(truth, f"{ps_feeder}-S1")
    out = []
    for adv in advisories(truth.scenario):
        if labels is not None and adv.label not in labels:
            continue
        start = epoch(adv.issued)
        times = np.arange(start, start + fam.f("forecast.horizon_h") * 3600.0 + 1.0, STEP_S)
        official, members, pinned = member_tracks(truth.track, adv, truth.scenario, fam, truth.seed)
        out.append(
            AdvisoryEnsemble(
                adv,
                times,
                pinned,
                _evaluate(official, times, pts, fam, ps_col, theta, beta),
                [_evaluate(m, times, pts, fam, ps_col, theta, beta) for m in members],
            )
        )
    return pts, out


def landfall_eta(truth: Truth, adv: Advisory, official: Track) -> datetime | None:
    """Forecast landfall: the time the official track reaches the truth landfall latitude."""
    from sgw.generator.config import parse_utc

    landfall = parse_utc(truth.scenario["storm"]["landfall_utc"])
    if adv.issued >= landfall:
        return None
    target = float(truth.track.at(np.array([epoch(landfall)]))["lat"][0])
    lat = official.lat
    idx = np.flatnonzero(lat >= target)
    if not len(idx) or idx[0] == 0:
        return None
    k = idx[0]
    frac = (target - lat[k - 1]) / (lat[k] - lat[k - 1])
    t = official.t[k - 1] + frac * (official.t[k] - official.t[k - 1])
    return datetime.fromtimestamp(round(t / 60.0) * 60.0, tz=landfall.tzinfo)


def ensemble_record(pts: PointSet, ens: AdvisoryEnsemble, p_member_threshold: float) -> dict[str, Any]:
    """Compact JSON-ready view: tracks on a 6-h lead grid, per point peak gust (m/s, 0.1) and TS onset
    (minutes after issue, null when none), PS-17 loss probability (ppm) per member."""
    issue = epoch(ens.advisory.issued)

    def member(m: MemberResult) -> dict[str, Any]:
        return {
            "track": [
                [
                    round((t - issue) / 3600.0, 1),
                    round(float(a), 2),
                    round(float(o), 2),
                    round(float(v) / 0.514444, 1),
                ]
                for t, a, o, v in zip(
                    m.track.t[::2], m.track.lat[::2], m.track.lon[::2], m.track.vmax[::2], strict=True
                )
            ],
            "peak_gust_ms": [round(float(g), 1) for g in m.peak_gust],
            "ts_onset_min": [None if np.isnan(o) else round((o - issue) / 60.0) for o in m.onset_t],
            "ps17_p_loss_ppm": round(float(m.p_loss_path[-1]) * 1e6),
        }

    return {
        "advisory_label": ens.advisory.label,
        "forecast_id": ens.advisory.forecast_id,
        "issued_utc": ens.advisory.issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "official_error_pinned": ens.pinned,
        "official": member(ens.official),
        "members": [member(m) for m in ens.members],
        "ps17_member_p_loss_threshold": p_member_threshold,
    }
