"""One single-call LLM text node for the report graphs (etr_brief, sitrep, after_action_summary).

Same path as the spine's `narrate`: view -> one gateway call (tags, classes from the view) -> refusal,
truncation and tool-request checks -> D-073 verifier -> render. Any failure takes the M2 template with the
same slots. A fixed code sentence (`closing`, e.g. the ETR caveat) is appended on both paths and verified
with the rest.
"""

from __future__ import annotations

from sgw.agent.nodes.llm import LlmClient, LlmRequest, LlmUnavailable
from sgw.agent.nodes.templates import M2_NOTE
from sgw.agent.nodes.text_nodes import NodeOutcome, _call
from sgw.agent.render.evidence import EvidenceBundle, EvidenceView
from sgw.agent.render.slots import render_text, slot_values, used_values
from sgw.agent.render.verify import Violation, verify
from sgw.contracts.llm_nodes import NodeConfig
from sgw.reports.prompts import SYSTEM_PROMPTS, USER_TEMPLATE


class TemplateDrift(RuntimeError):
    pass


def _outcome(
    node: str, path: str, text: str, bundle: EvidenceBundle, reason: str | None = None
) -> NodeOutcome:
    values = slot_values(bundle)
    return NodeOutcome(
        node=node,
        path=path,  # type: ignore[arg-type]
        text=text,
        rendered=render_text(text, values),
        slots_shown=used_values(text, values),
        reason=reason,
    )


def _join(text: str, closing: str) -> str:
    return f"{text.strip()} {closing}".strip() if closing else text.strip()


async def write(
    *,
    node: str,
    client: LlmClient,
    config: NodeConfig,
    bundle: EvidenceBundle,
    view: EvidenceView,
    ids: frozenset[str],
    task: str,
    what: str,
    template: str,
    closing: str = "",
    run_id: str | None = None,
    model_override: str | None = None,
) -> NodeOutcome:
    fields = view.fields()

    def m2(reason: str) -> NodeOutcome:
        text = _join(_join(template, closing), M2_NOTE)
        problems = verify(text, fields, ids)
        if problems:
            raise TemplateDrift(f"M2 template for {node} fails the verifier: {[str(p) for p in problems]}")
        return _outcome(node, "m2", text, bundle, reason)

    request = LlmRequest(
        node=node,
        config=config,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPTS[node][config.prompt_version],
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {"role": "user", "content": USER_TEMPLATE.format(task=task, evidence=view.text, what=what)}
        ],
        classes=view.classes,
        run_id=run_id,
        model_override=model_override,
    )
    try:
        response, alerts = await _call(client, request)
    except LlmUnavailable as exc:
        return m2(exc.reason)
    if alerts:
        out = m2("tool_request")
        out.alerts = alerts
        return out
    model_text = response.text().strip()
    text = _join(model_text, closing)
    problems = verify(text, fields, ids) if model_text else [Violation("empty", "no text")]
    if problems:
        out = m2("verifier_rejected")
        out.violations = [str(p) for p in problems]
        out.model, out.usage, out.call_id = response.model, response.usage, response.call_id
        return out
    out = _outcome(node, "llm", text, bundle)
    out.model, out.usage, out.call_id = response.model, response.usage, response.call_id
    return out
