"""Run evidence with values (code side) and the K15 agent view without values (model side).

`EvidenceItem` holds the deterministic values a model or rule computed; only `build_view` decides what of it
enters a prompt. The view carries ids, kinds, labels, bands, units, slot field names and closed enum hints,
never a value, so the prompt's data class comes from the labels and hints that entered it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from sgw.contracts.base import Contract, UtcDatetime
from sgw.contracts.evidence import EvidenceRef
from sgw.contracts.vocab import Classification, RiskBand, Trust

CLASS_ORDER: dict[Classification, int] = {
    Classification.C0: 0,
    Classification.C1: 1,
    Classification.C2: 2,
    Classification.C3: 3,
    Classification.C3_N: 3,
    Classification.C4: 4,
    Classification.CX: 5,
}
ROUTE_CLASSES: dict[str, frozenset[Classification]] = {
    "R1": frozenset({Classification.C0, Classification.C1}),
    "R2": frozenset({Classification.C0, Classification.C1, Classification.C2}),
}
UNTRUSTED = frozenset({Trust.EXTERNAL, Trust.INTERNAL_FREE_TEXT})
UNTRUSTED_LABEL = "free-text report from an untrusted channel, quarantined, not evidence"
QUARANTINE_LINE_CLASS = Classification.C1
HINT_VALUE_RE = r"^[a-z][a-z0-9_]{0,40}$"

SlotFormat = Literal["utc_minute", "hours", "minutes", "count", "percent_ppm", "text", "kw", "psi"]


class SlotValue(Contract):
    value: datetime | int | float | str
    format: SlotFormat
    unit: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _typed_from_json(cls, data: object) -> object:
        if (
            isinstance(data, dict)
            and data.get("format") == "utc_minute"
            and isinstance(data.get("value"), str)
        ):
            return {**data, "value": datetime.fromisoformat(data["value"].replace("Z", "+00:00"))}
        return data


class EvidenceItem(Contract):
    id: str = Field(pattern=r"^E[1-9]\d{0,2}$")
    kind: str = Field(pattern=r"^[a-z][a-z0-9_]{0,40}$")
    label: str = Field(min_length=1, max_length=200)
    label_classification: Classification = Classification.C1
    derived_classification: Classification = Field(
        default=Classification.C1,
        description="class of what the view shows besides the label: kind, band, unit, trust, citation and "
        "the closed enum hints, all derived by code from the values (D-072)",
    )
    band: RiskBand | None = None
    unit: str | None = None
    as_of: UtcDatetime
    model_version: str | None = None
    citation: str
    classification: Classification
    trust: Trust
    values: dict[str, SlotValue] = Field(default_factory=dict)
    hints: dict[str, str] = Field(
        default_factory=dict, description="closed enum hints computed by code (trend, verdict); no digits"
    )
    entity_ids: list[str] = Field(default_factory=list, description="registry ids this item is about")
    raw_text: str | None = Field(default=None, description="untrusted free text; never enters a prompt")


class EvidenceBundle(Contract):
    run_id: str
    items: list[EvidenceItem]

    def by_id(self) -> dict[str, EvidenceItem]:
        return {i.id: i for i in self.items}

    def entity_ids(self) -> set[str]:
        return {e for i in self.items for e in i.entity_ids}


class ViewRef(Contract):
    ref: EvidenceRef
    fields: list[str]
    hints: dict[str, str]


class EvidenceView(Contract):
    refs: list[ViewRef]
    text: str = Field(description="the exact evidence block that enters the prompt")
    classes: list[Classification]
    withheld_labels: list[str] = Field(default_factory=list, description="ids whose label was withheld")

    def fields(self) -> dict[str, set[str]]:
        return {r.ref.id: set(r.fields) for r in self.refs}

    def header_value(self) -> str:
        return ",".join(c.value for c in self.classes)


def max_class(classes: Iterable[Classification]) -> Classification:
    return max(classes, key=lambda c: CLASS_ORDER[c], default=Classification.C0)


def _label(item: EvidenceItem, allowed: frozenset[Classification]) -> tuple[str, bool]:
    if item.trust in UNTRUSTED:
        return UNTRUSTED_LABEL, False
    if item.label_classification in allowed:
        return item.label, False
    return f"{item.kind.replace('_', ' ')} (label withheld: class {item.label_classification.value})", True


def _hints(item: EvidenceItem) -> dict[str, str]:
    return {
        k: v for k, v in sorted(item.hints.items()) if re.match(HINT_VALUE_RE, v) and not re.search(r"\d", v)
    }


def _ref_line(view_ref: ViewRef) -> str:
    r = view_ref.ref
    parts = [f"[{r.id}] {r.kind}: {r.label}"]
    if r.band is not None:
        parts.append(f"band={r.band.value}")
    if r.unit:
        parts.append(f"unit={r.unit}")
    parts.append(f"trust={r.trust.value}")
    parts.extend(f"{k}={v}" for k, v in view_ref.hints.items())
    if view_ref.fields:
        parts.append("slots=" + " ".join(f"{{{r.id}.{f}}}" for f in view_ref.fields))
    parts.append(f"source={r.citation}")
    return "; ".join(parts)


def build_view(
    bundle: EvidenceBundle, *, route: str = "R1", include: Sequence[str] | None = None
) -> EvidenceView:
    """Agent view of the bundle. The declared classes are those of the text that entered the view: C0 for
    the frame, each shown label's class, and the value class of any item whose value text is found in the
    rendered block (which the builder never puts there; the scan is the proof)."""
    allowed = ROUTE_CLASSES[route]
    chosen = [i for i in bundle.items if include is None or i.id in include]
    refs: list[ViewRef] = []
    withheld: list[str] = []
    classes: set[Classification] = {Classification.C0}
    for item in chosen:
        label, was_withheld = _label(item, allowed)
        if was_withheld:
            withheld.append(item.id)
        else:
            classes.add(QUARANTINE_LINE_CLASS if item.trust in UNTRUSTED else item.label_classification)
        fields = [] if item.trust in UNTRUSTED else sorted(item.values)
        ref = EvidenceRef(
            id=item.id,
            kind=item.kind,
            label=label,
            band=item.band,
            unit=item.unit,
            as_of=item.as_of,
            model_version=item.model_version,
            citation=item.citation if item.trust not in UNTRUSTED else "quarantine",
            classification=item.classification,
            trust=item.trust,
            derived_classification=item.derived_classification,
        )
        classes.add(QUARANTINE_LINE_CLASS if item.trust in UNTRUSTED else item.derived_classification)
        refs.append(ViewRef(ref=ref, fields=fields, hints={} if item.trust in UNTRUSTED else _hints(item)))
    text = "\n".join(_ref_line(r) for r in refs)
    classes |= leaked_classes(text, chosen)
    ordered = sorted(classes, key=lambda c: CLASS_ORDER[c])
    return EvidenceView(refs=refs, text=text, classes=ordered, withheld_labels=withheld)


def leaked_classes(text: str, items: Iterable[EvidenceItem]) -> set[Classification]:
    from sgw.agent.render.slots import format_value

    found: set[Classification] = set()
    for item in items:
        for value in item.values.values():
            shown = format_value(value)
            if len(shown) >= 3 and shown in text:
                found.add(item.classification)
        if item.raw_text and item.raw_text.strip() and item.raw_text.strip()[:40] in text:
            found.add(max_class([item.classification, Classification.C2]))
    return found


def view_classes_allowed(view: EvidenceView, route: str = "R1") -> bool:
    return set(view.classes) <= ROUTE_CLASSES[route]


def slot_fields(view: EvidenceView) -> Mapping[str, set[str]]:
    return view.fields()
