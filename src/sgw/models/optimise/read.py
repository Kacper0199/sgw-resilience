"""Read of the published crew plan (WP-16 `crew_plan` snapshot) for the API: the P50 plan beside the SAA
courses of action, envelope bounds, VSS and EVPI, as stored by the optimise job. Solver internals, SAA
replications and the full EDXL resource request stay in the snapshot; the API gives the request's id only.
Plan ids and the snapshot kind repeat `coa.COA_IDS` and `job.SNAPSHOT_KIND` so the API does not import the
solver stack; a test pins them equal."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from sgw.contracts.api_models import CrewPlanDocument, Provenance
from sgw.contracts.vocab import NumberLabel

SNAPSHOT_KIND = "crew_plan"
PLAN_ORDER = ("P50", "COA-A", "COA-B", "COA-C")
LABEL = "S (synthetic Helene replay); SAA over the A2 forecast scenarios; SGW policy parameters assumed"
PLAN_KEYS = (
    "plan_id",
    "title",
    "trade_off",
    "risk",
    "early_mutual_aid_groups",
    "early_mutual_aid_persons",
    "own_groups_staged",
    "committed_early_mutual_aid_usd_per_day",
    "synthetic_truth_customer_hours",
    "observed_scale_stress_customer_hours",
    "yards",
    "params",
    "envelope",
)
OUTCOME_KEYS = (
    "n",
    "expected_customer_hours",
    "p90_customer_hours",
    "cvar90_customer_hours",
    "expected_idle_early_mutual_aid_persons",
    "expected_late_mutual_aid_persons",
)
COST_KEYS = ("total_mutual_aid_usd", "total_mutual_aid_person_days", "usd_per_customer_hour_avoided_vs_p50")


class NotPublished(LookupError):
    """No crew plan was published at or before the scenario time."""


def _plan(p: dict[str, Any]) -> dict[str, Any]:
    request = p.get("resource_request")
    item = {k: p[k] for k in PLAN_KEYS if k in p}
    item["expected_cost"] = {k: p["expected_cost"][k] for k in COST_KEYS if k in p["expected_cost"]}
    item["out_of_sample"] = {k: p["out_of_sample"][k] for k in OUTCOME_KEYS if k in p["out_of_sample"]}
    if "resource_request_id" in p:
        item["resource_request_id"] = p["resource_request_id"]
    elif isinstance(request, dict):
        item["resource_request_id"] = request.get("MessageID")
    return item


def project(snapshot_id: str, as_of: datetime, doc: dict[str, Any]) -> CrewPlanDocument:
    plans = sorted(
        (_plan(p) for p in doc["plans"] if p["plan_id"] in PLAN_ORDER),
        key=lambda p: PLAN_ORDER.index(p["plan_id"]),
    )
    band = doc["forecast_scale_band"]
    evpi = doc["evpi"]
    return CrewPlanDocument.model_validate(
        {
            "snapshot_id": snapshot_id,
            **{
                k: doc[k]
                for k in (
                    "engine_version",
                    "scenario",
                    "advisory",
                    "issued_utc",
                    "landfall_utc",
                    "objective",
                    "size",
                    "planning_band_check",
                    "staging_rules",
                    "vss",
                    "recommendation_note",
                )
            },
            "crews": {
                k: doc["crews"][k] for k in ("own_groups", "own_group_persons", "mutual_aid_group_persons")
            },
            "forecast_scale_band": {k: band[k] for k in ("k_low", "k_high", "observed_scale_stress_k")},
            "evpi": {k: evpi[k] for k in ("in_sample", "out_of_sample", "out_of_sample_n")},
            "plans": plans,
            "recommendation": None,
            "provenance": Provenance(
                source=f"snapshot:{snapshot_id}",
                model_id=str(doc["engine_version"]),
                as_of=as_of,
                label=NumberLabel.S,
                detail=LABEL,
            ),
        }
    )


async def crew_plan(
    conn: AsyncConnection[Any], scenario: str, at: datetime, advisory: str | None = None
) -> CrewPlanDocument:
    sql = (
        "SELECT snapshot_id, as_of, output FROM snapshot WHERE kind = %s AND output->>'scenario' = %s"
        " AND as_of <= %s"
    )
    args: list[Any] = [SNAPSHOT_KIND, scenario, at]
    if advisory is not None:
        sql += " AND output->>'advisory' = %s"
        args.append(advisory)
    sql += " ORDER BY as_of DESC, snapshot_id DESC LIMIT 1"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, args)
        row = await cur.fetchone()
    if row is None:
        which = f"for advisory {advisory} " if advisory else ""
        raise NotPublished(
            f"no crew plan {which}published at or before {at:%Y-%m-%dT%H:%MZ};"
            " run `uv run sgw optimise enqueue` then `uv run sgw optimise work`"
        )
    return project(row["snapshot_id"], row["as_of"], row["output"])
