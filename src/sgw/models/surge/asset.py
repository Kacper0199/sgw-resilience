"""Pipeline asset `surge.outages`: the outage surges in force at the run's scenario time, with data quality
checks (`dq_check` rows) and a freshness rule on the EAGLE-I series behind them. Registered through
`sgw.pipeline.runner.ASSET_MODULES`; opt-in per run with `SGW_SURGE_SCENARIO=helene` in the run env (a no-op
otherwise). Reads only committed artefacts; writes only the runner's `pipeline_run` and `dq_check` rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import psycopg

from sgw.models.surge.read import SurgeUnavailable, list_outage_surges, scenario_data
from sgw.pipeline.context import RunContext
from sgw.pipeline.registry import AssetResult, CheckResult, asset

FRESHNESS_S = 1800
COUNTIES = 123
SCENARIO_ENV = "SGW_SURGE_SCENARIO"
GAP_WARN_SHARE = 0.05
DAY = timedelta(hours=24)


def checks_at(scenario: str, at: datetime) -> tuple[int, list[CheckResult]]:
    try:
        report = list_outage_surges(at, scenario=scenario)
    except SurgeUnavailable as exc:
        return 0, [CheckResult("surge.series_available", "warn", False, str(exc))]
    sc = scenario_data(scenario)
    recent = (sc.times > report.data_through - DAY) & (sc.times <= report.data_through)
    gap_share = float(np.isnan(sc.x[recent]).all(axis=1).mean()) if recent.any() else 1.0
    lag_s = (at - report.data_through).total_seconds()
    flagged = sum(1 for s in report.surges if s.dq_flags)
    return report.surges_total, [
        CheckResult(
            "surge.counties_complete",
            "error",
            report.counties_monitored == COUNTIES,
            f"{report.counties_monitored} of {COUNTIES}",
        ),
        CheckResult(
            "surge.feed_gap_share_24h",
            "warn",
            gap_share <= GAP_WARN_SHARE,
            f"{gap_share:.3f} of 15-min slots",
        ),
        CheckResult(
            "surge.series_fresh", "error", lag_s <= FRESHNESS_S, f"{lag_s:.0f} s behind", FRESHNESS_S
        ),
        CheckResult("surge.dq_flagged", "warn", flagged == 0, f"{flagged} surges with data-quality flags"),
    ]


@asset("surge.outages", freshness_limit_s=FRESHNESS_S)
def surge_outages(ctx: RunContext, conn: psycopg.Connection) -> AssetResult:
    """Outage surges detected by the EAGLE-I CUSUM detector at the run's scenario time (G1)."""
    scenario = ctx.env.get(SCENARIO_ENV)
    if not scenario:
        return AssetResult(watermarks={"skipped": f"{SCENARIO_ENV} not set"})
    at = ctx.as_of or ctx.now
    n, checks = checks_at(str(scenario), at)
    return AssetResult(rows_out=n, watermarks={"scenario": scenario, "as_of": at.isoformat()}, checks=checks)
