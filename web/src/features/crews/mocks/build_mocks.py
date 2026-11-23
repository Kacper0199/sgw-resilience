"""Writes the MSW fixtures of the Water and Crews pages from committed artefacts.

Usage (repository root):
  uv run sgw optimise plan --advisory N --out <plan.json>      # about 95 s, heavy lock
  uv run python web/src/features/crews/mocks/build_mocks.py <plan.json>
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import yaml

from sgw.agent.graphs.water import SENSITIVITY_LAGS_MIN, breach_p_at, generator_residual_p
from sgw.common import numbers as nm

ROOT = Path(__file__).resolve().parents[5]
WATER = ROOT / "web/src/features/water/mocks"
CREWS = ROOT / "web/src/features/crews/mocks"
ppm = lambda p: round(p * 1_000_000)  # noqa: E731


def dump(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print("wrote", path.relative_to(ROOT))


def register() -> None:
    table = json.loads((ROOT / "data/artefacts/water_twin/ps17_clock_members.json").read_text())
    residual = generator_residual_p(float(nm.value("policy_water_continuity_horizon_h")))
    lag = float(table["lead_min"]["generator.hookup_lead_min"])
    assessments = []
    for name in ("N", "N+1"):
        adv = table["advisories"][name]
        members = adv["members"]
        loss = statistics.fmean(float(m["p_loss_final"]) for m in members)
        breach = breach_p_at(members, lag, residual)
        assessments.append(
            {
                "advisory": name,
                "issued_utc": adv["issued_utc"],
                "power_loss_p_ppm": ppm(loss),
                "breach_given_loss_p_ppm": ppm(breach / loss),
                "breach_p_ppm": ppm(breach),
            }
        )
    members = table["advisories"]["N+1"]["members"]
    sensitivity = [
        {"hookup_lag_min": s, "breach_p_ppm": ppm(breach_p_at(members, s, residual))}
        for s in SENSITIVITY_LAGS_MIN
    ] + [{"hookup_lag_min": int(lag), "breach_p_ppm": assessments[1]["breach_p_ppm"]}]
    row = {
        "advisory_id": "BWA-WZ-PS17-CEDARFALL-PRELANDFALL",
        "state": "SC",
        "zone_id": "WZ-PS17-CEDARFALL",
        "station_id": "PS-17",
        "kind": "pre_landfall",
        "clause_ids": ["SC-A2", "SC-P1"],
        "policy_key": "policy_pre_landfall_breach_p",
        "assessments": assessments,
        "sensitivity": sensitivity,
        "due_utc": "2024-09-27T03:10:00Z",
        "status": "proposed",
        "proposal_id": "PRP-BWN-READY",
        "decision_case_id": "DC-D4-BWN-READY",
    }
    dump(WATER / "register.json", {"advisories": [row]})

    rules = yaml.safe_load((ROOT / "src/sgw/rules/bwa_rules.yaml").read_text())
    clauses = [
        {
            "clause_id": cid,
            "state": c["state"],
            "summary": c["summary"],
            "citation": c["citation"],
            "sop": c.get("sop"),
            "label": c["label"],
        }
        for cid, c in rules["clauses"].items()
    ]
    dump(WATER / "rules.json", {"version": rules["version"], "clauses": clauses})


def anomaly_report() -> None:
    a = json.loads((ROOT / "data/artefacts/water_twin/anomaly_dev.json").read_text())
    bench = a["results"]["dev_bench"]
    m, base = bench["metrics"], bench["baseline_metrics"]
    rows = [
        {
            "metric": "anomaly.recall_raw",
            "value": m["recall"],
            "unit": "share of seeded faults found",
            "n": m["faults"],
            "split": "dev",
            "label": "C",
            "baseline_name": "station low-pressure alarm alone",
            "baseline_value": base["recall"],
            "threshold": a["targets"]["recall"],
            "direction": "higher_is_better",
            "passed": False,
            "ci_low": m["recall_wilson95"][0],
            "ci_high": m["recall_wilson95"][1],
        },
        {
            "metric": "anomaly.false_alarms_per_100_asset_days",
            "value": m["fa_per_100_asset_days"],
            "unit": "false alarms per 100 asset-days",
            "n": int(m["asset_days"]),
            "split": "dev",
            "label": "C",
            "baseline_name": "station low-pressure alarm alone",
            "baseline_value": base["fa_per_100_asset_days"],
            "threshold": a["targets"]["fa_per_100_asset_days"],
            "direction": "lower_is_better",
            "passed": True,
            "ci_low": None,
            "ci_high": None,
        },
        {
            "metric": "anomaly.spoof_flagged_share",
            "value": m["spoof_flagged"] / m["spoof_cases"],
            "unit": "share of spoofed readings flagged",
            "n": m["spoof_cases"],
            "split": "dev",
            "label": "C",
            "baseline_name": "station low-pressure alarm alone",
            "baseline_value": base["spoof_flagged"] / base["spoof_cases"],
            "threshold": 1.0,
            "direction": "higher_is_better",
            "passed": False,
            "ci_low": None,
            "ci_high": None,
        },
    ]
    for kind, v in m["by_kind"].items():
        b = base["by_kind"][kind]
        rows.append(
            {
                "metric": f"anomaly.recall.{kind}",
                "value": v["detected"] / v["n"],
                "unit": "share of seeded faults of this kind found",
                "n": v["n"],
                "split": "dev",
                "label": "C",
                "baseline_name": "station low-pressure alarm alone",
                "baseline_value": b["detected"] / b["n"],
                "threshold": a["targets"]["recall"],
                "direction": "higher_is_better",
                "passed": v["detected"] / v["n"] >= a["targets"]["recall"],
                "ci_low": None,
                "ci_high": None,
            }
        )
    caveats = [
        "A leak while the tank stays full changes neither pressure nor level, so it needs flow metering.",
        "When two sensors disagree the checks cannot say which one is wrong, "
        "except where a third sensor exists.",
    ]
    assert any(s.startswith("a leak while") for s in a["limitations"])
    assert any(s.startswith("pairwise A8") for s in a["limitations"])
    dump(
        WATER / "anomaly-report.json",
        {
            "name": "anomaly_a7_a8",
            "schema_version": 1,
            "command": a["command"],
            "metrics": rows,
            "caveats": caveats,
        },
    )


def crews(plan_path: Path) -> None:
    d = json.loads(plan_path.read_text())
    keep = ("COA-A", "COA-B", "COA-C", "P50")
    plans = []
    for p in d["plans"]:
        if p["plan_id"] not in keep:
            continue
        item = {
            k: p[k]
            for k in (
                "plan_id",
                "title",
                "trade_off",
                "risk",
                "early_mutual_aid_groups",
                "early_mutual_aid_persons",
                "own_groups_staged",
                "committed_early_mutual_aid_usd_per_day",
                "expected_cost",
                "yards",
                "out_of_sample",
                "synthetic_truth_customer_hours",
                "observed_scale_stress_customer_hours",
            )
        }
        if "envelope" in p:
            item["params"] = p["params"]
            item["envelope"] = p["envelope"]
            item["resource_request_id"] = (
                p["resource_request"]["MessageID"] if p["resource_request"] else None
            )
        plans.append(item)
    order = ("P50", "COA-A", "COA-B", "COA-C")
    plans.sort(key=lambda x: order.index(x["plan_id"]))
    doc = {
        k: d[k]
        for k in (
            "engine_version",
            "scenario",
            "advisory",
            "issued_utc",
            "landfall_utc",
            "objective",
            "size",
            "crews",
            "planning_band_check",
            "staging_rules",
            "vss",
            "evpi",
            "recommendation",
            "recommendation_note",
        )
    }
    doc["forecast_scale_band"] = {
        k: d["forecast_scale_band"][k] for k in ("k_low", "k_high", "observed_scale_stress_k")
    }
    doc["plans"] = plans
    dump(CREWS / "plan.json", doc)

    q = json.loads((ROOT / "data/artefacts/cv/review_queue.json").read_text())
    case_ids = {pid for c in q["cases"] for pid in c["photo_ids"]}
    rows = [r for r in q["rows"] if r["rank"] <= 12 or r["image_id"] in case_ids]
    damage = {
        k: q[k]
        for k in (
            "cases",
            "honest_miss",
            "imagery_note",
            "review_note",
            "model_id",
            "model_revision",
            "seeded_order",
            "acceptance_history",
        )
    }
    damage["rows"] = rows
    damage["total_photos"] = len(q["rows"])
    dump(CREWS / "damage.json", damage)
    ref = json.loads((ROOT / "evals/reports/ladi_reference.json").read_text())
    dump(
        CREWS / "ladi-report.json",
        {"name": ref["name"], "schema_version": ref["schema_version"], "metrics": ref["metrics"]},
    )


if __name__ == "__main__":
    register()
    anomaly_report()
    crews(Path(sys.argv[1]))
