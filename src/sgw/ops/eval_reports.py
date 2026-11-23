"""K17 evaluation reports by name for `GET /api/models/{name}/evaluation`.

Only the names in `REPORTS` are served, each from a fixed file (no path is built from the request). Most are
K17 files in `evals/reports/`; `anomaly_a7_a8` is assembled from the WP-13 dev artefact
(`data/artefacts/water_twin/anomaly_dev.json`) as K17-shaped rows, `passed` computed from value and threshold.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sgw.contracts.api_models import Provenance
from sgw.contracts.vocab import NumberLabel

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_DIR = REPO_ROOT / "evals" / "reports"
ANOMALY_ARTEFACT = REPO_ROOT / "data" / "artefacts" / "water_twin" / "anomaly_dev.json"
ANOMALY_BASELINE = "station low-pressure alarm alone"


def _k17(name: str) -> Callable[[], dict[str, Any]]:
    path = REPORTS_DIR / f"{name}.json"

    def read() -> dict[str, Any]:
        report: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        rows = report.get("metrics", [])
        return {
            **{k: report.get(k) for k in ("name", "schema_version", "created_at", "code_version", "command")},
            "llm_mode": report.get("llm_mode"),
            "metrics": rows,
            "caveats": list(report.get("caveats", [])),
            "provenance": Provenance(
                source=str(path.relative_to(REPO_ROOT)),
                as_of=_utc(report.get("created_at")),
                label=_label(rows),
                detail=_labels(rows),
            ).model_dump(mode="json"),
        }

    return read


def _utc(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def _label(rows: list[dict[str, Any]]) -> NumberLabel:
    """The report's K10 label: the one its rows share, else C (computed) with the mix in `detail`."""
    found = {str(r.get("label")) for r in rows if r.get("label")}
    return NumberLabel(found.pop()) if len(found) == 1 else NumberLabel.C


def _labels(rows: list[dict[str, Any]]) -> str:
    return ",".join(sorted({str(r.get("label")) for r in rows if r.get("label")})) or "unlabelled"


def _row(
    metric: str,
    value: float,
    unit: str,
    n: int,
    baseline: float,
    threshold: float,
    direction: str,
    ci: tuple[float, float] | None = None,
) -> dict[str, Any]:
    passed = value >= threshold if direction == "higher_is_better" else value <= threshold
    return {
        "metric": metric,
        "value": value,
        "unit": unit,
        "n": n,
        "split": "dev",
        "label": "C",
        "baseline_name": ANOMALY_BASELINE,
        "baseline_value": baseline,
        "threshold": threshold,
        "direction": direction,
        "passed": passed,
        "ci_low": ci[0] if ci else None,
        "ci_high": ci[1] if ci else None,
    }


def anomaly_a7_a8(path: Path = ANOMALY_ARTEFACT) -> dict[str, Any]:
    a = json.loads(path.read_text(encoding="utf-8"))
    bench = a["results"]["dev_bench"]
    m, base, target = bench["metrics"], bench["baseline_metrics"], a["targets"]
    recall = float(target["recall"])
    wilson = m.get("recall_wilson95")
    rows = [
        _row(
            "anomaly.recall_raw",
            m["recall"],
            "share of seeded faults found",
            int(m["faults"]),
            base["recall"],
            recall,
            "higher_is_better",
            (wilson[0], wilson[1]) if wilson else None,
        ),
        _row(
            "anomaly.false_alarms_per_100_asset_days",
            m["fa_per_100_asset_days"],
            "false alarms per 100 asset-days",
            int(m["asset_days"]),
            base["fa_per_100_asset_days"],
            float(target["fa_per_100_asset_days"]),
            "lower_is_better",
        ),
        _row(
            "anomaly.spoof_flagged_share",
            m["spoof_flagged"] / m["spoof_cases"],
            "share of spoofed readings flagged",
            int(m["spoof_cases"]),
            base["spoof_flagged"] / base["spoof_cases"],
            1.0,
            "higher_is_better",
        ),
    ]
    for kind, v in m["by_kind"].items():
        b = base["by_kind"][kind]
        rows.append(
            _row(
                f"anomaly.recall.{kind}",
                v["detected"] / v["n"],
                "share of seeded faults of this kind found",
                int(v["n"]),
                b["detected"] / b["n"],
                recall,
                "higher_is_better",
            )
        )
    return {
        "name": "anomaly_a7_a8",
        "schema_version": 1,
        "created_at": None,
        "code_version": None,
        "command": a["command"],
        "llm_mode": None,
        "metrics": rows,
        "caveats": [str(s) for s in a.get("limitations", [])],
        "provenance": Provenance(
            source=str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else path.name,
            model_id="sgw-anomaly-a7-a8",
            as_of=None,
            label=NumberLabel.C,
            detail=f"{a.get('label', 'synthetic')} {a.get('split', 'dev')} bench",
        ).model_dump(mode="json"),
    }


K17_FILES = (
    "outage_loso",
    "outage_loso_v2",
    "outage_loso_v3",
    "etr",
    "saa",
    "ladi_reference",
    "outage_surge",
    "anomaly_batadal",
)
REPORTS: dict[str, Callable[[], dict[str, Any]]] = {
    **{n: _k17(n) for n in K17_FILES},
    "anomaly_a7_a8": anomaly_a7_a8,
}


def report(name: str) -> dict[str, Any] | None:
    """The named report, or None when the name is not served or its file is missing."""
    read = REPORTS.get(name)
    if read is None:
        return None
    try:
        return {**read(), "report_name": name}
    except FileNotFoundError:
        return None


def with_k17_view(evaluation: dict[str, Any]) -> dict[str, Any]:
    """A registered model's evaluation in the one shape the UI reads: the K17 report fields (`report_name`,
    `metrics`, `caveats`, `created_at`, `code_version`, `provenance`) at the top level, the registry fields
    (`name`, `serving`, `versions`, `registry_metrics`, `card`) beside them, and `eval_report` kept as is."""
    ev = evaluation.get("eval_report") or {}
    named = report(str(ev["name"])) if ev.get("name") in REPORTS else None
    return {
        **evaluation,
        "schema_version": 1,
        "report_name": ev.get("name"),
        "created_at": ev.get("created_at"),
        "code_version": ev.get("code_version"),
        "metrics": ev.get("metrics", []),
        "caveats": named["caveats"] if named else [],
        "provenance": named["provenance"] if named else None,
    }
