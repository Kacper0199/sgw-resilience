"""Graph nodes of `etr`, `sitrep` and `after_action` on top of the shared spine.

Reused spine nodes: `input_guard` (notes quarantined, run tainted), `verify` (re-verify every shown text and
re-derive its values), `policy_gate` (draft through the proposal port, tier from the approval policy),
`approval` (interrupt; the resume value is never an approval), `execute` and `audit`. The nodes here load
code-computed evidence, call one LLM text node each, publish the ETR only after the store says approved,
and render the after-action and SC 103-314 drafts.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from langgraph.runtime import Runtime

from sgw.agent.nodes import spine
from sgw.agent.nodes.gate import gated
from sgw.agent.nodes.llm import node_config
from sgw.agent.render.evidence import EvidenceBundle, EvidenceItem, build_view
from sgw.contracts.api_models import ProposalCreate
from sgw.contracts.vocab import ActionType, Classification
from sgw.models.restoration.publish import EtrEstimate
from sgw.reports import evidence as ev
from sgw.reports import narrative, sc_103_314, templates
from sgw.reports.after_action import AfterActionReview, ChainCheck, ClockResult, chain_alert
from sgw.reports.publisher import (
    AlreadyPublished,
    EtrPublisher,
    MemoryEtrPublisher,
    NotApproved,
    approved_params,
)
from sgw.reports.scorecard import ACTUAL_LABEL, EstimateScore
from sgw.reports.seed import ETR_CASE
from sgw.reports.seed import TERRITORY as GLOBAL_TARGET
from sgw.reports.sources import EtrCaveat, ReplayStatus, etr_caveat, replay_status

SITREP_CASE = "DC-W7-SITREP"


@dataclass
class ReportDeps(spine.SpineDeps):
    member_table: Any = field(default_factory=dict)
    extra_ids: frozenset[str] = templates.QUANTILE_IDS
    estimates: Callable[[], Sequence[EtrEstimate]] | None = None
    caveat: Callable[[float], EtrCaveat] = etr_caveat
    status: Callable[[datetime], ReplayStatus] = replay_status
    open_clocks: Callable[[datetime], Sequence[ClockResult]] = lambda _at: ()
    cosign_open: Callable[[], int | None] = lambda: None
    review: Callable[[datetime], AfterActionReview] | None = None
    on_chain_broken: Callable[[ChainCheck], bool] | None = None
    scorecard: Callable[[], Sequence[EstimateScore]] | None = None
    interruptions: Callable[[], sc_103_314.InterruptionReport] = sc_103_314.build
    publisher: EtrPublisher = field(default_factory=MemoryEtrPublisher)
    as_of: datetime | None = None
    issue_offset_h: float = 24.0
    etr_case_id: str = ETR_CASE
    etr_case: Callable[[], str] | None = None
    sitrep_case_id: str = SITREP_CASE


class ReportState(spine.SpineState, total=False):
    estimates: list[dict[str, Any]]
    report: dict[str, Any]


ReportNode = Callable[[ReportState, Runtime[spine.SpineDeps]], Awaitable[dict[str, Any]]]


def report_node(name: str, *, llm: bool = False) -> Callable[[ReportNode], ReportNode]:
    """`spine.node` (K12 span, K4 step/agent events) for nodes that read the report keys of the state."""
    return spine.node(name, llm=llm)  # type: ignore[return-value]


def _deps(runtime: Runtime[spine.SpineDeps]) -> ReportDeps:
    deps = runtime.context
    if not isinstance(deps, ReportDeps):
        raise TypeError("report graphs need ReportDeps")
    return deps


def _bundle_out(state: ReportState, deps: ReportDeps, items: list[EvidenceItem], kind: str) -> dict[str, Any]:
    bundle = EvidenceBundle(run_id=state["run_id"], items=items)
    view = build_view(bundle, route=deps.route)
    values = ev_values(bundle)
    spine.emit(
        "artifact",
        {
            "kind": "evidence",
            "items": [
                {"id": i.id, "kind": i.kind, "label": i.label, "citation": i.citation, "values": values[i.id]}
                for i in items
            ],
            "prompt_classes": [c.value for c in view.classes],
        },
        Classification.C2,
    )
    return {
        "bundle": bundle.model_dump(mode="json"),
        "view": view.model_dump(mode="json"),
        "audit": [
            {"kind": "evidence", "graph": kind, "items": len(items), "prompt_classes": view.header_value()}
        ],
    }


def ev_values(bundle: EvidenceBundle) -> dict[str, dict[str, str]]:
    from sgw.agent.render.slots import slot_values

    return slot_values(bundle)


def _start(phase: str) -> spine.Node:
    @spine.node("load_context")
    async def load(state: spine.SpineState, runtime: Runtime[spine.SpineDeps]) -> dict[str, Any]:
        return {
            "phase": phase,
            "status": "running",
            "audit": [{"kind": "run_start", "graph": state.get("graph"), "user_id": state.get("user_id")}],
        }

    return load


etr_start = _start("D4 global estimated time of restoration")
sitrep_start = _start("W7 situation report")
after_action_start = _start("D5 after-action review")


@report_node("etr_evidence")
async def etr_evidence(state: ReportState, runtime: Runtime[spine.SpineDeps]) -> dict[str, Any]:
    deps = _deps(runtime)
    if deps.estimates is None:
        raise ValueError("no ETR source configured")
    estimates = list(deps.estimates())
    g = ev.global_estimate(estimates)
    items = ev.etr_items(estimates, deps.caveat(deps.issue_offset_h))
    request = ProposalCreate(
        decision_case_id=deps.etr_case() if deps.etr_case else deps.etr_case_id,
        action_type=ActionType.PUBLISH_GLOBAL_ETR,
        params=approved_params(estimates),
        target_ids=[GLOBAL_TARGET],
        evidence_ids=["E1"],
    )
    preview = spine.policy_preview(request, state.get("user_id", "unknown"))
    if deps.policy_evidence:
        items.append(spine.policy_item(len(items) + 1, preview, g.as_of_utc))
    out = _bundle_out(state, deps, items, "etr")
    out["estimates"] = [e.model_dump(mode="json") for e in estimates]
    out["proposal"] = {**request.model_dump(mode="json"), "tier": preview.tier}
    return out


async def _write(
    state: ReportState,
    deps: ReportDeps,
    node: str,
    task: str,
    what: str,
    template: str,
    closing: str = "",
) -> dict[str, Any]:
    bundle, view = spine._bundle(state), spine._view(state)
    out = (
        await narrative.write(
            node=node,
            client=gated(deps.llm, deps.llm_gate),
            config=node_config(node, deps.nodes_file),
            bundle=bundle,
            view=view,
            ids=spine._ids(state, deps),
            task=task,
            what=what,
            template=template,
            closing=closing,
            run_id=state.get("run_id"),
            model_override=deps.model_overrides.get(node),
        )
    ).as_state()
    spine._mark_path(out)
    return {
        "narrative": out,
        "alerts": out["alerts"],
        "audit": [
            {"kind": node, "path": out["path"], "reason": out["reason"], "violations": out["violations"]}
        ],
    }


@report_node("etr_brief", llm=True)
async def etr_brief(state: ReportState, runtime: Runtime[spine.SpineDeps]) -> dict[str, Any]:
    deps = _deps(runtime)
    bundle = spine._bundle(state)
    out = await _write(
        state,
        deps,
        "etr_brief",
        "brief for the global ETR proposal (D4)",
        "brief",
        templates.etr_template(bundle),
        templates.etr_closing(bundle),
    )
    out["rationale"] = out["narrative"]
    return out


@report_node("execute")
async def etr_execute(state: ReportState, runtime: Runtime[spine.SpineDeps]) -> dict[str, Any]:
    """Publishes `EtrPublished` only when the store says approved and bound to the shown version and hash; the
    publisher burns the execution token in the same transaction. A second execution is answered cleanly."""
    deps = _deps(runtime)
    approval_ = state.get("approval") or {}
    pid = str(approval_.get("proposal_id", ""))
    store_state, version, action_hash = deps.proposals.approval_state(pid)
    bound = version == approval_.get("proposal_version") and action_hash == approval_.get("action_hash")
    if store_state == "executed" and bound:
        return {
            "status": "executed",
            "execution": {"already_executed": True},
            "audit": [{"kind": "execute_refused", "proposal_id": pid, "code": AlreadyPublished.code}],
        }
    if store_state != "approved" or not bound:
        status = "awaiting_approval" if store_state in ("proposed", "in_review", "draft") else "blocked"
        return {
            "status": status,
            "execution": {},
            "audit": [
                {"kind": "execute_refused", "proposal_id": pid, "store_state": store_state, "bound": bound}
            ],
        }
    estimates = [EtrEstimate.model_validate(e) for e in state.get("estimates") or []]
    at = deps.as_of or ev.global_estimate(estimates).as_of_utc
    params = dict((state.get("proposal") or {}).get("params") or {})
    try:
        out = deps.publisher.publish(
            pid,
            estimates,
            proposal_version=int(approval_["proposal_version"]),
            action_hash=str(approval_["action_hash"]),
            params=params,
            published_by=state.get("user_id", "unknown"),
            at=at,
        )
    except AlreadyPublished as exc:
        return {
            "status": "executed",
            "execution": {"already_executed": True},
            "audit": [{"kind": "execute_refused", "code": AlreadyPublished.code, "detail": str(exc)}],
        }
    except NotApproved as exc:
        return {
            "status": "blocked",
            "execution": {},
            "audit": [{"kind": "execute_refused", "detail": str(exc)}],
        }
    events, effect = out.events, out.effect_id
    published = [e.estimate_id for e in events]
    spine.emit(
        "artifact",
        {
            "kind": "etr_published",
            "proposal_id": pid,
            "estimate_ids": published,
            "replay_overlay_allowed": all(e.replay_overlay_allowed for e in estimates),
        },
    )
    return {
        "status": "executed",
        "execution": {"effect_id": effect, "published": published, "events": len(events)},
        "audit": [{"kind": "execute", "proposal_id": pid, "effect_id": effect, "etr_published": len(events)}],
    }


@report_node("sitrep_evidence")
async def sitrep_evidence(state: ReportState, runtime: Runtime[spine.SpineDeps]) -> dict[str, Any]:
    deps = _deps(runtime)
    estimates = list(deps.estimates()) if deps.estimates is not None else []
    etr = ev.global_estimate(estimates) if estimates else None
    as_of = deps.as_of or (etr.as_of_utc if etr is not None else None)
    if as_of is None:
        raise ValueError("sitrep needs an as-of time or a published ETR")
    status = deps.status(as_of)
    items = ev.sitrep_items(status, etr, deps.open_clocks(as_of), deps.cosign_open())
    out = _bundle_out(state, deps, items, "sitrep")
    out["report"] = {"kind": "sitrep", "as_of_utc": status.as_of.isoformat()}
    return out


@report_node("sitrep", llm=True)
async def sitrep_text(state: ReportState, runtime: Runtime[spine.SpineDeps]) -> dict[str, Any]:
    deps = _deps(runtime)
    out = await _write(
        state,
        deps,
        "sitrep",
        "situation report paragraph",
        "sitrep",
        templates.sitrep_template(spine._bundle(state)),
    )
    return out


@report_node("sitrep_draft")
async def sitrep_draft(state: ReportState, runtime: Runtime[spine.SpineDeps]) -> dict[str, Any]:
    """T1 (PLAN tier table: work-order or sitrep draft, promotion by a person). The tier comes from the
    approval policy; the graph never promotes: it hands the verified draft to people and ends."""
    if state.get("status") == "blocked":
        return {"audit": [{"kind": "sitrep_draft", "drafted": False}]}
    deps = _deps(runtime)
    request = ProposalCreate(
        decision_case_id=deps.sitrep_case_id,
        action_type=ActionType.SITREP_DRAFT,
        params={"as_of_utc": str((state.get("report") or {}).get("as_of_utc", ""))},
        target_ids=[GLOBAL_TARGET],
        evidence_ids=[i.id for i in spine._bundle(state).items],
    )
    preview = spine.policy_preview(request, state.get("user_id", "unknown"))
    n = state["narrative"]
    draft = {
        "kind": "sitrep_draft",
        "tier": preview.tier,
        "promotion": "by a person",
        "path": n["path"],
        "rendered": n["rendered"],
        "slots": n["slots_shown"],
        "tainted": bool(state.get("tainted")),
    }
    spine.emit("artifact", draft, Classification.C2)
    return {
        "report": {**(state.get("report") or {}), **draft},
        "status": "draft_ready",
        "audit": [{"kind": "sitrep_draft", "drafted": True, "tier": preview.tier, "path": n["path"]}],
    }


@report_node("after_action_evidence")
async def after_action_evidence(state: ReportState, runtime: Runtime[spine.SpineDeps]) -> dict[str, Any]:
    deps = _deps(runtime)
    if deps.review is None or deps.as_of is None:
        raise ValueError("after-action needs a review source and a review time")
    review = deps.review(deps.as_of)
    sc = deps.interruptions()
    out = _bundle_out(state, deps, ev.after_action_items(review, sc), "after_action")
    out["report"] = {"review": review.model_dump(mode="json"), "sc_103_314": sc.model_dump(mode="json")}
    if not review.chain.ok:
        alert = chain_alert(review.chain)
        recorded = deps.on_chain_broken(review.chain) if deps.on_chain_broken is not None else False
        spine.emit("artifact", {"kind": "security_alert", **alert}, Classification.C2)
        out["alerts"] = [alert]
        out["audit"] = [*out["audit"], {"kind": "security_alert", "alert": alert, "recorded": recorded}]
    return out


@report_node("after_action_summary", llm=True)
async def after_action_summary(state: ReportState, runtime: Runtime[spine.SpineDeps]) -> dict[str, Any]:
    deps = _deps(runtime)
    return await _write(
        state,
        deps,
        "after_action_summary",
        "after-action review summary (D5)",
        "summary",
        templates.after_action_template(spine._bundle(state)),
    )


@report_node("render_reports")
async def render_reports(state: ReportState, runtime: Runtime[spine.SpineDeps]) -> dict[str, Any]:
    """Drafts only after the verifier passed: the after-action review and the SC 103-314 report."""
    if state.get("status") == "blocked":
        return {"audit": [{"kind": "render_reports", "rendered": False}]}
    report = dict(state.get("report") or {})
    summary = state["narrative"]["rendered"]
    sc = sc_103_314.InterruptionReport.model_validate(report["sc_103_314"])
    review = AfterActionReview.model_validate(report["review"])
    banner = None if review.usable else chain_banner(review)
    report["sc_103_314_markdown"] = sc_103_314.render_markdown(sc, banner)
    source = _deps(runtime).scorecard
    scores = list(source()) if source is not None else []
    report["after_action_markdown"] = render_after_action(review, summary, scores)
    report["etr_scorecard"] = [x.model_dump(mode="json") for x in scores]
    report["usable"] = review.usable
    for kind in ("after_action_markdown", "sc_103_314_markdown"):
        spine.emit("artifact", {"kind": kind, "markdown": report[kind]}, Classification.C2)
    return {
        "report": report,
        "status": "draft_ready",
        "audit": [{"kind": "render_reports", "rendered": True, "missed": len(review.missed)}],
    }


def _h(v: float | None) -> str:
    return "-" if v is None else f"{v:+.1f} h"


def _yn(v: bool | None) -> str:
    return "-" if v is None else ("yes" if v else "no")


def chain_banner(review: AfterActionReview) -> str:
    c = review.chain
    return (
        f"> CHAIN BROKEN, NOT FOR USE. The audit chain failed verification at seq {c.first_bad_seq}; records"
        f" after seq {c.trusted_to_seq} are unverifiable and nothing here may be used against named people"
        " until the chain is restored (SEC-52)."
    )


def render_after_action(review: AfterActionReview, summary: str, scores: Sequence[EstimateScore] = ()) -> str:
    """Code-formatted tables (times, counts) beside the verified summary."""
    chain = review.chain
    lines = [
        *([chain_banner(review), ""] if not review.usable else []),
        f"# After-action review (as of {review.as_of:%Y-%m-%d %H:%MZ})",
        "",
        "Synthetic data: Helene replay on the SGW synthetic network.",
        "",
        summary.strip(),
        "",
        "## Audit chain",
        "",
        f"- Verified: {'yes' if chain.ok else 'no'}; checked to seq {chain.checked_to_seq};"
        f" signed head {chain.signed_head_seq if chain.signed_head_seq is not None else 'none'};"
        f" first bad seq {chain.first_bad_seq if chain.first_bad_seq is not None else 'none'}.",
        "",
        "## Decision clocks",
        "",
        "| Case | Step | Effective decide-by | Decided | How | Outcome | Margin |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in review.clocks:
        decided = f"{c.decided_at:%Y-%m-%d %H:%MZ}" if c.decided_at else "-"
        margin = f"{c.margin_min:+d} min" if c.margin_min is not None else "-"
        lines.append(
            f"| {c.decision_case_id} | {c.step} | {c.effective_decide_by:%Y-%m-%d %H:%MZ} | {decided}"
            f" | {c.decided_by or '-'} | {c.outcome} | {margin} |"
        )
    lines += [
        "",
        "## Break-glass uses (each flagged for this review)",
        "",
        "| Id | Proposal | IC | Used | Co-sign due | Co-signed by | Status | Table agrees |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for b in review.break_glass:
        lines.append(
            f"| {b.break_glass_id} | {b.proposal_id} | {b.ic_id} | {b.used_at:%Y-%m-%d %H:%MZ}"
            f" | {b.cosign_due:%Y-%m-%d %H:%MZ} | {b.cosigned_by or '-'} | {b.status}"
            f" | {'yes' if b.table_agrees else 'NO'} |"
        )
    if not review.break_glass:
        lines.append("| - | - | - | - | - | - | none | - |")
    lines += ["", f"## ETR forecast vs {ACTUAL_LABEL}", ""]
    if scores:
        lines += [
            f"Scored against the restoration model's own simulated restoration ({ACTUAL_LABEL});"
            " one storm, in-sample. Calibration on many storms is in the model evaluation report.",
            "",
            "| Estimate | Area | P50 error | Analog error | In P25-P75 | In P10-P90 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        lines += [
            f"| {x.estimate_id} | {x.region_id} | {_h(x.p50_error_h)} | {_h(x.analog_abs_error_h)}"
            f" | {_yn(x.in_p25_p75)} | {_yn(x.in_p10_p90)} |"
            for x in scores
        ]
    else:
        lines.append("No published ETR to score.")
    lines += [
        "",
        "## Ledger timeline",
        "",
        "| Seq | Time | Kind | Actor | Subject |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {t.seq} | {t.occurred_at:%Y-%m-%d %H:%MZ} | {t.kind} | {t.actor_id} | {t.subject} |"
        for t in review.timeline
    ]
    return "\n".join(lines) + "\n"
