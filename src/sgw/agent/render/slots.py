"""K15 slot values: deterministic formatting of evidence values, and rendering of model or template text.

Every digit a person reads in narration comes from here. Formatting is fixed per `SlotFormat` (times on the
scenario clock in UTC to the minute, hours to one decimal, counts with thousands separators, ppm shares as
percent to one decimal), so the LLM path and the M2 template path print identical values.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from sgw.agent.render.evidence import EvidenceBundle, SlotValue
from sgw.contracts.evidence import SLOT_RE, SlotError, render

SlotValues = dict[str, dict[str, str]]


def _num(value: datetime | int | float | str) -> float:
    if isinstance(value, datetime | str):
        raise SlotError(f"numeric slot holds {type(value).__name__}")
    return float(value)


def format_value(slot: SlotValue) -> str:
    v = slot.value
    match slot.format:
        case "utc_minute":
            if not isinstance(v, datetime):
                raise SlotError("utc_minute slot needs a datetime")
            return v.astimezone(UTC).strftime("%d %b %H:%MZ")
        case "hours":
            return f"{_num(v):.1f} h"
        case "minutes":
            return f"{round(_num(v)):,} min"
        case "count":
            return f"{round(_num(v)):,}" + (f" {slot.unit}" if slot.unit else "")
        case "percent_ppm":
            return f"{_num(v) / 10_000:.1f}%"
        case "kw":
            return f"{round(_num(v)):,} kW"
        case "psi":
            return f"{_num(v):.0f} psi"
        case "text":
            return str(v)
    raise SlotError(f"unknown slot format {slot.format}")


def slot_values(bundle: EvidenceBundle) -> SlotValues:
    return {
        item.id: {name: format_value(v) for name, v in sorted(item.values.items())} for item in bundle.items
    }


def render_text(text: str, values: Mapping[str, Mapping[str, str]]) -> str:
    return render(text, values)


def used_slots(text: str) -> list[tuple[str, str]]:
    return [(f"E{m['n']}", m["field"]) for m in SLOT_RE.finditer(text)]


def used_values(text: str, values: Mapping[str, Mapping[str, str]]) -> dict[str, str]:
    """`{"E3.decide_by": "27 Sep 04:28Z", ...}` for every slot the text uses: what the reader is shown."""
    return {f"{ref}.{field}": values[ref][field] for ref, field in used_slots(text)}
