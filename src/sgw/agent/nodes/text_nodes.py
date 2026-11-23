"""The spine's two LLM nodes: `narrate` (N5) and `draft_rationale` (N6).

Each runs: view -> one gateway call -> refusal/truncation/tool-request checks -> K15 verify -> render. Any
failure goes to the M2 template with the same slots. Model text is never streamed or shown before the
verifier has passed it, and a model asking for a tool is a security alert (SEC-14), never a tool call.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, ValidationError

from sgw.agent.nodes.llm import LlmClient, LlmRequest, LlmUnavailable, ensure_usable
from sgw.agent.nodes.prompts import (
    NARRATE_SYSTEM_V1,
    NARRATE_SYSTEM_V2,
    NARRATE_SYSTEM_V3,
    NARRATE_USER_TEMPLATE,
    RATIONALE_SYSTEM_V1,
    RATIONALE_SYSTEM_V2,
    RATIONALE_USER_TEMPLATE,
    RATIONALE_USER_TEMPLATE_V2,
)
from sgw.agent.nodes.templates import narrate_template, rationale_template
from sgw.agent.render.evidence import UNTRUSTED, EvidenceBundle, EvidenceView
from sgw.agent.render.slots import render_text, slot_values, used_values
from sgw.agent.render.verify import Violation, verify
from sgw.contracts.base import Contract
from sgw.contracts.llm_nodes import NodeConfig

SYSTEM_PROMPTS = {
    "narrate": {"v1": NARRATE_SYSTEM_V1, "v2": NARRATE_SYSTEM_V2, "v3": NARRATE_SYSTEM_V3},
    "draft_rationale": {"v1": RATIONALE_SYSTEM_V1, "v2": RATIONALE_SYSTEM_V2},
}


class Precondition(StrEnum):
    ADVISORY_CONFIRMS_TRACK = "advisory_confirms_track"
    CREWS_AVAILABLE = "crews_available"
    YARD_OUTSIDE_HAZARD_ZONE = "yard_outside_hazard_zone"
    FUEL_PATH_OPEN = "fuel_path_open"
    GENERATOR_READY = "generator_ready"
    PRESSURE_FLOOR_HELD = "pressure_floor_held"


class RationaleOut(Contract):
    rationale: str = Field(min_length=1, max_length=1500)
    preconditions: list[Precondition] = Field(max_length=6)
    evidence_ids: list[str] = Field(min_length=1, max_length=12)


RATIONALE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rationale": {"type": "string"},
        "preconditions": {
            "type": "array",
            "items": {"type": "string", "enum": [p.value for p in Precondition]},
        },
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["rationale", "preconditions", "evidence_ids"],
    "additionalProperties": False,
}


@dataclass
class NodeOutcome:
    node: str
    path: Literal["llm", "m2"]
    text: str
    rendered: str
    slots_shown: dict[str, str]
    reason: str | None = None
    violations: list[str] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None
    structured: dict[str, Any] | None = None

    def as_state(self) -> dict[str, Any]:
        return asdict(self)


def system_blocks(node: str, config: NodeConfig) -> list[dict[str, Any]]:
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPTS[node][config.prompt_version],
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _tool_alerts(node: str, tool_uses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "code": "SEC-14",
            "kind": "tool_request_refused",
            "node": node,
            "tool": str(b.get("name", ""))[:64],
            "detail": "the node binds no tools; the request was not executed",
        }
        for b in tool_uses
    ]


def _m2(
    node: str, text: str, bundle: EvidenceBundle, view: EvidenceView, ids: frozenset[str], reason: str
) -> NodeOutcome:
    problems = verify(text, view.fields(), ids)
    if problems:
        raise RuntimeError(f"M2 template for {node} fails the verifier: {[str(p) for p in problems]}")
    values = slot_values(bundle)
    return NodeOutcome(
        node=node,
        path="m2",
        text=text,
        rendered=render_text(text, values),
        slots_shown=used_values(text, values),
        reason=reason,
    )


async def _call(client: LlmClient, request: LlmRequest) -> tuple[Any, list[dict[str, Any]]]:
    response = await client.create(request)
    alerts = _tool_alerts(request.node, response.tool_uses())
    if alerts:
        return response, alerts
    ensure_usable(response)
    return response, []


async def narrate(
    *,
    client: LlmClient,
    config: NodeConfig,
    bundle: EvidenceBundle,
    view: EvidenceView,
    ids: frozenset[str],
    phase: str,
    run_id: str | None = None,
    model_override: str | None = None,
) -> NodeOutcome:
    request = LlmRequest(
        node="narrate",
        config=config,
        system=system_blocks("narrate", config),
        messages=[
            {
                "role": "user",
                "content": NARRATE_USER_TEMPLATE.format(phase=phase, evidence=view.text),
            }
        ],
        classes=view.classes,
        run_id=run_id,
        model_override=model_override,
    )
    template = narrate_template(bundle, [r.ref.id for r in view.refs])
    try:
        response, alerts = await _call(client, request)
    except LlmUnavailable as exc:
        return _m2("narrate", template, bundle, view, ids, exc.reason)
    if alerts:
        out = _m2("narrate", template, bundle, view, ids, "tool_request")
        out.alerts = alerts
        return out
    text = response.text().strip()
    problems = verify(text, view.fields(), ids) if text else [Violation("empty", "no text")]
    if problems:
        out = _m2("narrate", template, bundle, view, ids, "verifier_rejected")
        out.violations = [str(p) for p in problems]
        out.model, out.usage, out.call_id = response.model, response.usage, response.call_id
        return out
    values = slot_values(bundle)
    return NodeOutcome(
        node="narrate",
        path="llm",
        text=text,
        rendered=render_text(text, values),
        slots_shown=used_values(text, values),
        model=response.model,
        usage=response.usage,
        call_id=response.call_id,
    )


def rationale_problems(out: RationaleOut, view: EvidenceView, ids: frozenset[str]) -> list[Violation]:
    problems = verify(out.rationale, view.fields(), ids)
    refs = {r.ref.id: r for r in view.refs}
    for eid in out.evidence_ids:
        if eid not in refs:
            problems.append(Violation("unknown_evidence", eid))
        elif refs[eid].ref.trust in UNTRUSTED:
            problems.append(Violation("quarantined_evidence_cited", eid))
    used = {ref for ref, _ in (k.split(".", 1) for k in _slot_keys(out.rationale))}
    for ref in sorted(used - set(out.evidence_ids)):
        problems.append(Violation("slot_not_listed_as_evidence", ref))
    return problems


def _slot_keys(text: str) -> list[str]:
    from sgw.agent.render.slots import used_slots

    return [f"{r}.{f}" for r, f in used_slots(text)]


async def draft_rationale(
    *,
    client: LlmClient,
    config: NodeConfig,
    bundle: EvidenceBundle,
    view: EvidenceView,
    ids: frozenset[str],
    proposal: dict[str, Any],
    run_id: str | None = None,
    model_override: str | None = None,
) -> NodeOutcome:
    action = f"{proposal['action_type']} at {', '.join(proposal['target_ids'])}"
    request = LlmRequest(
        node="draft_rationale",
        config=config,
        system=system_blocks("draft_rationale", config),
        messages=[
            {
                "role": "user",
                "content": (
                    RATIONALE_USER_TEMPLATE.format(
                        action=action,
                        case=proposal["decision_case_id"],
                        tier=proposal["tier"],
                        evidence=view.text,
                    )
                    if config.prompt_version == "v1"
                    else RATIONALE_USER_TEMPLATE_V2.format(
                        action=action, case=proposal["decision_case_id"], evidence=view.text
                    )
                ),
            }
        ],
        classes=view.classes,
        run_id=run_id,
        output_schema=RATIONALE_SCHEMA,
        model_override=model_override,
    )
    fallback = rationale_template(proposal, bundle)

    def m2(reason: str) -> NodeOutcome:
        out = _m2("draft_rationale", fallback["rationale"], bundle, view, ids, reason)
        out.structured = fallback
        return out

    try:
        response, alerts = await _call(client, request)
    except LlmUnavailable as exc:
        return m2(exc.reason)
    if alerts:
        out = m2("tool_request")
        out.alerts = alerts
        return out
    try:
        parsed = RationaleOut.model_validate(json.loads(response.text()))
    except (ValueError, ValidationError) as exc:
        out = m2("schema_invalid")
        out.violations = [f"schema_invalid: {type(exc).__name__}"]
        return out
    problems = rationale_problems(parsed, view, ids)
    if problems:
        out = m2("verifier_rejected")
        out.violations = [str(p) for p in problems]
        out.model, out.usage, out.call_id = response.model, response.usage, response.call_id
        return out
    values = slot_values(bundle)
    return NodeOutcome(
        node="draft_rationale",
        path="llm",
        text=parsed.rationale,
        rendered=render_text(parsed.rationale, values),
        slots_shown=used_values(parsed.rationale, values),
        model=response.model,
        usage=response.usage,
        call_id=response.call_id,
        structured=parsed.model_dump(mode="json"),
    )
