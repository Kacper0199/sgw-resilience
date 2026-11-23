"""Calibrate `restoration.repair_scale` so that the truth run's county t50 median equals the Helene t50.

t50 per county: hours from the county's peak customers out until customers out first falls to half the peak;
the target is the median over footprint counties (numbers.yaml `helene_restoration_t50_hours`, 35.5 h, which
equals the median of the EAGLE-I calibration table over the 123 counties). Bisection on the scale; t50 is
monotone in the scale up to the 15-min grid, so the result is the smallest scale whose t50 reaches the target.
"""

from __future__ import annotations

from dataclasses import dataclass

from sgw.common import numbers as numbers_mod
from sgw.generator.config import load_family, load_scenario
from sgw.generator.restoration import median_t50
from sgw.generator.truth import run_truth


@dataclass(frozen=True)
class Calibration:
    target_h: float
    scale: float
    t50_h: float
    iterations: int


def calibrate_repair_scale(
    scenario_name: str = "helene", lo: float = 0.05, hi: float = 1.5, tol: float = 0.005
) -> Calibration:
    scenario = load_scenario(scenario_name)
    fam = load_family(scenario.get("family", "A"))
    target = float(numbers_mod.value("helene_restoration_t50_hours"))
    it = 0
    while hi - lo > tol:
        mid = (lo + hi) / 2.0
        t50 = median_t50(run_truth(scenario, fam, repair_scale=mid).county)
        lo, hi = (mid, hi) if t50 < target else (lo, mid)
        it += 1
    scale = round(hi, 3)
    t50 = median_t50(run_truth(scenario, fam, repair_scale=scale).county)
    return Calibration(target, scale, t50, it)
