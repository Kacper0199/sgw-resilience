"""Adapters for a scenario: one `ReplayAdapter` per source in its fixtures, faults from `FAULT_FEED_*`.
Live feeds (NWS) are added by the caller, since they need a network client."""

from __future__ import annotations

from collections.abc import Mapping

from sgw.ingest.adapters.replay import ReplayAdapter
from sgw.ingest.faults import faults_from_env
from sgw.ingest.scenario import Scenario

DEFAULT_PAGE = 500


def scenario_adapters(
    scenario: Scenario,
    *,
    env: Mapping[str, str],
    page_size: int = DEFAULT_PAGE,
    include_platform: bool = False,
) -> list[ReplayAdapter]:
    adapters: list[ReplayAdapter] = []
    for source_id, events in scenario.by_source(include_platform=include_platform).items():
        modes = {e.feed_mode for e in events}
        if len(modes) != 1:
            raise ValueError(f"{scenario.name}/{source_id}: mixed feed_mode {sorted(m.value for m in modes)}")
        adapters.append(
            ReplayAdapter(
                source_id,
                events,
                feed_mode=modes.pop(),
                page_size=page_size,
                faults=faults_from_env(env, source_id),
            )
        )
    return adapters
