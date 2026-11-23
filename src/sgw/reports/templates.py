"""M2 templates and fixed code sentences of the report graphs.

Templates write the same slots the model is asked to write, so the values a reader sees are identical on the
LLM path and the template path (SC-7); they go through the same verifier. The ETR caveat is never left to the
model: code appends it on both paths, from the K17 coverage rows (WP-17 framing).
"""

from __future__ import annotations

from sgw.agent.render.evidence import EvidenceBundle, EvidenceItem

QUANTILE_IDS = frozenset({"P25", "P75"})


def _first(bundle: EvidenceBundle, kind: str) -> EvidenceItem | None:
    return next((i for i in bundle.items if i.kind == kind), None)


def _all(bundle: EvidenceBundle, kind: str) -> list[EvidenceItem]:
    return [i for i in bundle.items if i.kind == kind]


def _policy(bundle: EvidenceBundle) -> str:
    p = _first(bundle, "approval_policy")
    if p is None:
        return ""
    return (
        f" The approval policy sets tier {{{p.id}.tier}} for this action;"
        f" it needs {{{p.id}.approver_functions}}."
    )


def etr_caveat(bundle: EvidenceBundle) -> str:
    c = _first(bundle, "etr_caveat")
    g = _first(bundle, "etr_estimate")
    if c is None or g is None:
        return ""
    text = (
        f"Caveat: on a test set of {{{c.id}.storms}} storms, all synthetic and Helene-like, the P10 to P90"
        f" interval contained the actual time {{{c.id}.coverage80}} of the time and the P25 to P75 band"
        f" {{{c.id}.coverage50}}; the"
        " simulator matches Helene's median county restoration times by construction but not how widely"
        " counties varied, and the estimate has not been checked against a real storm."
    )
    if g.hints.get("replay_overlay") == "not_allowed":
        text += (
            " The estimate is not drawn on the replayed outage curve, which comes from a different"
            " restoration process."
        )
    return text


def etr_closing(bundle: EvidenceBundle) -> str:
    return (etr_caveat(bundle) + _policy(bundle)).strip()


def etr_template(bundle: EvidenceBundle) -> str:
    g = _first(bundle, "etr_estimate")
    if g is None:
        raise ValueError("ETR bundle without a global estimate")
    e = g.id
    parts = [
        f"The global estimate for {{{e}.target}} is {{{e}.p50}} (P25 to P75: {{{e}.p25}} to {{{e}.p75}}),"
        f" issued at {{{e}.as_of}}, {{{e}.p50_hours}} ahead.",
        f"Customers out now: {{{e}.customers_out_now}}, against a peak of"
        f" {{{e}.peak_customers_out}} customers.",
    ]
    regions = _all(bundle, "etr_region")
    if regions:
        listed = "; ".join(f"{r.label.rsplit(' ', 1)[-1]} at {{{r.id}.p50}}" for r in regions)
        parts.append(f"Operating areas expected to finish last: {listed}.")
    parts.append("This is an estimate for the named approvers to publish or hold, not a commitment.")
    return " ".join(parts)


def sitrep_template(bundle: EvidenceBundle) -> str:
    s = _first(bundle, "system_status")
    if s is None:
        raise ValueError("sitrep bundle without system status")
    i = s.id
    status = s.hints.get("status", "responding").replace("_", " ").capitalize()
    parts = [
        f"{status}: {{{i}.customers_out_now}} customers out of power at {{{i}.as_of}}, down from a peak of"
        f" {{{i}.peak_customers_out}} at {{{i}.peak_at}}; {{{i}.restored_since_peak}} restored since"
        f" the peak, across {{{i}.counties_out}} counties; the trend is {s.hints.get('trend', 'flat')}."
    ]
    g = _first(bundle, "etr_estimate")
    if g is not None:
        parts.append(
            f"Estimated restoration (global, P50): {{{g.id}.p50}}, band {{{g.id}.p25}} to {{{g.id}.p75}};"
            " an estimate, not a commitment."
        )
    for c in _all(bundle, "decision_clock"):
        parts.append(f"Open decision: {c.label}, decide by {{{c.id}.decide_by}}.")
    gov = _first(bundle, "governance")
    if gov is not None:
        parts.append(f"Break-glass co-signatures still open: {{{gov.id}.cosign_open}}.")
    return " ".join(parts)


def after_action_template(bundle: EvidenceBundle) -> str:
    chain = _first(bundle, "audit_chain")
    clocks = _first(bundle, "clock_outcomes")
    bg = _first(bundle, "break_glass")
    sc = _first(bundle, "interruption_record")
    if chain is None or clocks is None or bg is None or sc is None:
        raise ValueError("after-action bundle is incomplete")
    if chain.hints.get("chain") == "verified":
        parts = [
            f"The audit chain verified before the review, checked through record {{{chain.id}.checked_to}}."
        ]
    else:
        parts = [
            f"The audit chain did not verify (checked through record {{{chain.id}.checked_to}});"
            " facts after the first bad record are excluded from this review."
        ]
    u = _first(bundle, "unverifiable")
    if u is not None:
        parts.append(
            f"Not for use: after record {{{u.id}.trusted_to}} nothing can be verified;"
            f" {{{u.id}.clocks}} decision clocks and {{{u.id}.break_glass}} break-glass uses are"
            " unverifiable, not missed or overdue."
        )
    c = clocks.id
    parts.append(f"Decision clocks: {{{c}.met}} met, {{{c}.missed}} missed, {{{c}.open}} still open.")
    for m in _all(bundle, "missed_clock"):
        how = m.hints.get("how", "not_decided")
        when = (
            f"decided at {{{m.id}.decided_at}}" + (" by break-glass" if how == "break_glass" else "")
            if "decided_at" in m.values
            else "not decided"
        )
        parts.append(f"Missed: {m.label}, due by {{{m.id}.decide_by}}, {when}.")
    b = bg.id
    parts.append(
        f"Break-glass uses: {{{b}.uses}}; co-signed in time {{{b}.cosigned_on_time}},"
        f" late {{{b}.cosigned_late}}, overdue and unsigned {{{b}.overdue_unsigned}},"
        f" awaiting {{{b}.awaiting_cosign}}; each use is flagged for this review."
    )
    s = sc.id
    until = (
        f"from {{{s}.started}}, not yet restored ({{{s}.duration}} so far)"
        if sc.hints.get("restored") == "no"
        else f"from {{{s}.started}} to {{{s}.restored}} ({{{s}.duration}})"
    )
    parts.append(
        f"South Carolina interruption: {until}, {{{s}.customers}} customers interrupted;"
        f" {{{s}.counties_reportable}} counties over the {{{s}.threshold}} threshold."
    )
    if sc.hints.get("report") == "required":
        parts.append("A complete report is due under the state's interruption-of-service rule.")
    return " ".join(parts)
