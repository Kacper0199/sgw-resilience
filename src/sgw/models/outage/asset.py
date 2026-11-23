"""Pipeline asset `risk.snapshot`: one risk publish per pipeline run at the run's scenario time, with its data
quality checks (`dq_check` rows) and a 15-min freshness rule. Registered through
`sgw.pipeline.runner.ASSET_MODULES`; opt-in per run with `SGW_RISK_SCENARIO=<scenario with a hazard ensemble>`
in the run env (a no-op otherwise, so replays of scenarios without ensembles are unchanged)."""

from __future__ import annotations

import psycopg

from sgw.models.outage.publisher import publish_tick
from sgw.pipeline.context import RunContext
from sgw.pipeline.registry import AssetResult, CheckResult, asset

FRESHNESS_S = 900
COUNTIES = 123
SCENARIO_ENV = "SGW_RISK_SCENARIO"


@asset("risk.snapshot", deps=("ledger.relay",), freshness_limit_s=FRESHNESS_S)
def risk_snapshot(ctx: RunContext, conn: psycopg.Connection) -> AssetResult:
    """County fans, asset risk and no-regret shares of the advisory in force (RiskSnapshotPublished)."""
    scenario = ctx.env.get(SCENARIO_ENV)
    if not scenario:
        return AssetResult(watermarks={"skipped": f"{SCENARIO_ENV} not set"})
    at = ctx.as_of or ctx.now
    result = publish_tick(conn, at, str(scenario))
    if result.snapshot_id is None:
        return AssetResult(
            checks=[CheckResult("risk.advisory_in_force", "warn", False, f"no advisory at {at}")]
        )
    row = conn.execute(
        "SELECT count(*) FILTER (WHERE level = 'county'),"
        " count(*) FILTER (WHERE p_ppm NOT BETWEEN 0 AND 1000000) FROM risk WHERE snapshot_id = %s",
        (result.snapshot_id,),
    ).fetchone()
    counties, bad = (int(row[0]), int(row[1])) if row else (0, 0)
    return AssetResult(
        rows_out=counties,
        watermarks={"snapshot_id": result.snapshot_id, "advisory": result.advisory_label},
        checks=[
            CheckResult("risk.counties_complete", "error", counties == COUNTIES, f"{counties} of {COUNTIES}"),
            CheckResult("risk.p_in_range", "error", bad == 0, f"{bad} rows out of range"),
            CheckResult(
                "risk.event_in_ledger",
                "error",
                result.event_seq is not None,
                f"ledger_seq {result.event_seq}",
                FRESHNESS_S,
            ),
            CheckResult(
                "risk.tick_latency", "warn", result.seconds < 60.0, f"{result.seconds:.2f} s (limit 60 s)"
            ),
        ],
    )
