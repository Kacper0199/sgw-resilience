"""K15 evidence agent view and slot grammar `{E<n>.<field>}` (DC-40, NEW-ai-01).

Text-generating nodes see `EvidenceRef` without values and write slots; `render` fills them from
deterministic values; `verify_text` rejects any digit outside a slot except ISO dates, times and
SOP section ids from the allowlist patterns.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from pydantic import Field

from sgw.contracts.base import Contract, UtcDatetime
from sgw.contracts.vocab import Classification, RiskBand, Trust

SLOT_RE = re.compile(r"\{E(?P<n>[1-9]\d{0,2})\.(?P<field>[a-z][a-z0-9_]*)\}")
ALLOWED_DIGIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?Z?)?\b"),
    re.compile(r"\b\d{2}:\d{2}Z\b"),
    re.compile(r"\bSOP-[A-Z]{2,6}-\d{1,3}(\.\d{1,3})*\b"),
    re.compile(r"\b(?:R\.)?\d{2,3}-\d{1,3}(?:\.\d+)*(?:\.[A-Z])?(?:\(\d+\))?"),
    re.compile(r"\bN\+\d\b"),
    re.compile(r"\b[TKMCDHW]\d\b"),
)


class EvidenceRef(Contract):
    id: str = Field(pattern=r"^E[1-9]\d{0,2}$")
    kind: str
    label: str
    band: RiskBand | None = None
    unit: str | None = None
    as_of: UtcDatetime
    model_version: str | None = None
    citation: str
    classification: Classification
    trust: Trust
    derived_classification: Classification = Field(
        default=Classification.C1,
        description="declared class of what the view shows besides the label: kind, band, unit, trust, "
        "citation and closed enum hints, all derived by code from the values (D-072)",
    )


class SlotError(ValueError):
    pass


def slots_in(text: str) -> list[tuple[str, str]]:
    return [(f"E{m['n']}", m["field"]) for m in SLOT_RE.finditer(text)]


def render(text: str, values: Mapping[str, Mapping[str, str]]) -> str:
    def sub(m: re.Match[str]) -> str:
        ref, field = f"E{m['n']}", m["field"]
        try:
            return values[ref][field]
        except KeyError as exc:
            raise SlotError(f"unknown slot {{{ref}.{field}}}") from exc

    return SLOT_RE.sub(sub, text)


def verify_text(text: str, known_refs: set[str]) -> list[str]:
    """Return violations: unknown refs and digits outside slots or allowlisted patterns."""
    problems = [f"unknown evidence {ref}" for ref, _ in slots_in(text) if ref not in known_refs]
    stripped = SLOT_RE.sub(" ", text)
    for pattern in ALLOWED_DIGIT_PATTERNS:
        stripped = pattern.sub(" ", stripped)
    problems += [
        f"bare digit near {stripped[max(0, m.start() - 12) : m.end() + 12]!r}"
        for m in re.finditer(r"\d", stripped)
    ]
    return problems
