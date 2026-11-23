"""Platform events emitted by the pipeline (`PipelineRunFinished`, `DQCheckFailed`, `CoverageGap`). Ids and
times derive from the run, never the wall clock, so a replay publishes the same bytes every time."""

from __future__ import annotations

import uuid
from typing import Any

from sgw.contracts.events import EVENT_MODELS, EnvelopeBase
from sgw.contracts.vocab import Classification, Trust
from sgw.pipeline.context import RunContext

PLATFORM_SOURCE = "sgw-pipeline"
PIPELINE_NAMESPACE = uuid.UUID("a3e9c1d4-7b25-5e80-9f16-2c4d8b0e6a53")


def platform_event(ctx: RunContext, type_name: str, key: str, payload: dict[str, Any]) -> EnvelopeBase:
    dedup_key = f"{ctx.namespace}:{type_name}:{key}"[:256]
    event: EnvelopeBase = EVENT_MODELS[type_name].model_validate(
        {
            "type": type_name,
            "event_id": uuid.uuid5(PIPELINE_NAMESPACE, dedup_key),
            "source_id": PLATFORM_SOURCE,
            "feed_mode": ctx.feed_mode,
            "run_mode": ctx.run_mode,
            "event_time": ctx.now,
            "received_at": ctx.now,
            "known_at": ctx.now,
            "scenario_known_at": ctx.now,
            "dedup_key": dedup_key,
            "classification": Classification.C1,
            "trust": Trust.SYSTEM,
            "payload": payload,
        }
    )
    return event
