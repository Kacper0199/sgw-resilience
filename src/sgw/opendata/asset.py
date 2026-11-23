"""Pipeline asset `opendata.helene`: data-quality checks (`dq_check` rows) over the five derived open-data
files and a freshness rule per observed source at the run's scenario time (ASOS 1 h, USGS 2 h: older than
that, the peak so far may be missing a later report). Registered through `sgw.pipeline.runner.ASSET_MODULES`;
reads files only, no database rows."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from sgw.opendata import read
from sgw.opendata.build import OUT_ROOT, WIND_DATA_END, WINDOW_END, WINDOW_START
from sgw.pipeline.context import RunContext
from sgw.pipeline.registry import AssetResult, CheckResult, asset

FRESHNESS_S = {"iem-asos": 3600, "usgs-nwis": 7200}
ASSET_FRESHNESS_S = 3600
MIN_GAUGES = 100
STATIONS = 6
DECLARATIONS = {"DR-4829-SC", "DR-4830-GA"}
MAX_STAGE_FT = 200.0
MAX_GUST_KT = 150


def _span(rows: list[list[Any]]) -> bool:
    return all(0 <= p[0] < (WINDOW_END - WINDOW_START).total_seconds() / 60 for p in rows)


def checks_for(root: Path, at: datetime) -> list[CheckResult]:
    load = read.load.__wrapped__
    gauges = load("gauges", root)["gauges"]
    wind = load("wind", root)["stations"]
    warnings = load("warnings", root)
    decl = load("declarations", root)["declarations"]
    events = load("events", root)["events"]
    rises = [p for g in gauges for p in g["rise"]]
    gusts = [p for s in wind for p in s["rise"]]
    checks = [
        CheckResult("opendata.gauges_count", "error", len(gauges) >= MIN_GAUGES, f"{len(gauges)} gauges"),
        CheckResult(
            "opendata.gauge_stage_range",
            "error",
            all(-5 <= p[1] <= MAX_STAGE_FT for p in rises) and _span(rises),
            f"{len(rises)} rise points",
        ),
        CheckResult(
            "opendata.gauge_rise_monotone",
            "error",
            all(
                all(a[0] < b[0] and a[1] < b[1] for a, b in zip(g["rise"], g["rise"][1:], strict=False))
                for g in gauges
            ),
            "running maximum only rises",
        ),
        CheckResult("opendata.wind_stations", "error", len(wind) == STATIONS, f"{len(wind)} stations"),
        CheckResult(
            "opendata.gust_range",
            "error",
            all(0 < p[1] <= MAX_GUST_KT and -1 <= p[2] < 360 for p in gusts) and _span(gusts),
            f"{len(gusts)} gust points",
        ),
        CheckResult(
            "opendata.warning_zones_resolve",
            "error",
            all(w.get("zone", "") in warnings["zones"] or "geometry" in w for w in warnings["warnings"]),
            f"{len(warnings['warnings'])} warnings, {len(warnings['zones'])} zones",
        ),
        CheckResult(
            "opendata.warning_windows",
            "error",
            all(w["from"] < w["to"] for w in warnings["warnings"]),
            "every warning expires after it starts",
        ),
        CheckResult(
            "opendata.declarations",
            "error",
            {d["id"] for d in decl} == DECLARATIONS
            and all(set(d["footprint_fips"]) <= set(read.county_names()) for d in decl),
            ", ".join(sorted(d["id"] for d in decl)),
        ),
        CheckResult("opendata.storm_events", "error", len(events) > 0, f"{len(events)} events"),
    ]
    m = (at - WINDOW_START).total_seconds() / 60
    if 0 <= m < WIND_DATA_END:
        silent = [s.station for s in read.stations_at(at) if s.silent_since_utc is not None]
        checks.append(
            CheckResult(
                "freshness.iem-asos",
                "warn",
                not silent,
                f"silent: {', '.join(silent)}" if silent else "all 6 stations reporting",
                FRESHNESS_S["iem-asos"],
            )
        )
        stale = sum(
            1 for g in gauges if g["last"] is not None and g["last"] < m - FRESHNESS_S["usgs-nwis"] / 60
        )
        checks.append(
            CheckResult(
                "freshness.usgs-nwis",
                "warn",
                stale == 0,
                f"{stale} of {len(gauges)} gauges without a report in 2 h",
                FRESHNESS_S["usgs-nwis"],
            )
        )
    return checks


@asset("opendata.helene", freshness_limit_s=ASSET_FRESHNESS_S)
def opendata_helene(ctx: RunContext, conn: psycopg.Connection) -> AssetResult:
    """Helene open data (USGS gauges, ASOS wind, NWS warnings, FEMA declarations, NCEI Storm Events)."""
    checks = checks_for(OUT_ROOT, ctx.as_of or ctx.now)
    return AssetResult(rows_out=len(checks), checks=checks)
