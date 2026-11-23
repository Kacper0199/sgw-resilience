"""On-demand pipeline runs (K3 `runPipelineAsset`): one asset and its upstream assets, through WP-07's
runner with the scenario's replay adapters, so a run resumes from stored cursors and never repeats a source
event. Refused while the kill level or degraded mode removes pipeline runs (K3, M3 and above)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import psycopg

from sgw.contracts.api_models import PipelineRunOut
from sgw.contracts.vocab import FeedMode, RunMode
from sgw.ops import levels
from sgw.ops.control import ControlService
from sgw.ops.errors import OpsForbidden, OpsNotFound
from sgw.ops.health import runs

INGEST_ASSET = "ingest.feeds"


def known_assets() -> list[str]:
    from sgw.pipeline.registry import REGISTRY
    from sgw.pipeline.runner import load_assets

    load_assets()
    return sorted(REGISTRY)


def run_asset(
    conn: psycopg.Connection[Any],
    control: ControlService,
    name: str,
    *,
    scenario: str,
    env: Mapping[str, str],
) -> PipelineRunOut:
    if name not in known_assets():
        raise OpsNotFound(f"no pipeline asset named {name!r}", code="ASSET_NOT_FOUND")
    if not control.capabilities(conn)[levels.Capability.PIPELINE_RUNS]:
        raise OpsForbidden(
            "pipeline runs are paused at this kill level or degraded mode", code="PIPELINE_RUNS_PAUSED"
        )
    from sgw.ingest.adapters.registry import scenario_adapters
    from sgw.ingest.scenario import load_scenario
    from sgw.pipeline.context import RunContext
    from sgw.pipeline.registry import topo_order
    from sgw.pipeline.runner import run_pipeline

    plan = [spec.name for spec in topo_order([name])]
    loaded = load_scenario(scenario)
    modes = {h.feed_mode for h in loaded.headers}
    horizon = max((e.scenario_known_at for e in loaded.events), default=loaded.window_end)
    ctx = RunContext(
        namespace=f"replay.{scenario}",
        run_mode=RunMode.REPLAY,
        feed_mode=modes.pop() if len(modes) == 1 else FeedMode.SYNTHETIC,
        now=min(horizon, loaded.window_end),
        adapters=list(scenario_adapters(loaded, env=env)) if INGEST_ASSET in plan else [],
        env=env,
    )
    outcomes = run_pipeline(conn, ctx, plan)
    run_id = next(o.run_id for o in outcomes if o.asset == name)
    found = [r for r in runs(conn, asset=name, limit=20) if r.run_id == run_id]
    if not found:
        raise OpsNotFound(f"run {run_id} was not recorded", code="RUN_NOT_RECORDED")
    return found[0]
