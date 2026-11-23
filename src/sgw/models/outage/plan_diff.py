"""Plan diff between two advisories (N -> N+1): what changed in the risk picture and in the no-regret shares.

Rows are ranked by size of change. An action is flagged when its share crosses the act-now policy threshold
(`policy_no_regret_act_now_ppm`), since that is the change that can flip a wait into an act-now verdict.
"""

from __future__ import annotations

from typing import Any

from sgw.common import numbers as numbers_mod
from sgw.models.outage.forecast import AdvisoryRisk

TOP_COUNTIES = 10
TOP_ASSETS = 10


def plan_diff(before: AdvisoryRisk, after: AdvisoryRisk) -> dict[str, Any]:
    if before.scenario != after.scenario:
        raise ValueError("plan diff needs two advisories of one scenario")
    threshold = int(numbers_mod.value("policy_no_regret_act_now_ppm"))
    c = before.counties.merge(after.counties, on=["fips", "name"], suffixes=("_before", "_after"))
    c["delta_p50_out"] = c["q0500_out_after"] - c["q0500_out_before"]
    c["delta_p90_out"] = c["q0900_out_after"] - c["q0900_out_before"]
    c["delta_p_ppm"] = c["p_ppm_after"] - c["p_ppm_before"]
    c = c.reindex(c["delta_p50_out"].abs().sort_values(ascending=False).index)
    counties = [
        {
            "fips": r.fips,
            "name": r.name,
            "p50_out": [int(r.q0500_out_before), int(r.q0500_out_after)],
            "p90_out": [int(r.q0900_out_before), int(r.q0900_out_after)],
            "p_ppm": [int(r.p_ppm_before), int(r.p_ppm_after)],
            "band": [r.band_before, r.band_after],
        }
        for r in c.head(TOP_COUNTIES).itertuples()
    ]
    a = before.assets.merge(after.assets, on="section_id", suffixes=("_before", "_after"))
    a["delta_impact"] = a["expected_impact_after"] - a["expected_impact_before"]
    band_changes = int((a["band_before"] != a["band_after"]).sum())
    a = a.reindex(a["delta_impact"].abs().sort_values(ascending=False).index)
    assets = [
        {
            "section_id": r.section_id,
            "p_ppm": [int(r.p_ppm_before), int(r.p_ppm_after)],
            "band": [r.band_before, r.band_after],
            "expected_impact": [int(r.expected_impact_before), int(r.expected_impact_after)],
        }
        for r in a.head(TOP_ASSETS).itertuples()
    ]
    shares_before = {s.action_id: s for s in before.actions}
    actions = []
    for s in after.actions:
        b = shares_before.get(s.action_id)
        old = b.share_ppm if b else None
        crossed = old is not None and (old >= threshold) != (s.share_ppm >= threshold)
        actions.append(
            {
                "action_id": s.action_id,
                "decision_case_ids": list(s.decision_case_ids),
                "share_ppm": [old, s.share_ppm],
                "crossed_act_now_threshold": crossed,
                "rule": s.rule,
            }
        )
    return {
        "scenario": after.scenario,
        "from_advisory": before.advisory_label,
        "to_advisory": after.advisory_label,
        "from_forecast_id": before.forecast_id,
        "to_forecast_id": after.forecast_id,
        "footprint_mean_out": [int(before.counties["mean_out"].sum()), int(after.counties["mean_out"].sum())],
        "footprint_p90_out_sum": [
            int(before.counties["q0900_out"].sum()),
            int(after.counties["q0900_out"].sum()),
        ],
        "asset_band_changes": band_changes,
        "act_now_threshold_ppm": threshold,
        "counties": counties,
        "assets": assets,
        "actions": actions,
        "label": "S (synthetic replay; model trained on real storms without Helene)",
    }
