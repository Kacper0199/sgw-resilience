"""What one tool call returns to an agent, and the per-worker evidence ledger that numbers its items.

`ToolOutcome.content` is the K15 agent view of the new items (ids, kinds, labels, bands, closed hints and slot
names; never a value), so a model can only quote a number through a `{E<n>.<field>}` slot that code fills.
`status` is the call's real result: `ok` (evidence returned), `empty` (the read model has nothing for this
time or filter), `refused` (not offered to this role, or not a registered read-only tool) or `error`
(invalid arguments, read model unavailable). A persona refusal is an answer, not an error (`is_error` is
false); an unregistered or write tool is an error and raises a SEC-13/SEC-14 alert."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sgw.agent.render.evidence import EvidenceBundle, EvidenceItem, build_view

ToolStatus = Literal["ok", "empty", "refused", "error"]
MAX_EVIDENCE_ID = 999


@dataclass
class EvidenceLedger:
    """Numbers items `E<start>`, `E<start + 1>` ... in the order they are added. Parallel workers each get
    their own ledger with a disjoint `start`, so an id never depends on which worker finishes first."""

    start: int = 1
    items: list[EvidenceItem] = field(default_factory=list)

    def add(self, item: EvidenceItem) -> EvidenceItem:
        n = self.start + len(self.items)
        if n > MAX_EVIDENCE_ID:
            raise OverflowError("evidence ids are limited to E999")
        numbered = item.model_copy(update={"id": f"E{n}"})
        self.items.append(numbered)
        return numbered

    def view_text(self, new: list[EvidenceItem]) -> str:
        bundle = EvidenceBundle(run_id="tools", items=self.items)
        return build_view(bundle, include=[i.id for i in new]).text


@dataclass
class ToolOutcome:
    content: str | list[dict[str, Any]]
    status: ToolStatus = "ok"
    is_error: bool = False
    new_items: list[EvidenceItem] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def evidence_ids(self) -> list[str]:
        return [i.id for i in self.new_items]
