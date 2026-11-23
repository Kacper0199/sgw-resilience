"""Robustness of the PS-17 hinge (review fix R08): how the N -> N+1 shift and the no-regret verdicts depend on
the size of advisory N's pinned forecast error, on the member threshold of the no-regret rule and on the
exposure level `clocks.material_loss_p`. Every run reuses the truth run and the seeded member draws."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

from sgw.generator import clocks as ck
from sgw.generator.config import Family
from sgw.generator.ensemble import run_ensembles
from sgw.generator.truth import Truth

PIN_SCALES = (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5)
MEMBER_THRESHOLDS = (0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5)
EXPOSURE_LEVELS = (0.05, 0.1, 0.2, 0.3)


def _family(fam: Family, **values: float) -> Family:
    params = dict(fam.params)
    for key, value in values.items():
        params[key] = replace(params[key], value=value)
    return Family(fam.name, fam.path, params)


def _with_scenario(truth: Truth, scenario: dict[str, Any]) -> Truth:
    other = copy.copy(truth)
    other.scenario = scenario
    return other


def _power(clock: dict[str, Any] | None) -> dict[str, Any]:
    if clock is None:
        return {"decide_by_utc": None, "effective_decide_by_utc": None, "verdict": None, "share_ppm": None}
    case = clock["cases"][ck.CASE_POWER]
    return {
        "decide_by_utc": case["clock"]["decide_by_utc"],
        "effective_decide_by_utc": case["effective_decide_by_utc"],
        "verdict": case["no_regret_verdict"],
        "share_ppm": case["no_regret_share_ppm"],
    }


def pin_sweep(truth: Truth, scales: tuple[float, ...] = PIN_SCALES) -> list[dict[str, Any]]:
    """Advisory N's pinned z-errors times `scale`; N+1 unchanged. Shift = own decide-by N+1 minus N."""
    fam = truth.family
    pts, base = run_ensembles(truth, labels=("N+1",))
    n1 = ck.advisory_clocks(base[0], pts, fam)
    pin = truth.scenario["advisories"]["official_error_overrides"]["N"]
    rows = []
    for scale in scales:
        sc = copy.deepcopy(truth.scenario)
        sc["advisories"]["official_error_overrides"]["N"] = {k: float(v) * scale for k, v in pin.items()}
        pts_n, ens = run_ensembles(_with_scenario(truth, sc), labels=("N",))
        n = ck.advisory_clocks(ens[0], pts_n, fam)
        shift = ck.shift_minutes(n, n1) if n is not None and n1 is not None else None
        rows.append({"scale": scale, "shift_min": shift, "N": _power(n)})
    return rows


def member_threshold_band(
    truth: Truth, thresholds: tuple[float, ...] = MEMBER_THRESHOLDS
) -> list[dict[str, Any]]:
    pts, ens = run_ensembles(truth, labels=("N", "N+1"))
    rows = []
    for th in thresholds:
        fam = _family(truth.family, **{"clocks.no_regret_member_p_loss": th})
        verdicts = [_power(ck.advisory_clocks(e, pts, fam))["verdict"] for e in ens]
        rows.append(
            {
                "member_p_loss": th,
                "verdict_N": verdicts[0],
                "verdict_N1": verdicts[1],
                "flip": verdicts == ["wait_for_next_advisory", "act_now"],
            }
        )
    return rows


def exposure_sensitivity(truth: Truth, levels: tuple[float, ...] = EXPOSURE_LEVELS) -> list[dict[str, Any]]:
    pts, ens = run_ensembles(truth, labels=("N", "N+1"))
    rows = []
    for level in levels:
        fam = _family(truth.family, **{"clocks.material_loss_p": level})
        n, n1 = (ck.advisory_clocks(e, pts, fam) for e in ens)
        rows.append(
            {
                "material_loss_p": level,
                "N": _power(n),
                "N+1": _power(n1),
                "shift_min": ck.shift_minutes(n, n1) if n is not None and n1 is not None else None,
            }
        )
    return rows


def hinge_robustness(truth: Truth) -> dict[str, Any]:
    sweep = pin_sweep(truth)
    flips = [r["scale"] for r in sweep if r["N"]["verdict"] == "wait_for_next_advisory"]
    band = member_threshold_band(truth)
    holds = [r["member_p_loss"] for r in band if r["flip"]]
    return {
        "pin_sweep": sweep,
        "min_pin_scale_for_flip": min(flips) if flips else None,
        "member_threshold_band": band,
        "flip_holds_for_member_p_loss": [min(holds), max(holds)] if holds else None,
        "exposure_sensitivity": exposure_sensitivity(truth),
    }
