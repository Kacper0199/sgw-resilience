"""K6 adapter port (DC-51). `feed_mode` (where data comes from) is distinct from `run_mode`
(whether side effects are allowed). `tests/contracts/adapter_conformance.py` runs over every adapter."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from sgw.contracts.base import Contract, Identifier, UtcDatetime
from sgw.contracts.events import EnvelopeBase
from sgw.contracts.vocab import FeedMode


class FaultKind(StrEnum):
    DELAY = "delay"
    GAP = "gap"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"
    SCHEMA_DRIFT = "schema_drift"
    FLOOD_10X = "flood_10x"


class Coverage(Contract):
    from_utc: UtcDatetime | None
    to_utc: UtcDatetime | None
    complete: bool


class FetchResult(Contract):
    events: list[Any] = Field(description="K2 events (EnvelopeBase subclasses)")
    next_cursor: str
    coverage: Coverage


class AdapterHealth(Contract):
    source_id: Identifier
    last_success_at: UtcDatetime | None
    ingest_lag_s: int | None = Field(ge=0)
    product_age_s: int | None = Field(ge=0)
    error_rate_ppm: int = Field(ge=0, le=1_000_000)
    feed_mode: FeedMode


class Record(Contract):
    record_id: Identifier
    kind: str
    attributes: dict[str, Any]


@runtime_checkable
class Adapter(Protocol):
    source_id: str
    feed_mode: FeedMode

    def fetch_since(self, cursor: str | None) -> FetchResult: ...

    def snapshot(self) -> list[Record]: ...

    def health(self) -> AdapterHealth: ...

    def inject_fault(self, kind: FaultKind, **params: Any) -> None: ...


@runtime_checkable
class WritebackAdapter(Adapter, Protocol):
    def propose_writeback(self, draft: dict[str, Any]) -> str: ...


def is_event(obj: Any) -> bool:
    return isinstance(obj, EnvelopeBase)
