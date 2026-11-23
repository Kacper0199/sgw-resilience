"""Damage states and crew-constrained restoration.

Damage state given failure follows ordered lognormal states (slight, moderate, extensive, complete) at medians
theta * m_k, conditioned on failure, evaluated at the section's peak gust. Repair work time per job is
`repair_scale * Hazus distribution-circuit days (truncated normal)`; `repair_scale` is calibrated so that the
median over counties of "hours from county peak to 50 percent of peak" is the Helene t50 (numbers.yaml).
Crew groups work from their yard's area, highest priority first (critical facilities, then customers per
expected hour), one job at a time; work starts only after the local sustained wind has dropped below the
bucket-truck limit. Mutual-aid groups are sized at damage assessment to the Helene personnel ratio and arrive
after a lognormal delay. No shift limits, no material shortages, no road closures (assumptions).
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import norm, truncnorm

from sgw.generator.config import Family, rng
from sgw.generator.network import Network, nearest_yard
from sgw.generator.wind import distance_km

DS_NAMES = ("none", "slight", "moderate", "extensive", "complete")


def damage_states(
    net: Network, peak_gust: np.ndarray, failed: np.ndarray, fam: Family, seed: int
) -> np.ndarray:
    beta = fam.f("fragility.beta")
    mult = fam.arr("fragility.ds_median_multipliers")
    theta = np.asarray(net.sections["theta"], dtype=float)
    exceed = norm.cdf(np.log(np.maximum(peak_gust, 1e-6)[:, None] / (theta[:, None] * mult[None, :])) / beta)
    cond = exceed / np.maximum(exceed[:, :1], 1e-12)
    ds = np.zeros(len(theta), dtype=int)
    pinned = np.asarray(net.sections["pinned_ds"], dtype=int)
    for i in np.flatnonzero(failed):
        if pinned[i]:
            ds[i] = pinned[i]
            continue
        v = rng(seed, "damage", net.sections["id"][i]).uniform()
        ds[i] = 1 + int(np.sum(v <= cond[i, 1:]))
    return ds


def base_repair_hours(net: Network, ds: np.ndarray, fam: Family, seed: int) -> np.ndarray:
    mean = fam.arr("restoration.hazus_days_mean")
    sd = fam.arr("restoration.hazus_days_sigma")
    out = np.zeros(len(ds))
    for i in np.flatnonzero(ds > 0):
        k = ds[i] - 1
        a = (0.05 - mean[k]) / sd[k]
        r = rng(seed, "repair", net.sections["id"][i])
        out[i] = float(truncnorm.rvs(a, np.inf, loc=mean[k], scale=sd[k], random_state=r)) * 24.0
    return out


@dataclass
class Crew:
    id: str
    yard: int
    headcount: int
    mutual_aid: bool
    available_utc: float


@dataclass
class Assignment:
    crew: str
    section: int
    assigned: float
    arrive: float
    start: float
    end: float


def plan_crews(
    net: Network,
    fault_t: np.ndarray,
    fam: Family,
    scenario: dict[str, Any],
    seed: int,
    window_start: float,
    request_t: float,
) -> list[Crew]:
    """Internal groups per yard by customers served; mutual aid sized from the outages known at request."""
    yard_of = section_yards(net)
    customers = np.asarray(net.sections["customers"])
    named = scenario["named"]["crews"]
    crews: list[Crew] = []
    per_k = fam.f("restoration.internal_personnel_per_1000_customers")
    ratio = fam.f("restoration.personnel_per_1000_outages")
    hc_in = int(fam["restoration.internal_group_headcount"])
    hc_ma = int(fam["restoration.mutual_aid_group_headcount"])
    med = fam.f("restoration.mutual_aid_median_h")
    sig = fam.f("restoration.mutual_aid_sigma")
    birds = (
        "OSPREY",
        "KESTREL",
        "MERLIN",
        "HARRIER",
        "SHRIKE",
        "PLOVER",
        "GANNET",
        "CORMORANT",
        "EGRET",
        "TANAGER",
        "WARBLER",
        "GROSBEAK",
        "NIGHTJAR",
        "SWIFT",
        "PETREL",
        "TERN",
        "BITTERN",
        "HERON",
    )
    yard_ids = [y["id"] for y in net.yards]
    for yi, yid in enumerate(yard_ids):
        in_yard = yard_of == yi
        internal_people = per_k * customers[in_yard].sum() / 1000.0
        n_internal = max(2, math.ceil(internal_people / hc_in))
        fixed_internal = [cid for cid, c in named.items() if c["yard"] == yid and not c["mutual_aid"]]
        fixed_ma = [cid for cid, c in named.items() if c["yard"] == yid and c["mutual_aid"]]
        ids = list(fixed_internal)
        n = 1
        while len(ids) < n_internal:
            cid = f"CRW-{birds[(yi + n) % len(birds)]}-{yi + 1:02d}{n:02d}"
            if cid not in named:
                ids.append(cid)
            n += 1
        crews += [Crew(cid, yi, hc_in, False, window_start) for cid in ids]
        known = in_yard & (fault_t <= request_t)
        outages = customers[known].sum()
        need = max(0.0, ratio * outages / 1000.0 - n_internal * hc_in)
        n_ma = math.ceil(need / hc_ma) if need > 0 else 0
        ma_ids = list(fixed_ma)[:n_ma]
        n = 1
        while len(ma_ids) < n_ma:
            cid = f"CRW-MA-{birds[(yi + 2 * n) % len(birds)]}-{yi + 1:02d}{n:02d}"
            if cid not in named:
                ma_ids.append(cid)
            n += 1
        for cid in ma_ids:
            delay_h = float(rng(seed, "mutual_aid", cid).lognormal(np.log(med), sig))
            crews.append(Crew(cid, yi, hc_ma, True, request_t + delay_h * 3600.0))
    return crews


def section_yards(net: Network) -> np.ndarray:
    return nearest_yard(net, np.asarray(net.sections["lat"]), np.asarray(net.sections["lon"]))


def restore(
    net: Network,
    fault_t: np.ndarray,
    work_ok: np.ndarray,
    repair_h: np.ndarray,
    ds: np.ndarray,
    crews: list[Crew],
    fam: Family,
) -> tuple[np.ndarray, list[Assignment]]:
    """Event-driven list scheduling per yard. Returns restore time per section (NaN if not faulted)."""
    travel_kmh = fam.f("restoration.travel_kmh")
    min_h = fam.f("restoration.min_repair_h")
    yard_of = section_yards(net)
    lat = np.asarray(net.sections["lat"])
    lon = np.asarray(net.sections["lon"])
    critical = np.array([bool(c) for c in net.sections["critical"]])
    trunk = np.asarray(net.sections["trunk"])
    customers = np.asarray(net.sections["customers"], dtype=float)
    feeder_customers: dict[str, float] = {}
    for fid, cust in zip(net.feeders["id"], net.feeders["customers"], strict=True):
        feeder_customers[fid] = float(cust)
    weight = np.array(
        [
            feeder_customers[f] if t else c
            for f, t, c in zip(net.sections["feeder"], trunk, customers, strict=True)
        ]
    )
    mean_h = fam.arr("restoration.hazus_days_mean") * 24.0 * fam.f("restoration.repair_scale")
    restored = np.full(len(fault_t), np.nan)
    log: list[Assignment] = []
    for yi, yard in enumerate(net.yards):
        jobs = np.flatnonzero((yard_of == yi) & ~np.isnan(fault_t))
        if len(jobs) == 0:
            continue
        open_mask = np.ones(len(jobs), dtype=bool)
        heap = [(c.available_utc, k, c) for k, c in enumerate(crews) if c.yard == yi]
        heapq.heapify(heap)
        pos = {c.id: (yard["lat"], yard["lon"]) for _, _, c in heap}
        while heap and open_mask.any():
            t, k, crew = heapq.heappop(heap)
            ready = open_mask & (fault_t[jobs] <= t)
            if not ready.any():
                nxt = fault_t[jobs][open_mask].min()
                heapq.heappush(heap, (float(nxt), k, crew))
                continue
            cand = jobs[ready]
            here = pos[crew.id]
            travel = distance_km(here[0], here[1], lat[cand], lon[cand]) / travel_kmh + 0.25
            score = weight[cand] / (travel + mean_h[np.maximum(ds[cand], 1) - 1])
            score = np.where(critical[cand], score + 1e12, score)
            best = int(np.argmax(score))
            j = int(cand[best])
            arrive = t + travel[best] * 3600.0
            start = max(arrive, float(work_ok[j]))
            end = start + max(min_h, float(repair_h[j]) * fam.f("restoration.repair_scale")) * 3600.0
            restored[j] = end
            open_mask[np.flatnonzero(jobs == j)[0]] = False
            log.append(Assignment(crew.id, j, t, arrive, start, end))
            pos[crew.id] = (float(lat[j]), float(lon[j]))
            heapq.heappush(heap, (end, k, crew))
    return restored, log


def customers_out_series(
    net: Network, fault_t: np.ndarray, restored_t: np.ndarray, times: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Customers out per section over `times` (a section is out while its own fault or its trunk's fault is
    open). Returns (out matrix [time, section] as bool, effective restore time per section)."""
    idx = net.section_index()
    trunk_of = np.array([idx[f"{f}-S1"] for f in net.sections["feeder"]])
    own = (
        (~np.isnan(fault_t))[None, :]
        & (times[:, None] >= np.nan_to_num(fault_t, nan=np.inf)[None, :])
        & (times[:, None] < np.nan_to_num(restored_t, nan=np.inf)[None, :])
    )
    tf = fault_t[trunk_of]
    tr = restored_t[trunk_of]
    via_trunk = (
        (~np.isnan(tf))[None, :]
        & (times[:, None] >= np.nan_to_num(tf, nan=np.inf)[None, :])
        & (times[:, None] < np.nan_to_num(tr, nan=np.inf)[None, :])
    )
    out = own | via_trunk
    eff = np.fmax(np.where(np.isnan(fault_t), np.nan, restored_t), np.where(np.isnan(tf), np.nan, tr))
    return out, eff


def county_metrics(net: Network, out: np.ndarray, times: np.ndarray) -> dict[str, dict[str, float]]:
    customers = np.asarray(net.sections["customers"], dtype=float)
    fips = np.asarray(net.sections["fips"])
    result: dict[str, dict[str, float]] = {}
    for c in net.counties:
        cols = fips == c.fips
        series = (out[:, cols] * customers[cols][None, :]).sum(axis=1)
        peak = float(series.max())
        if peak <= 0:
            continue
        ip = int(np.argmax(series))
        after = series[ip:]
        t50 = _hours_to(after, 0.5 * peak, times[ip:])
        t90 = _hours_to(after, 0.1 * peak, times[ip:])
        result[c.fips] = {
            "peak_out": peak,
            "peak_frac": peak / max(c.customers, 1),
            "peak_utc": float(times[ip]),
            "t50_h": t50,
            "t90_h": t90,
        }
    return result


def _hours_to(series: np.ndarray, level: float, times: np.ndarray) -> float:
    hit = np.flatnonzero(series <= level)
    return float((times[hit[0]] - times[0]) / 3600.0) if len(hit) else float("nan")


def median_t50(metrics: dict[str, dict[str, float]]) -> float:
    vals = [m["t50_h"] for m in metrics.values() if not math.isnan(m["t50_h"])]
    return float(np.median(vals)) if vals else float("nan")
