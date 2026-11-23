"""Synthetic load events for relay tests and spike S11 (labelled synthetic; ids follow the S11 run)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sgw.contracts.events import EVENT_MODELS, EnvelopeBase
from sgw.contracts.vocab import Classification, Domain, FeedMode, RunMode, Trust

LOAD_NAMESPACE = uuid.UUID("0d7c4a52-8e1b-5f39-a0c6-4b2e9f17d3a8")
LOAD_START = datetime(2024, 9, 27, 4, 0, tzinfo=UTC)


def meter_events(producer: str, count: int, *, start: datetime = LOAD_START) -> list[EnvelopeBase]:
    model = EVENT_MODELS["MeterEvent"]
    events: list[EnvelopeBase] = []
    for i in range(count):
        key = f"s11:{producer}:{i:06d}"
        at = start + timedelta(milliseconds=250 * i)
        events.append(
            model.model_validate(
                {
                    "type": "MeterEvent",
                    "event_id": uuid.uuid5(LOAD_NAMESPACE, key),
                    "source_id": f"load-{producer}",
                    "feed_mode": FeedMode.SYNTHETIC,
                    "run_mode": RunMode.REPLAY,
                    "event_time": at,
                    "received_at": at + timedelta(seconds=2),
                    "known_at": at + timedelta(seconds=2),
                    "scenario_known_at": at + timedelta(seconds=2),
                    "dedup_key": key,
                    "classification": Classification.C1,
                    "trust": Trust.SYSTEM,
                    "region_id": "SC-45003",
                    "domain": Domain.ELECTRIC,
                    "payload": {
                        "meter_id": f"MTR-KESTREL-{producer}-{i:05d}",
                        "kind": "last_gasp",
                        "premise_id": f"PRM-KESTREL-{i:05d}",
                        "feeder_id": "FDR-AIK-2207",
                    },
                }
            )
        )
    return events
