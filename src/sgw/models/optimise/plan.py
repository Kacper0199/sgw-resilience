"""Crew-plan document: the courses of action, baselines, metrics, envelope bounds and EDXL-RM requests, as one
JSON-ready dict (stored as a `crew_plan` snapshot by the async job, printed by the CLI)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from sgw.common import numbers as numbers_mod
from sgw.contracts.vocab import ActionType, Tier
from sgw.models.optimise.coa import COA_IDS, ENGINE_VERSION, PlanRun, envelope_bounds, plan_params
from sgw.models.optimise.edxl import request_resource
from sgw.models.optimise.scenarios import param


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def document(run: PlanRun, *, incident_id: str = "INC-HELENE-2024") -> dict[str, Any]:
    ctx = run.ctx
    pct = int(numbers_mod.value("policy_envelope_pct"))
    day_rate = float(param("mutual_aid_usd_per_person_day"))
    plans: list[dict[str, Any]] = []
    p50 = run.outcomes["P50"]
    for pid, out in run.outcomes.items():
        item = out.summary(ctx, p50)
        if pid in COA_IDS:
            item["action_type"] = ActionType.PREPOSITION_CREWS.value
            item["tier"] = Tier.T3.value
            item["params"] = plan_params(ctx, out.solve)
            bounds = envelope_bounds(ctx, out.solve, pct)
            item["envelope"] = {
                "pct": pct,
                "bounds": {k: b.model_dump() for k, b in bounds.items()},
                "rule": "re-optimisation inside these bounds is T1; outside or after expiry T3 again (O-04)",
                "pinned_yards": sorted(k for k, b in bounds.items() if b.min == b.max),
                "note": (
                    f"+-{pct}% of fewer than {math.ceil(100 / pct)} groups rounds to 0: those yards are "
                    "pinned and any change there is T3"
                ),
            }
            item["resource_request"] = request_resource(
                ctx, pid, out.solve, incident_id=incident_id, sent=ctx.issued_utc, usd_per_person_day=day_rate
            )
        plans.append(item)
    return {
        "engine_version": ENGINE_VERSION,
        "scenario": ctx.scenario,
        "advisory": ctx.advisory,
        "issued_utc": _iso(ctx.issued_utc),
        "landfall_utc": _iso(ctx.landfall_utc),
        "objective": "customer-hours of crew-arrival delay (travel, yard hold, aid arrival); synthetic",
        "size": {
            "yards": len(ctx.geo.yards),
            "clusters": ctx.geo.n_clusters,
            "scenarios": run.n_in,
            "out_of_sample": run.n_out,
        },
        "crews": {
            "own_groups": ctx.own_groups,
            "own_group_persons": ctx.own_group_size,
            "mutual_aid_group_persons": ctx.ma_group_size,
            "persons_per_1000_outages": round(ctx.persons_per_outage * 1000, 2),
        },
        "forecast_scale_band": {
            "k_low": round(ctx.k_low, 4),
            "k_high": round(ctx.k_high, 4),
            "from_loso_ratios_excluding_replayed_storm": {k: round(v, 4) for k, v in ctx.loso_ratios.items()},
            "observed_scale_stress_k": round(run.stress_k, 4),
            "note": (
                "storm-scale ambiguity of the A2 forecast, symmetric in log; the replayed storm's own "
                "hindcast error is used only for the stress evaluation, never for planning"
            ),
        },
        "planning_band_check": {
            "synthetic_truth_requirement_over_p50": round(run.truth_k, 2),
            "inside_planning_band": bool(ctx.k_low <= run.truth_k <= ctx.k_high),
            "note": (
                f"the generator's realised requirement is {run.truth_k:.1f}x the P50 forecast, "
                f"{'inside' if ctx.k_low <= run.truth_k <= ctx.k_high else 'outside'} the planning band "
                f"[{ctx.k_low:.2f}, {ctx.k_high:.2f}]; no plan sized from this forecast covers it, the "
                "gap is filled by post-landfall mutual aid"
            ),
        },
        "staging_rules": {
            "home_share_min": float(param("home_share_min")),
            "site_cap_persons": int(param("site_cap_persons")),
            "label": "Assumed SGW policy; replace the site cap with the logistics site list",
        },
        "cvar_check": run.cvar_check,
        "caps_groups": run.caps,
        "plans": plans,
        "vss": run.vss,
        "evpi": run.evpi,
        "saa_bounds": run.mmw,
        "replications": run.replications,
        "recommendation": None,
        "recommendation_note": (
            "the optimiser does not pick: the trade-off (committed spend and idle crews against tail "
            "customer-hours) is the T3 approvers' call"
        ),
    }
