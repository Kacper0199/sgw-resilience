"""Truth run: the storm on the network, from wind to customers restored."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import norm

from sgw.generator import restoration as rs
from sgw.generator.config import Family, load_counties, parse_utc, rng
from sgw.generator.network import Network, build_network
from sgw.generator.wind import Track, calm_after_peak, epoch, first_crossing, sustained_wind

STEP_S = 900.0


@dataclass
class Truth:
    scenario: dict[str, Any]
    family: Family
    seed: int
    track: Track
    net: Network
    times: np.ndarray
    wind_times: np.ndarray
    section_gust_peak: np.ndarray
    fault_t: np.ndarray
    work_ok: np.ndarray
    ds: np.ndarray
    repair_h: np.ndarray
    crews: list[rs.Crew]
    restored_t: np.ndarray
    effective_restore_t: np.ndarray
    assignments: list[rs.Assignment]
    out: np.ndarray
    county: dict[str, dict[str, float]]
    point_wind: dict[str, np.ndarray]


def wind_kwargs(fam: Family) -> dict[str, float]:
    return {
        "holland_b": fam.f("wind.holland_b"),
        "inner_exponent": fam.f("wind.inner_exponent"),
        "r34_fallback": fam.f("wind.r34_fallback_rmw_multiple"),
        "r34_extent": fam.f("wind.r34_extent_factor"),
        "taper_start": fam.f("wind.taper_start_r34"),
        "taper_end": fam.f("wind.taper_end_r34"),
    }


def site_gust_multiplier(ids: list[str], fam: Family, seed: int) -> np.ndarray:
    sigma = fam.f("wind.site_gust_sigma")
    return np.array([np.exp(sigma * rng(seed, "site_gust", i).standard_normal()) for i in ids])


def run_truth(
    scenario: dict[str, Any], fam: Family, seed: int | None = None, repair_scale: float | None = None
) -> Truth:
    seed = int(scenario["seed"] if seed is None else seed)
    if repair_scale is not None:
        fam = _with_param(fam, "restoration.repair_scale", repair_scale)
    track = Track.from_rows(scenario["storm"]["track"], parse_utc)
    net = build_network(load_counties(), fam, scenario, seed)
    start = epoch(parse_utc(scenario["window"]["start_utc"]))
    end = epoch(parse_utc(scenario["window"]["end_utc"]))
    times = np.arange(start, end + 1.0, STEP_S)
    wind_times = times[(times >= track.t[0]) & (times <= track.t[-1])]
    lat = np.asarray(net.sections["lat"], dtype=float)
    lon = np.asarray(net.sections["lon"], dtype=float)
    v = sustained_wind(track, wind_times, lat, lon, **wind_kwargs(fam))
    gust = fam.f("wind.gust_factor") * v * site_gust_multiplier(net.sections["id"], fam, seed)[None, :]
    capacity = np.asarray(net.sections["capacity"], dtype=float)
    fault_t = first_crossing(gust, wind_times, capacity)
    failed = ~np.isnan(fault_t)
    peak = gust.max(axis=0)
    limit = fam.f("restoration.bucket_limit_sustained_ms")
    calm_from = calm_after_peak(v, wind_times, limit)
    access_h = access_delay_h(net, peak, fam, scenario, seed)
    work_ok = np.where(np.isnan(calm_from), fault_t, np.fmax(calm_from, fault_t)) + access_h * 3600.0
    ds = rs.damage_states(net, peak, failed, fam, seed)
    repair_h = rs.base_repair_hours(net, ds, fam, seed)
    request_t = epoch(parse_utc(scenario["detail"]["mutual_aid_request_utc"]))
    crews = rs.plan_crews(net, fault_t, fam, scenario, seed, start, request_t)
    restored_t, log = rs.restore(net, fault_t, work_ok, repair_h, ds, crews, fam)
    out, eff = rs.customers_out_series(net, fault_t, restored_t, times)
    county = rs.county_metrics(net, out, times)
    point_wind = {"v1min": v, "gust": gust}
    return Truth(
        scenario,
        fam,
        seed,
        track,
        net,
        times,
        wind_times,
        peak,
        fault_t,
        work_ok,
        ds,
        repair_h,
        crews,
        restored_t,
        eff,
        log,
        out,
        county,
        point_wind,
    )


def access_delay_h(
    net: Network, peak_gust: np.ndarray, fam: Family, scenario: dict[str, Any], seed: int
) -> np.ndarray:
    """Debris on the access road: blocked with the tree-failure probability at the section's peak gust,
    cleared after a lognormal time."""
    soil = float(scenario["antecedent_soil_multiplier"]["value"])
    median = fam.f("restoration.access_tree_median_gust_ms") * soil
    p_block = norm.cdf(np.log(np.maximum(peak_gust, 1e-6) / median) / fam.f("restoration.access_tree_beta"))
    out = np.zeros(len(peak_gust))
    med_h = fam.f("restoration.access_clearance_median_h")
    sig = fam.f("restoration.access_clearance_sigma")
    for i, sid in enumerate(net.sections["id"]):
        r = rng(seed, "access", sid)
        blocked, draw = r.uniform(), r.lognormal(np.log(med_h), sig)
        out[i] = draw if blocked < p_block[i] else 0.0
    return out


def _with_param(fam: Family, key: str, value: Any) -> Family:
    from dataclasses import replace

    params = dict(fam.params)
    params[key] = replace(params[key], value=value)
    return Family(fam.name, fam.path, params)
