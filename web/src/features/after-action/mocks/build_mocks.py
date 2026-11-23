"""Regenerates the after-action feature mocks: `uv run python <this file>` from the repo root."""

import json
from pathlib import Path

from sgw.reports import sc_103_314

OUT = Path(__file__).parent
ROOT = Path(__file__).resolve().parents[5]
SHOWN = 12


def record(r: sc_103_314.InterruptionRecord) -> dict[str, object]:
    return {
        "area_id": r.area_id,
        "area_kind": r.area_kind,
        "county_code": r.county_code,
        "started_at": r.started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "restored_at": r.restored_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_h": r.duration_h,
        "customers_interrupted": r.customers_interrupted,
        "max_gust_ms": r.max_gust_ms,
        "cause": r.cause,
        "report_required": r.report_required,
    }


def main() -> None:
    report = sc_103_314.build()
    reportable = report.reportable
    notes = [
        "Notice to the Commission and the ORS: times are not held by the platform; enter them before filing.",
        "Restored means the last customer of the area's damaged sections back on supply in the replay.",
        "Counties stand in for the rule's major communities (assumption); the filer confirms the areas.",
    ]
    (OUT / "sc-report.json").write_text(
        json.dumps(
            {
                "citation": report.citation,
                "source_note": report.source_note,
                "label": report.label,
                "threshold_h": report.threshold_h,
                "event_name": report.event_name,
                "filed": False,
                "summary": sc_103_314.interruption_summary(report),
                "system": record(report.system),
                "counties": [record(r) for r in reportable[:SHOWN]],
                "counties_reportable": len(reportable),
                "counties_total": len(report.counties),
                "filer_notes": notes,
                "markdown": sc_103_314.render_markdown(report),
            },
            indent=2,
        )
        + "\n"
    )
    card = json.loads((ROOT / "data/artefacts/evals/etr_story_scorecard.json").read_text())
    keep = ("estimate_id", "region_id", "scope", "as_of_utc", "actual_utc", "p50_error_h", "abs_error_h")
    keep += ("analog_abs_error_h", "in_p25_p75", "in_p10_p90")
    (OUT / "scorecard.json").write_text(
        json.dumps(
            {
                "name": card["name"],
                "label": card["metrics"][0]["label"],
                "actual_label": card["actual_label"],
                "metrics": [
                    {
                        k: m[k]
                        for k in (
                            "metric",
                            "value",
                            "unit",
                            "n",
                            "baseline_value",
                            "baseline_name",
                            "direction",
                            "passed",
                        )
                    }
                    for m in card["metrics"]
                ],
                "estimates": [{k: e[k] for k in keep} for e in card["estimates"]],
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
