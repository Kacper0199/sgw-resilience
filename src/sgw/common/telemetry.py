"""K12 trace and log fields. Every span carries `run_id`, `ledger_seq` (when relevant), `classification`
(high-water mark), `user_role` and `run_mode`, under the `sgw.` attribute prefix."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span

from sgw.contracts.vocab import Classification, RunMode

TRACER_NAME = "sgw"
REQUIRED_ATTRS: tuple[str, ...] = ("sgw.run_id", "sgw.classification", "sgw.user_role", "sgw.run_mode")
OPTIONAL_ATTRS: tuple[str, ...] = (
    "sgw.ledger_seq",
    "sgw.node",
    "sgw.wave",
    "sgw.purpose",
    "sgw.region_id",
    "sgw.llm_path",
)
LOG_FIELDS: tuple[str, ...] = (
    "run_id",
    "ledger_seq",
    "classification",
    "user_role",
    "run_mode",
    "request_id",
    "trace_id",
)


def span_attributes(
    *,
    run_id: str | None,
    classification: Classification,
    user_role: str,
    run_mode: RunMode,
    ledger_seq: int | None = None,
    **extra: str | int | bool,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "sgw.run_id": run_id or "none",
        "sgw.classification": classification.value,
        "sgw.user_role": user_role,
        "sgw.run_mode": run_mode.value,
    }
    if ledger_seq is not None:
        attrs["sgw.ledger_seq"] = ledger_seq
    for key, value in extra.items():
        name = f"sgw.{key}"
        if name not in OPTIONAL_ATTRS:
            raise ValueError(f"{name} is not a K12 attribute")
        attrs[name] = value
    return attrs


def missing_required(attributes: dict[str, Any] | Any) -> list[str]:
    present = dict(attributes or {})
    return [a for a in REQUIRED_ATTRS if a not in present]


@contextmanager
def sgw_span(name: str, **kwargs: Any) -> Iterator[Span]:
    tracer = trace.get_tracer(TRACER_NAME)
    with tracer.start_as_current_span(name, attributes=span_attributes(**kwargs)) as span:
        yield span
