"""K2 source events for the detail area, grouped per feed (one K9 fixture file per feed).

Only source systems are emitted (weather, OMS, SCADA, AMI, FSM, EAM, LIMS, GIS); platform events (risk,
clocks, proposals, approvals) are produced by the platform at replay. Every event is synthetic, validated
against its K2 model, and gets a deterministic id: uuid5(namespace, dedup_key).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from sgw.contracts.events import EVENT_MODELS, EnvelopeBase
from sgw.generator.config import Family, rng

NAMESPACE = uuid.UUID("3f6c2a1e-9b47-4d2f-8e15-2024092717a5")

SOURCES: dict[str, dict[str, str]] = {
    "nws-alerts": {"feed": "weather", "classification": "C0", "trust": "external"},
    "nhc-advisory-synthetic": {"feed": "weather", "classification": "C0", "trust": "external"},
    "oms": {"feed": "oms", "classification": "C1", "trust": "verified_internal"},
    "scada-electric": {"feed": "scada", "classification": "C2", "trust": "verified_internal"},
    "scada-water": {"feed": "scada", "classification": "C2", "trust": "verified_internal"},
    "ami-headend": {"feed": "ami", "classification": "C1", "trust": "verified_internal"},
    "fsm-crews": {"feed": "fsm", "classification": "C1", "trust": "verified_internal"},
    "eam": {"feed": "eam", "classification": "C1", "trust": "verified_internal"},
    "lims": {"feed": "lims", "classification": "C1", "trust": "verified_internal"},
    "gis-trace": {"feed": "gis", "classification": "C2", "trust": "verified_internal"},
}


def utc(t: float) -> datetime:
    return datetime.fromtimestamp(round(t), tz=UTC)


class EventSink:
    def __init__(self, scenario: str, fam: Family, window: tuple[float, float]) -> None:
        self.scenario = scenario
        self.latency = {k: int(v) for k, v in fam["telemetry.latency_s"].items()}
        self.window = window
        self.by_feed: dict[str, list[EnvelopeBase]] = defaultdict(list)
        self.dropped_outside_window = 0
        self.extra_latency: list[tuple[str, float, float, int]] = []
        self.delayed = 0

    def add(
        self,
        type_name: str,
        t: float,
        payload: dict[str, Any],
        *,
        key: str,
        source: str,
        region: str | None = None,
        domain: str | None = None,
        issued: float | None = None,
    ) -> bool:
        if not self.window[0] <= t <= self.window[1]:
            self.dropped_outside_window += 1
            return False
        meta = SOURCES[source]
        dedup = f"{self.scenario}:{type_name}:{key}"
        at = utc(t)
        lag = self.latency[source]
        for src, start, end, extra in self.extra_latency:
            if src == source and start <= t < end:
                lag += extra
                self.delayed += 1
        known = at + timedelta(seconds=lag)
        event = EVENT_MODELS[type_name].model_validate(
            {
                "type": type_name,
                "event_id": str(uuid.uuid5(NAMESPACE, dedup)),
                "source_id": source,
                "feed_mode": "synthetic",
                "run_mode": "replay",
                "event_time": at,
                "issued_at": utc(issued) if issued is not None else None,
                "valid_at": None,
                "received_at": known,
                "known_at": known,
                "scenario_known_at": known,
                "dedup_key": dedup,
                "classification": meta["classification"],
                "trust": meta["trust"],
                "region_id": region,
                "domain": domain,
                "payload": payload,
            }
        )
        self.by_feed[meta["feed"]].append(event)
        return True

    def count(self) -> int:
        return sum(len(v) for v in self.by_feed.values())


def jitter_s(seed: int, *keys: object, high: float = 120.0) -> float:
    return float(rng(seed, "jitter", *keys).uniform(0.0, high))


def shared_lost(seed: int, section: str, n: int, p_lost: float, rho: float) -> np.ndarray:
    """Last-gasp loss with a shared draw inside a section (OSR dependence dial)."""
    from scipy.stats import norm

    r = rng(seed, "ami_lost", section)
    z = np.sqrt(rho) * r.standard_normal() + np.sqrt(1.0 - rho) * r.standard_normal(n)
    return norm.cdf(z) < p_lost
