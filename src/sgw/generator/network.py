"""Synthetic SGW network: footprint-wide feeders and sections per county (customer counts from EAGLE-I
`MCC.csv`), Aiken detail with the named assets of the PS-17 story, staging yards and crew groups.

Fragility (lognormal on the 3-s gust): section median

    theta = median * soil * exp(u_county + u_feeder) * age_ratio(pole_age) * (1 - veg_reduction * veg),

capacity = max(theta * exp(beta * Phi^-1(q)), floor), q ~ U(0.01, 0.99) per section (pinned for seeded cases;
tails and floor because the storm curve says nothing about gusts under about 20 m/s, where blue-sky faults
rule). A section fails at the first time its gust reaches the capacity. The "known" median (what a forecaster
can know) omits the random effects; their spread is folded into the known dispersion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm

from sgw.generator.config import County, Family, rng
from sgw.generator.wind import distance_km

QUANTILE_MIN = 0.01
QUANTILE_MAX = 0.99
COUNTY_CODE_OVERRIDES = {
    "45003": "AIK",
    "13245": "RCH",
    "45079": "RLD",
    "45045": "GVL",
    "45019": "CHS",
    "45041": "FLO",
    "13051": "CHT",
    "13299": "WRE",
    "13175": "LAU",
    "13059": "CLK",
    "45091": "YRK",
}


@dataclass
class Network:
    counties: list[County]
    county_code: dict[str, str]
    feeders: dict[str, np.ndarray | list[Any]]
    sections: dict[str, np.ndarray | list[Any]]
    yards: list[dict[str, Any]]
    crews: list[dict[str, Any]]
    named: dict[str, Any] = field(default_factory=dict)

    def section_index(self) -> dict[str, int]:
        return {sid: i for i, sid in enumerate(self.sections["id"])}

    def feeder_index(self) -> dict[str, int]:
        return {fid: i for i, fid in enumerate(self.feeders["id"])}


def _county_codes(counties: list[County]) -> dict[str, str]:
    codes: dict[str, str] = {}
    used = set(COUNTY_CODE_OVERRIDES.values())
    for c in counties:
        if c.fips in COUNTY_CODE_OVERRIDES:
            codes[c.fips] = COUNTY_CODE_OVERRIDES[c.fips]
            continue
        letters = "".join(ch for ch in c.name.upper() if ch.isalpha())
        candidates = [letters[:3]] + [
            letters[0] + letters[i] + letters[j]
            for i in range(1, len(letters))
            for j in range(i + 1, len(letters))
        ]
        code = next((x + c.st[0] for x in candidates if x + c.st[0] not in used), None)
        if code is None:
            raise ValueError(f"no county code for {c.name}")
        codes[c.fips] = code
        used.add(code)
    return codes


def _split(total: int, weights: np.ndarray) -> np.ndarray:
    raw = weights / weights.sum() * total
    out = np.floor(raw).astype(int)
    rest = total - out.sum()
    order = np.argsort(-(raw - out), kind="stable")
    out[order[:rest]] += 1
    return out


def age_ratio(age: np.ndarray, fam: Family) -> np.ndarray:
    return np.interp(age, fam.arr("fragility.age_points_years"), fam.arr("fragility.age_median_ratio"))


def cascade_factor(fam: Family) -> float:
    """Section median / county median. The handoff curve gives the fraction of customers out; a breaker-zone
    (trunk) fault drops the whole feeder, so with n equal sections a customer outside the trunk zone is out
    with 1 - (1 - q)^2. Solve w q + (1 - w)(1 - (1 - q)^2) = 0.5 (w = 1/n) and return exp(-beta Phi^-1(q))."""
    n = int(fam["network.sections_per_feeder"])
    w = 1.0 / n
    q = brentq(lambda x: w * x + (1.0 - w) * (1.0 - (1.0 - x) ** 2) - 0.5, 1e-9, 0.5)
    return float(np.exp(-fam.f("fragility.beta") * norm.ppf(q)))


def modifier_norm(fam: Family) -> float:
    """Mean of the age and vegetation modifiers over the asset population, so that the population median
    stays at the handoff median (the modifiers redistribute vulnerability, they do not shift it)."""
    lo, hi = fam["network.pole_age_range_years"]
    va, vb = fam["network.veg_beta_ab"]
    ages = np.linspace(lo, hi, 401)
    mean_age = float(np.mean(age_ratio(ages, fam)))
    mean_veg = 1.0 - fam.f("fragility.veg_median_reduction") * va / (va + vb)
    return mean_age * mean_veg


def build_network(counties: list[County], fam: Family, scenario: dict[str, Any], seed: int) -> Network:
    named = scenario["named"]
    codes = _county_codes(counties)
    per_feeder = fam.f("network.customers_per_feeder")
    n_sec = int(fam["network.sections_per_feeder"])
    alpha = fam.f("network.section_dirichlet_alpha")
    jitter = fam.f("network.feeder_jitter_deg")
    age_lo, age_hi = fam["network.pole_age_range_years"]
    va, vb = fam["network.veg_beta_ab"]
    sigma_c = fam.f("fragility.county_effect_sigma")
    sigma_f = fam.f("fragility.feeder_effect_sigma")
    soil = float(scenario["antecedent_soil_multiplier"]["value"])
    median = fam.f("fragility.median_gust_ms") * soil
    veg_red = fam.f("fragility.veg_median_reduction")
    norm_k = modifier_norm(fam)
    cascade = cascade_factor(fam)
    cap_floor = fam.f("fragility.capacity_floor_gust_ms")
    named_feeders: dict[str, dict[str, Any]] = named["feeders"]
    pins = {
        p["pin"]["section"]: p["pin"]
        for p in scenario["seeded"]
        if isinstance(p.get("pin"), dict) and "section" in p["pin"]
    }

    f: dict[str, list[Any]] = {
        k: []
        for k in (
            "id",
            "fips",
            "lat",
            "lon",
            "customers",
            "pole_age",
            "veg",
            "ami",
            "substation",
            "theta_known",
            "u_feeder",
        )
    }
    s: dict[str, list[Any]] = {
        k: []
        for k in (
            "id",
            "feeder",
            "fips",
            "lat",
            "lon",
            "customers",
            "trunk",
            "device",
            "theta",
            "theta_known",
            "quantile",
            "capacity",
            "pinned_ds",
            "critical",
        )
    }
    for c in counties:
        r = rng(seed, "network", "county", c.fips)
        u_c = r.normal(0.0, sigma_c)
        n_f = max(1, round(c.customers / per_feeder))
        code = codes[c.fips]
        ids = [f"FDR-{code}-{2201 + i}" for i in range(n_f)]
        fixed = {fid: named_feeders[fid] for fid in ids if fid in named_feeders}
        free_ids = [fid for fid in ids if fid not in fixed]
        free_total = c.customers - sum(int(v["customers"]) for v in fixed.values())
        weights = r.dirichlet(np.full(len(free_ids), 5.0)) if free_ids else np.array([])
        counts = dict(zip(free_ids, _split(free_total, weights), strict=True)) if free_ids else {}
        sub_k = 0
        for fid in ids:
            rf = rng(seed, "network", "feeder", fid)
            spec = fixed.get(fid)
            lat = float(spec["lat"]) if spec else c.lat + rf.uniform(-jitter, jitter)
            lon = float(spec["lon"]) if spec else c.lon + rf.uniform(-jitter, jitter)
            age = float(spec["pole_age"]) if spec else rf.uniform(age_lo, age_hi)
            veg = float(spec["veg"]) if spec else rf.beta(va, vb)
            ami_ab = fam["network.ami_beta_sc"] if c.st == "SC" else fam["network.ami_beta_ga"]
            ami = rf.beta(*ami_ab)
            u_f = rf.normal(0.0, sigma_f)
            customers = int(spec["customers"]) if spec else int(counts[fid])
            if spec:
                substation = named["substation"]["id"]
            else:
                substation = f"SUB-{code}-{101 + sub_k // int(fam['network.feeders_per_substation'])}"
                sub_k += 1
            theta_known = median * float(age_ratio(np.array([age]), fam)[0]) * (1.0 - veg_red * veg) / norm_k
            for key, val in (
                ("id", fid),
                ("fips", c.fips),
                ("lat", lat),
                ("lon", lon),
                ("customers", customers),
                ("pole_age", age),
                ("veg", veg),
                ("ami", ami),
                ("substation", substation),
                ("theta_known", theta_known),
                ("u_feeder", u_f),
            ):
                f[key].append(val)
            shares = _split(customers, rf.dirichlet(np.full(n_sec, alpha)))
            for k in range(n_sec):
                sid = f"{fid}-S{k + 1}"
                pin = pins.get(sid, {})
                q = float(pin.get("capacity_quantile", rf.uniform(QUANTILE_MIN, QUANTILE_MAX)))
                theta = theta_known * cascade * np.exp(u_c + u_f)
                cap = max(theta * np.exp(fam.f("fragility.beta") * norm.ppf(q)), cap_floor)
                off = (0.0, 0.0) if k == 0 else (rf.uniform(-0.03, 0.03), rf.uniform(-0.03, 0.03))
                for key, val in (
                    ("id", sid),
                    ("feeder", fid),
                    ("fips", c.fips),
                    ("lat", lat + off[0]),
                    ("lon", lon + off[1]),
                    ("customers", int(shares[k])),
                    ("trunk", k == 0),
                    ("device", f"BRK-{fid}" if k == 0 else f"RCL-{fid}-{k + 1}"),
                    ("theta", theta),
                    ("theta_known", theta_known * cascade),
                    ("quantile", q),
                    ("capacity", cap),
                    ("pinned_ds", int(pin.get("damage_state", 0))),
                    ("critical", ""),
                ):
                    s[key].append(val)
    critical: dict[str, list[str]] = {}
    for ps_id, ps in named["pump_stations"].items():
        critical.setdefault(f"{ps['feeder']}-S1", []).append(ps_id)
    hosp = named["hospital"]
    critical.setdefault(f"{hosp['feeder']}-S1", []).append(hosp["id"])
    s["critical"] = [",".join(critical.get(sid, [])) for sid in s["id"]]

    feeders = {k: (np.asarray(v) if k not in ("id", "fips", "substation") else v) for k, v in f.items()}
    sections = {
        k: (np.asarray(v) if k not in ("id", "feeder", "fips", "device", "critical") else v)
        for k, v in s.items()
    }
    yards = [
        {"id": yid, "fips": str(y["fips"]), "lat": float(y["lat"]), "lon": float(y["lon"])}
        for yid, y in named["yards"].items()
    ]
    return Network(
        counties=counties,
        county_code=codes,
        feeders=feeders,
        sections=sections,
        yards=yards,
        crews=[],
        named=named,
    )


def nearest_yard(net: Network, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    ylat = np.array([y["lat"] for y in net.yards])
    ylon = np.array([y["lon"] for y in net.yards])
    d = distance_km(lat[:, None], lon[:, None], ylat[None, :], ylon[None, :])
    return np.argmin(d, axis=1)
