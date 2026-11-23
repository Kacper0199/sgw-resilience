"""M2 templates: the deterministic text path used when the LLM is unavailable, refuses, truncates, asks for a
tool or fails the verifier. Templates write the same slots as the model, so the rendered values are
identical on both paths (SC-7); they are verified like model text, so a template drift is caught too."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sgw.agent.render.evidence import UNTRUSTED, EvidenceBundle, EvidenceItem

VERDICT_TEXT = {
    "act_now": (
        "the platform's no-regret test says waiting for the next advisory does not fit inside the margin"
    ),
    "decide_now": (
        "the decide-by has passed or no later advisory is due, so the platform shows it as decide now"
    ),
    "wait_for_next_advisory": "the platform's no-regret test says waiting for the next advisory still fits",
}
M2_NOTE = "Template text: the language model was not used for this brief; every value is computed."


def _clock_sentence(item: EvidenceItem) -> str:
    ref = item.id
    s = f"{item.label}: decide by {{{ref}.decide_by}}"
    if "decide_by_p10" in item.values and "decide_by_p90" in item.values:
        s += f" (range {{{ref}.decide_by_p10}} to {{{ref}.decide_by_p90}})"
    if "consequence" in item.values and "lead_time" in item.values:
        s += (
            f", against a consequence expected around {{{ref}.consequence}}"
            f" and a lead time of {{{ref}.lead_time}}"
        )
    effective, own = item.values.get("effective_decide_by"), item.values.get("decide_by")
    if effective is not None and own is not None and effective.value != own.value:
        s += f"; a later step depends on it, so the binding decide-by is {{{ref}.effective_decide_by}}"
    verdict = VERDICT_TEXT.get(item.hints.get("verdict", ""))
    if verdict:
        s += f"; {verdict}"
    if item.hints.get("critical_path") == "on":
        s += "; it is on the critical path"
    return s + "."


def _policy_sentence(item: EvidenceItem) -> str:
    return (
        f"The approval policy sets tier {{{item.id}.tier}} for the proposed action; it needs "
        f"{{{item.id}.approver_functions}}."
    )


def narrate_template(bundle: EvidenceBundle, include: Sequence[str] | None = None) -> str:
    items = [i for i in bundle.items if include is None or i.id in include]
    lines = [_clock_sentence(i) for i in items if i.kind == "decision_clock" and i.trust not in UNTRUSTED]
    for i in items:
        if i.kind == "event_type":
            lines.append(
                f"Event type: the platform recommends {{{i.id}.recommended_type}},"
                f" with {{{i.id}.escalation_type}}"
                " as the escalation to be ready for; the Incident Commander sets the type."
            )
    if any(i.trust in UNTRUSTED for i in items):
        lines.append("A free-text report is quarantined for review and is not used as evidence.")
    lines.extend(_policy_sentence(i) for i in items if i.kind == "approval_policy")
    lines.append("Each action waits for its named approvers; nothing has been decided.")
    lines.append(M2_NOTE)
    return " ".join(lines)


def rationale_template(proposal: Mapping[str, Any], bundle: EvidenceBundle) -> dict[str, Any]:
    case_id = proposal["decision_case_id"]
    clock = next(
        (i for i in bundle.items if i.kind == "decision_clock" and case_id in i.entity_ids),
        None,
    )
    ids = [clock.id] if clock else []
    text = "The action follows the computed decision clock"
    if clock is not None:
        text = (
            f"The action answers the decision case {clock.label}, due by {{{clock.id}.decide_by}}"
            " with a lead "
            f"time of {{{clock.id}.lead_time}}"
        )
    text += "; the approvers decide."
    policy = next((i for i in bundle.items if i.kind == "approval_policy"), None)
    if policy is not None:
        text += " " + _policy_sentence(policy)
        ids.append(policy.id)
    text += " " + M2_NOTE
    return {
        "rationale": text,
        "preconditions": ["crews_available", "yard_outside_hazard_zone"],
        "evidence_ids": ids,
    }
