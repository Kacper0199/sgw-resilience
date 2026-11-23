"""N2 `extract_note`: untrusted free text -> `FieldClaim[]` (tool-less, structured output), then deterministic
checks. The FieldClaim schema follows the WP-15 proposal (evals/README.md, extractor set).

Every report is untrusted (`internal_free_text` or `external`), so every extraction taints the run that
reads it and every claim carries that trust. Claims are never authority: there is no approval category, a
claim cannot change an approval or a tier downwards, and a proposal whose evidence is only such claims
rises one approval tier through the policy fact `untrusted_evidence_only` (`proposal_facts`).

Path: guard (instruction sentences withheld, flags kept) -> one model call with the guarded text -> schema
check -> per-claim checks (quote is an exact span of the report and not of a withheld sentence; asset id
exact or resolved to exactly one registry id; value and unit supported by the quote) -> result. Failed
claims are dropped with a reason; a failed call gives the M2 result (no claims, registry ids found
verbatim, note kept in quarantine)."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import datetime
from enum import StrEnum
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, ValidationError

from sgw.agent.extract.guard import GuardedText, guard_untrusted, neutralise_tags
from sgw.agent.extract.prompts import EXTRACT_SYSTEM_V1, EXTRACT_SYSTEM_V2, EXTRACT_USER_TEMPLATE_V1
from sgw.agent.extract.registry import NETWORK_FILE, field_registry, named_assets_table, resolve
from sgw.agent.nodes.llm import LlmClient, LlmRequest, LlmUnavailable, ensure_usable
from sgw.agent.nodes.spine import proposal_facts as proposal_facts
from sgw.agent.render.evidence import EvidenceItem
from sgw.contracts.base import Contract
from sgw.contracts.llm_nodes import NodeConfig
from sgw.contracts.vocab import Classification, Trust, UiSeverity

NODE = "extract_note"
SYSTEM_PROMPTS = {"v1": EXTRACT_SYSTEM_V1, "v2": EXTRACT_SYSTEM_V2}
USER_TEMPLATES = {"v1": EXTRACT_USER_TEMPLATE_V1, "v2": EXTRACT_USER_TEMPLATE_V1}
DERIVED_UNITS = frozenset({"percent", "persons"})
FRACTIONS = {
    "1/4": 25.0,
    "1/2": 50.0,
    "3/4": 75.0,
    "half": 50.0,
    "quarter": 25.0,
    "full": 100.0,
    "empty": 0.0,
}
ID_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b")


class Channel(StrEnum):
    FIELD_NOTE = "field_note"
    CUSTOMER_TICKET = "customer_ticket"
    NWS_ALERT = "nws_alert"
    OCR = "ocr"
    GIS_ATTRIBUTE = "gis_attribute"
    USER_TURN = "user_turn"


class ClaimCategory(StrEnum):
    LINE_DOWN = "line_down"
    POLE_BROKEN = "pole_broken"
    TREE_ON_LINE = "tree_on_line"
    TRANSFORMER_DAMAGE = "transformer_damage"
    ROAD_BLOCKED = "road_blocked"
    FLOODING = "flooding"
    GENERATOR_STATUS = "generator_status"
    FUEL_LEVEL = "fuel_level"
    PRESSURE_LOW = "pressure_low"
    PUMP_STATUS = "pump_status"
    OUTAGE_REPORT = "outage_report"
    SAFETY_HAZARD = "safety_hazard"
    CREW_STATUS = "crew_status"
    OTHER = "other"


class Polarity(StrEnum):
    ASSERTED = "asserted"
    NEGATED = "negated"
    HEDGED = "hedged"


UntrustedTrust = Literal[Trust.INTERNAL_FREE_TEXT, Trust.EXTERNAL]


class NoteInput(Contract):
    note_id: str = Field(min_length=1, max_length=64)
    channel: Channel
    trust: UntrustedTrust = Field(
        description="extracted text is always untrusted; verified data never comes here"
    )
    author_role: str = Field(default="unknown", max_length=40)
    text: str = Field(min_length=1, max_length=4000)
    received_at: datetime | None = None


class FieldClaim(Contract):
    asset_id: str | None
    unregistered_ref: str | None = None
    category: ClaimCategory
    polarity: Polarity
    relayed: bool
    severity_hint: UiSeverity
    value: float | None = None
    unit: str | None = None
    quote: str
    quote_start: int = Field(ge=0)
    quote_end: int = Field(ge=0)
    location_text: str | None = None
    trust: Trust
    tainted: bool = True


class DroppedClaim(Contract):
    quote: str
    reason: str


class ExtractionResult(Contract):
    note_id: str
    channel: Channel
    trust: Trust
    path: Literal["llm", "m2"]
    tainted: bool
    instructions_detected: bool
    guard_reasons: list[str]
    claims: list[FieldClaim]
    dropped: list[DroppedClaim] = Field(default_factory=list)
    mentioned_ids: list[str] = Field(default_factory=list)
    model_flagged_instructions: bool = False
    reason: str | None = None
    model: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    call_id: str | None = None


_NULL_STR = {"type": ["string", "null"]}
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "asset_ref": _NULL_STR,
                    "category": {"type": "string", "enum": [c.value for c in ClaimCategory]},
                    "polarity": {"type": "string", "enum": [p.value for p in Polarity]},
                    "relayed": {"type": "boolean"},
                    "severity_hint": {"type": "string", "enum": [s.value for s in UiSeverity]},
                    "value": {"type": ["number", "null"]},
                    "unit": _NULL_STR,
                    "location_text": _NULL_STR,
                },
                "required": [
                    "quote",
                    "asset_ref",
                    "category",
                    "polarity",
                    "relayed",
                    "severity_hint",
                    "value",
                    "unit",
                    "location_text",
                ],
                "additionalProperties": False,
            },
        },
        "instructions_detected": {"type": "boolean"},
    },
    "required": ["claims", "instructions_detected"],
    "additionalProperties": False,
}


class ModelClaim(Contract):
    quote: str
    asset_ref: str | None
    category: ClaimCategory
    polarity: Polarity
    relayed: bool
    severity_hint: UiSeverity
    value: float | None
    unit: str | None
    location_text: str | None


class ModelOut(Contract):
    claims: list[ModelClaim] = Field(max_length=20)
    instructions_detected: bool


def build_request(
    note: NoteInput, guarded: GuardedText, config: NodeConfig, run_id: str | None
) -> LlmRequest:
    system = SYSTEM_PROMPTS[config.prompt_version].replace("{assets}", named_assets_table())
    user = USER_TEMPLATES[config.prompt_version].format(
        channel=note.channel.value,
        trust=note.trust.value,
        author_role=note.author_role,
        text=neutralise_tags(guarded.shown),
    )
    return LlmRequest(
        node=NODE,
        config=config,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": [{"type": "text", "text": user}]}],
        classes=[Classification.C0, Classification.C1],
        run_id=run_id,
        output_schema=OUTPUT_SCHEMA,
    )


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def locate(quote: str, text: str) -> tuple[int, int] | None:
    """Offsets of `quote` in `text`: exact first, then whitespace- and case-insensitive on the NFKC form."""
    if not quote.strip():
        return None
    i = text.find(quote)
    if i >= 0:
        return i, i + len(quote)
    words = [re.escape(w) for w in _nfkc(quote).split()]
    m = re.search(r"\s+".join(words), _nfkc(text), re.IGNORECASE)
    if m and len(_nfkc(text)) == len(text):
        return m.start(), m.end()
    return None


def _numbers(text: str) -> set[float]:
    found = {float(x.replace(",", "")) for x in re.findall(r"\d+(?:[.,]\d+)?", text)}
    low = text.lower()
    found |= {v for k, v in FRACTIONS.items() if re.search(rf"(?<![\w/]){re.escape(k)}(?![\w/])", low)}
    return found


def value_supported(value: float | None, unit: str | None, quote: str) -> tuple[bool, str]:
    if value is None:
        return (unit is None or unit in quote or unit in DERIVED_UNITS), "unit_without_value"
    if value not in _numbers(quote):
        return False, "value_not_in_quote"
    if unit is not None and unit not in DERIVED_UNITS and unit not in quote:
        return False, "unit_not_in_quote"
    return True, ""


def mentioned_ids(text: str) -> list[str]:
    reg = field_registry()
    return sorted({t for t in ID_TOKEN_RE.findall(_nfkc(text)) if t in reg})


def _squash(text: str) -> str:
    return re.sub(r"[\s_-]+", "", _nfkc(text).casefold())


@lru_cache(maxsize=1)
def _station_generators() -> dict[str, str]:
    named = json.loads(NETWORK_FILE.read_text(encoding="utf-8"))["named"]["pump_stations"]
    return {gen: ps for ps, info in named.items() if (gen := info.get("onsite_generator"))}


def short_forms(asset_id: str | None) -> list[str]:
    """How a report may write a registry id: in full, a feeder or section without `FDR-<county>-` ("2216 S2"),
    a crew without `CRW-` and `MA-` ("Osprey-07")."""
    if not asset_id:
        return []
    forms = [asset_id]
    if m := re.match(r"^FDR-[A-Z]+-(.+)$", asset_id):
        forms.append(m.group(1))
    if m := re.match(r"^CRW-(?:MA-)?(.+)$", asset_id):
        forms.append(m.group(1))
    return forms


def asset_named_in(ref: str | None, asset_id: str | None, text: str) -> bool:
    """The asset a claim names must be named in the report: the model's reference or the resolved id appears
    in the text (case, spaces and hyphens ignored), or the id is the onsite generator of a pump station the
    report names ("PS-38 ... Gen in standby"). Anything else is an asset the model brought in."""
    if not ref:
        return False
    body = _squash(text)
    if _squash(ref) in body or any(_squash(form) in body for form in short_forms(asset_id)):
        return True
    station = _station_generators().get(asset_id or "")
    return station is not None and _squash(station) in body


def check_claims(
    note: NoteInput, guarded: GuardedText, claims: Sequence[ModelClaim]
) -> tuple[list[FieldClaim], list[DroppedClaim]]:
    kept: list[FieldClaim] = []
    dropped: list[DroppedClaim] = []
    seen: set[tuple[str, str, str]] = set()
    for c in claims:
        span = locate(c.quote, note.text)
        if span is None:
            dropped.append(DroppedClaim(quote=c.quote[:200], reason="quote_not_in_report"))
            continue
        if guarded.overlaps_withheld(*span):
            dropped.append(DroppedClaim(quote=c.quote[:200], reason="quote_in_withheld_text"))
            continue
        quote = note.text[span[0] : span[1]]
        asset_id = resolve(c.asset_ref)
        named = asset_named_in(c.asset_ref, asset_id, note.text)
        if c.asset_ref and not named:
            dropped.append(DroppedClaim(quote=quote[:200], reason="asset_removed:asset_ref_not_in_report"))
            asset_id = None
        ok, why = value_supported(c.value, c.unit, quote)
        value, unit = (c.value, c.unit) if ok else (None, None)
        if not ok:
            dropped.append(DroppedClaim(quote=quote[:200], reason=f"value_removed:{why}"))
        key = (asset_id or c.asset_ref or "", c.category.value, quote)
        if key in seen:
            continue
        seen.add(key)
        kept.append(
            FieldClaim(
                asset_id=asset_id,
                unregistered_ref=None if asset_id or not c.asset_ref or not named else c.asset_ref[:80],
                category=c.category,
                polarity=c.polarity,
                relayed=c.relayed,
                severity_hint=c.severity_hint,
                value=value,
                unit=unit,
                quote=quote,
                quote_start=span[0],
                quote_end=span[1],
                location_text=c.location_text[:120] if c.location_text else None,
                trust=note.trust,
                tainted=True,
            )
        )
    return kept, dropped


def _tainted(note: NoteInput, guarded: GuardedText) -> bool:
    """Every extracted report taints the run: the channel is untrusted by construction (NoteInput.trust)."""
    return True


def m2_result(note: NoteInput, guarded: GuardedText, reason: str) -> ExtractionResult:
    return ExtractionResult(
        note_id=note.note_id,
        channel=note.channel,
        trust=note.trust,
        path="m2",
        tainted=_tainted(note, guarded),
        instructions_detected=guarded.instructions_detected,
        guard_reasons=guarded.reasons,
        claims=[],
        mentioned_ids=mentioned_ids(guarded.shown),
        reason=reason,
    )


async def extract_note(
    note: NoteInput,
    *,
    llm: LlmClient,
    config: NodeConfig,
    run_id: str | None = None,
    model_override: str | None = None,
) -> ExtractionResult:
    guarded = guard_untrusted(note.text)
    if not guarded.shown.replace("[withheld: instruction-like text]", "").strip():
        return m2_result(note, guarded, "nothing_left_after_guard")
    request = build_request(note, guarded, config, run_id)
    if model_override:
        request = replace(request, model_override=model_override)
    try:
        response = await llm.create(request)
        ensure_usable(response)
    except LlmUnavailable as exc:
        return m2_result(note, guarded, exc.reason)
    if response.tool_uses():
        return m2_result(note, guarded, "unexpected_tool_use")
    try:
        out = ModelOut.model_validate(json.loads(response.text()))
    except (ValueError, ValidationError):
        return m2_result(note, guarded, "schema_invalid")
    claims, dropped = check_claims(note, guarded, out.claims)
    return ExtractionResult(
        note_id=note.note_id,
        channel=note.channel,
        trust=note.trust,
        path="llm",
        tainted=_tainted(note, guarded),
        instructions_detected=guarded.instructions_detected,
        guard_reasons=guarded.reasons,
        claims=claims,
        dropped=dropped,
        mentioned_ids=mentioned_ids(guarded.shown),
        model_flagged_instructions=out.instructions_detected,
        model=response.model,
        usage=response.usage,
        call_id=response.call_id,
    )


def claim_items(results: Iterable[ExtractionResult], start: int, as_of: datetime) -> list[EvidenceItem]:
    """Claims as run evidence: one quarantined item per claim, with the report's trust. The view shows only
    the fixed quarantine line for them, so their text never reaches a privileged prompt."""
    items: list[EvidenceItem] = []
    for r in results:
        for c in r.claims:
            items.append(
                EvidenceItem(
                    id=f"E{start + len(items)}",
                    kind="field_claim",
                    label=f"{c.category.value} {c.polarity.value}",
                    as_of=as_of,
                    citation=f"{r.channel.value}:{r.note_id}",
                    classification=Classification.C1,
                    trust=r.trust,
                    hints={"category": c.category.value, "polarity": c.polarity.value},
                    entity_ids=[c.asset_id] if c.asset_id else [],
                    raw_text=c.quote,
                )
            )
    return items
