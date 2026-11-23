"""Read side of Health: feed freshness, pipeline runs, DQ results, asset lineage, model cards with their
evaluation, and LLM usage and cost from `llm_call`. Transport-free; every query is parameterised and paged.

Freshness never shows stale data as current: a feed with no ingest lag recorded is stale (K1 `feed_health`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from sgw.common.sources import display_name
from sgw.contracts.api_models import DqCheckOut, FeedHealthItem, ModelCard, PipelineRunOut
from sgw.ops.errors import OpsNotFound

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_DIR = REPO_ROOT / "evals" / "reports"
ARTEFACTS_DIR = REPO_ROOT / "data" / "artefacts" / "models"
MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
MAX_ROWS = 500
MICROS = 1_000_000
INGEST_ASSET = "ingest.feeds"
REPLAY_RUN_PREFIX = "replay."


def _limit(limit: int | None) -> int:
    return MAX_ROWS if limit is None else max(1, min(MAX_ROWS, limit))


def feeds(conn: psycopg.Connection[Any], at: datetime | None = None) -> list[FeedHealthItem]:
    """Feed freshness: at the replay clock `at` when given (`sgw.ops.freshness`), else the K1 view."""
    if at is not None:
        from sgw.ops import freshness

        current = freshness.feeds_at(conn, at)
        items = [freshness.feed_health(f, at, display_name(f.source_id)) for f in current]
        return sorted(items, key=lambda f: (not f.stale, f.source_id))
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT source_id, feed_mode, ingest_lag_s, product_age_s, freshness_limit_s, stale"
            " FROM feed_health ORDER BY stale DESC, source_id"
        ).fetchall()
    from sgw.ops.freshness import feed_status

    return [
        FeedHealthItem.model_validate(
            {
                **r,
                "display_name": display_name(r["source_id"]),
                "status": feed_status(r["product_age_s"] is not None, bool(r["stale"])),
            }
        )
        for r in rows
    ]


def runs(
    conn: psycopg.Connection[Any], *, asset: str | None = None, limit: int | None = None
) -> list[PipelineRunOut]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT run_id, asset, status, started_at, finished_at, rows_in, rows_out, rows_quarantined,"
            " error"
            " FROM pipeline_run WHERE (%(asset)s::text IS NULL OR asset = %(asset)s)"
            " ORDER BY started_at DESC, run_id DESC LIMIT %(limit)s",
            {"asset": asset, "limit": _limit(limit)},
        ).fetchall()
    return [PipelineRunOut.model_validate(r) for r in rows]


def dq_checks(
    conn: psycopg.Connection[Any],
    *,
    asset: str | None = None,
    failed_only: bool = False,
    limit: int | None = None,
    at: datetime | None = None,
) -> list[DqCheckOut]:
    """Stored DQ results. With the replay clock `at`, the ingest asset's freshness and late-arrival
    checks are evaluated at `at` instead of read from the run that loaded the whole window."""
    replaced: set[str] = set()
    current: list[DqCheckOut] = []
    if at is not None:
        from sgw.ops import freshness

        current = [
            c
            for c in freshness.checks_at(conn, at)
            if (asset is None or c.asset == asset) and (not failed_only or not c.passed)
        ]
        replaced = freshness.replaced_check_names([f.source_id for f in freshness.feeds_at(conn, at)])
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT check_id, asset, name, severity, passed, observed, checked_at FROM dq_check"
            " WHERE (%(asset)s::text IS NULL OR asset = %(asset)s) AND (NOT %(failed)s OR NOT passed)"
            " AND NOT (asset = %(ingest)s AND name = ANY(%(replaced)s))"
            " ORDER BY checked_at DESC, check_id DESC LIMIT %(limit)s",
            {
                "asset": asset,
                "failed": failed_only,
                "limit": _limit(limit),
                "ingest": INGEST_ASSET,
                "replaced": sorted(replaced),
            },
        ).fetchall()
    return [*current, *(DqCheckOut.model_validate(r) for r in rows)][: _limit(limit)]


def lineage(conn: psycopg.Connection[Any], at: datetime | None = None) -> list[dict[str, Any]]:
    """Every registered pipeline asset with its upstream and downstream assets, freshness rule, last run
    and DQ tally of that run (K3 `listPipelineAssets`, untyped in v1.1). With the replay clock `at` the
    ingest asset's tally counts its freshness and late-arrival checks at `at`, as `dq_checks` lists them.
    `skipped` marks a run that did nothing (an opt-in asset whose scenario env was not set); `replay` a run
    of the replay that loaded the whole scenario window when the demo was built."""
    from sgw.pipeline.registry import REGISTRY
    from sgw.pipeline.runner import load_assets

    load_assets()
    downstream: dict[str, list[str]] = {name: [] for name in REGISTRY}
    for spec in REGISTRY.values():
        for dep in spec.deps:
            downstream.setdefault(dep, []).append(spec.name)
    with conn.cursor(row_factory=dict_row) as cur:
        last = {
            r["asset"]: r
            for r in cur.execute(
                "SELECT DISTINCT ON (r.asset) r.asset, r.run_id, r.status, r.started_at, r.finished_at,"
                " r.rows_in, r.rows_out, r.rows_quarantined, r.watermarks ? 'skipped' AS skipped,"
                " (SELECT count(*) FROM dq_check d WHERE d.run_id = r.run_id) AS checks,"
                " (SELECT count(*) FROM dq_check d WHERE d.run_id = r.run_id AND NOT d.passed"
                "  AND d.severity = 'error') AS errors,"
                " (SELECT count(*) FROM dq_check d WHERE d.run_id = r.run_id AND NOT d.passed"
                "  AND d.severity = 'warn') AS warnings"
                " FROM pipeline_run r ORDER BY r.asset, r.started_at DESC, r.run_id DESC"
            ).fetchall()
        }
    out: list[dict[str, Any]] = []
    for name in sorted(REGISTRY):
        spec = REGISTRY[name]
        run = last.get(name)
        out.append(
            {
                "name": name,
                "description": spec.description,
                "upstream": list(spec.deps),
                "downstream": sorted(downstream.get(name, [])),
                "freshness_limit_s": spec.freshness_limit_s,
                "last_run": None
                if run is None
                else {
                    "run_id": run["run_id"],
                    "status": run["status"],
                    "started_at": _iso(run["started_at"]),
                    "finished_at": _iso(run["finished_at"]),
                    "rows_in": run["rows_in"],
                    "rows_out": run["rows_out"],
                    "rows_quarantined": run["rows_quarantined"],
                    "dq": _tally_at(conn, run, at)
                    if name == INGEST_ASSET and at is not None
                    else {
                        "checks": run["checks"],
                        "errors": run["errors"],
                        "warnings": run["warnings"],
                    },
                    "skipped": bool(run["skipped"]),
                    "replay": str(run["run_id"]).startswith(REPLAY_RUN_PREFIX),
                },
            }
        )
    return out


def _tally_at(conn: psycopg.Connection[Any], run: Mapping[str, Any], at: datetime) -> dict[str, int]:
    from sgw.ops import freshness

    current = freshness.checks_at(conn, at)
    sources = [c.name.removeprefix("freshness.") for c in current if c.name.startswith("freshness.")]
    replaced = freshness.replaced_check_names(sources)
    stored = conn.execute(
        "SELECT severity, passed FROM dq_check WHERE run_id = %s AND NOT (name = ANY(%s))",
        (run["run_id"], sorted(replaced)),
    ).fetchall()
    results = [(str(r[0]), bool(r[1])) for r in stored] + [(c.severity, c.passed) for c in current]
    return {
        "checks": len(results),
        "errors": sum(1 for sev, ok in results if not ok and sev == "error"),
        "warnings": sum(1 for sev, ok in results if not ok and sev == "warn"),
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def models(conn: psycopg.Connection[Any]) -> list[ModelCard]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT name, version, alias, data_hash, eval_report FROM model_version ORDER BY name, version"
        ).fetchall()
    return [ModelCard.model_validate(r) for r in rows]


def _safe_file(base: Path, relative: str | None) -> Path | None:
    if not relative:
        return None
    candidate = (REPO_ROOT / relative).resolve()
    if not candidate.is_relative_to(base.resolve()) or not candidate.is_file():
        return None
    return candidate


def _card_path(name: str) -> Path | None:
    """`data/artefacts/models/<name>/card.json`, else one level down under a model family folder
    (`data/artefacts/models/outage/<name>/card.json`); `name` is already checked against `MODEL_NAME`."""
    direct = _safe_file(ARTEFACTS_DIR, f"data/artefacts/models/{name}/card.json")
    if direct is not None:
        return direct
    nested = sorted(ARTEFACTS_DIR.glob(f"*/{name}/card.json"))
    return _safe_file(ARTEFACTS_DIR, str(nested[0].relative_to(REPO_ROOT))) if nested else None


def _read_json(path: Path | None) -> Any:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def model_evaluation(conn: psycopg.Connection[Any], name: str) -> dict[str, Any]:
    """The model card (registry row, artefact card) and its evaluation: the K17 report metrics that carry
    the model's name, each with n, split and label as recorded. Reads only `evals/reports/` and
    `data/artefacts/models/`."""
    if not MODEL_NAME.fullmatch(name):
        raise OpsNotFound(f"no model named {name!r}", code="MODEL_NOT_FOUND")
    with conn.cursor(row_factory=dict_row) as cur:
        versions = cur.execute(
            "SELECT model_id, name, version, alias, data_hash, mlflow_run_id, metrics, eval_report"
            " FROM model_version WHERE name = %s ORDER BY version DESC",
            (name,),
        ).fetchall()
    if not versions:
        raise OpsNotFound(f"no model named {name!r}", code="MODEL_NOT_FOUND")
    current = next((v for v in versions if v["alias"] == "serving"), versions[0])
    report_path = _safe_file(REPORTS_DIR, current["eval_report"])
    report = _read_json(report_path)
    metrics: list[dict[str, Any]] = []
    if isinstance(report, Mapping):
        metrics = [dict(m) for m in report.get("metrics", []) if isinstance(m, Mapping)]
    card = _read_json(_card_path(name))
    return {
        "name": name,
        "serving": {k: current[k] for k in ("model_id", "version", "alias", "data_hash", "mlflow_run_id")},
        "versions": [{k: v[k] for k in ("model_id", "version", "alias")} for v in versions],
        "registry_metrics": current["metrics"],
        "eval_report": {
            "path": current["eval_report"] if report_path else None,
            "name": report.get("name") if isinstance(report, Mapping) else None,
            "created_at": report.get("created_at") if isinstance(report, Mapping) else None,
            "code_version": report.get("code_version") if isinstance(report, Mapping) else None,
            "metrics": metrics,
        },
        "card": card if isinstance(card, Mapping) else None,
    }


@dataclass(frozen=True)
class UsageFilter:
    since: datetime | None = None
    until: datetime | None = None
    run_id: str | None = None


USAGE_GROUPS = ("purpose", "node", "model", "mode", "wave")


def llm_usage(
    conn: psycopg.Connection[Any],
    *,
    group_by: tuple[str, ...] = ("purpose", "node", "model"),
    flt: UsageFilter,
) -> dict[str, Any]:
    """Calls, tokens, cost (USD from integer micros) and latency from `llm_call`, grouped by allowed
    columns only. Replay rows are counted but never billed; denied calls are counted separately."""
    groups = tuple(g for g in group_by if g in USAGE_GROUPS) or ("purpose",)
    cols = ", ".join(groups)
    where = (
        "(%(since)s::timestamptz IS NULL OR ts >= %(since)s)"
        " AND (%(until)s::timestamptz IS NULL OR ts < %(until)s)"
        " AND (%(run)s::text IS NULL OR run_id = %(run)s)"
    )
    params = {"since": flt.since, "until": flt.until, "run": flt.run_id}
    aggregates = (
        "count(*) AS calls, count(*) FILTER (WHERE billed) AS billed_calls,"
        " count(*) FILTER (WHERE mode = 'replay') AS replay_calls,"
        " count(*) FILTER (WHERE decision = 'deny') AS denied_calls,"
        " coalesce(sum(input_tokens), 0) AS input_tokens, coalesce(sum(output_tokens), 0) AS output_tokens,"
        " coalesce(sum(cache_read_input_tokens), 0) AS cache_read_input_tokens,"
        " coalesce(sum(cache_creation_input_tokens), 0) AS cache_creation_input_tokens,"
        " coalesce(sum(cost_usd_micros), 0) AS cost_usd_micros,"
        " percentile_disc(0.5) WITHIN GROUP (ORDER BY latency_ms) AS latency_p50_ms,"
        " percentile_disc(0.95) WITHIN GROUP (ORDER BY latency_ms) AS latency_p95_ms"
    )
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            f"SELECT {cols}, {aggregates} FROM llm_call WHERE {where} GROUP BY {cols} ORDER BY {cols}",  # noqa: S608
            params,
        ).fetchall()
        total_sql = f"SELECT {aggregates}, max(ts) AS last_call_at FROM llm_call WHERE {where}"  # noqa: S608
        total = cur.execute(total_sql, params).fetchone()
    for row in [*rows, total]:
        if row is not None:
            row["cost_usd"] = round(int(row["cost_usd_micros"]) / MICROS, 6)
    assert total is not None
    total["last_call_at"] = _iso(total["last_call_at"])
    return {"group_by": list(groups), "rows": rows, "total": total}
