"""Evidence items (K15, values in code) for the ETR, sitrep and after-action graphs.

Items are built in a fixed, code-decided order so prompts and replay hashes are stable; every value a reader
sees comes from a slot. Hints are closed enums without digits.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sgw.agent.render.evidence import EvidenceItem, SlotValue
from sgw.contracts.vocab import Classification, Trust
from sgw.models.restoration.publish import EtrEstimate
from sgw.reports.after_action import AfterActionReview, ClockResult
from sgw.reports.sc_103_314 import InterruptionReport
from sgw.reports.sources import EtrCaveat, ReplayStatus

ETR_CITATION = "WP-17 ETR model (restoration Monte Carlo, conformal calibration)"
CAVEAT_CITATION = "evals/reports/etr.json (family-A test storms)"
REPLAY_CITATION = "Helene replay, county hourly customers out (synthetic data)"
AUDIT_CITATION = "audit chain (hash-chained, verified before use)"
SC_CITATION = "SC 103-314 interruption records from the replayed section outages (synthetic data)"
REGIONS_SHOWN = 3


def _t(v: datetime) -> SlotValue:
    return SlotValue(value=v, format="utc_minute")


def _n(v: int, unit: str | None = None) -> SlotValue:
    return SlotValue(value=v, format="count", unit=unit)


def _h(v: float) -> SlotValue:
    return SlotValue(value=round(v, 1), format="hours")


def _ppm(v: int) -> SlotValue:
    return SlotValue(value=v, format="percent_ppm")


def _item(n: int, kind: str, label: str, as_of: datetime, citation: str, **kw: object) -> EvidenceItem:
    return EvidenceItem.model_validate(
        {
            "id": f"E{n}",
            "kind": kind,
            "label": label,
            "as_of": as_of,
            "citation": citation,
            "classification": Classification.C1,
            "trust": Trust.SYSTEM,
            **kw,
        }
    )


def global_estimate(estimates: Sequence[EtrEstimate]) -> EtrEstimate:
    found = [e for e in estimates if e.scope == "global"]
    if len(found) != 1:
        raise ValueError(f"expected one global ETR estimate, found {len(found)}")
    return found[0]


def _etr_values(e: EtrEstimate, with_target: bool) -> dict[str, SlotValue]:
    values = {
        "as_of": _t(e.as_of_utc),
        "p25": _t(e.p25_utc),
        "p50": _t(e.p50_utc),
        "p75": _t(e.p75_utc),
        "p50_hours": _h(e.hours_from_as_of["p50"]),
        "band_hours": _h(e.hours_from_as_of["p75"] - e.hours_from_as_of["p25"]),
    }
    if with_target:
        values |= {
            "target": SlotValue(value=e.target, format="text"),
            "peak_customers_out": _n(e.peak_customers_out),
            "customers_out_now": _n(e.customers_out_now),
        }
    return values


def etr_global_item(n: int, e: EtrEstimate) -> EvidenceItem:
    return _item(
        n,
        "etr_estimate",
        "Global estimated time of restoration for the whole service territory (all operating areas)",
        e.as_of_utc,
        ETR_CITATION,
        model_version=e.model_version,
        values=_etr_values(e, with_target=True),
        hints={
            "calibration": "calibrated" if e.calibrated else "uncalibrated",
            "replay_overlay": "allowed" if e.replay_overlay_allowed else "not_allowed",
        },
        entity_ids=[e.region_id],
    )


def etr_items(estimates: Sequence[EtrEstimate], caveat: EtrCaveat) -> list[EvidenceItem]:
    """E1 global estimate, then the operating areas that finish last (by P50, then id), then the caveat."""
    g = global_estimate(estimates)
    regions = sorted(
        (e for e in estimates if e.scope == "region"), key=lambda e: (e.p50_utc, e.region_id), reverse=True
    )[:REGIONS_SHOWN]
    items = [etr_global_item(1, g)]
    for e in regions:
        items.append(
            _item(
                len(items) + 1,
                "etr_region",
                f"Estimated time of restoration for operating area {e.region_id}",
                e.as_of_utc,
                ETR_CITATION,
                model_version=e.model_version,
                values=_etr_values(e, with_target=False),
                hints={"order": "finishes_late"},
                entity_ids=[e.region_id],
            )
        )
    items.append(
        _item(
            len(items) + 1,
            "etr_caveat",
            "How often the ETR intervals held on synthetic Helene-like test storms (not a real storm)",
            g.as_of_utc,
            CAVEAT_CITATION,
            values={
                "coverage80": _ppm(caveat.coverage80_ppm),
                "coverage50": _ppm(caveat.coverage50_ppm),
                "storms": _n(caveat.n_storms),
            },
            hints={"evidence": "synthetic_only", "real_storm": "not_checked"},
        )
    )
    return items


def clock_item(n: int, c: ClockResult, as_of: datetime) -> EvidenceItem:
    return _item(
        n,
        "decision_clock",
        f"{c.title} ({c.step}, decision case {c.decision_case_id})",
        as_of,
        "decision_case (clocks service)",
        values={"decide_by": _t(c.effective_decide_by)},
        hints={"state": "open"},
        entity_ids=[c.decision_case_id],
    )


def sitrep_items(
    status: ReplayStatus,
    etr: EtrEstimate | None,
    open_clocks: Sequence[ClockResult],
    cosign_open: int | None = None,
) -> list[EvidenceItem]:
    items = [
        _item(
            1,
            "system_status",
            "Customers out of power across the service territory (electric)",
            status.as_of,
            REPLAY_CITATION,
            values={
                "as_of": _t(status.as_of),
                "customers_out_now": _n(status.customers_out_now),
                "peak_customers_out": _n(status.peak_customers_out),
                "peak_at": _t(status.peak_at),
                "restored_since_peak": _ppm(status.restored_since_peak_ppm),
                "counties_out": _n(status.counties_out),
            },
            hints={
                "trend": status.trend,
                "status": "restoring" if status.trend == "falling" else "responding",
            },
        )
    ]
    if etr is not None:
        item = etr_global_item(len(items) + 1, etr)
        keep = ("p25", "p50", "p75", "as_of")
        items.append(item.model_copy(update={"values": {k: item.values[k] for k in keep}}))
    for c in open_clocks:
        items.append(clock_item(len(items) + 1, c, status.as_of))
    if cosign_open is not None:
        items.append(
            _item(
                len(items) + 1,
                "governance",
                "Break-glass uses still waiting for the second function's co-signature",
                status.as_of,
                AUDIT_CITATION,
                values={"cosign_open": _n(cosign_open)},
            )
        )
    return items


def after_action_items(review: AfterActionReview, sc: InterruptionReport) -> list[EvidenceItem]:
    as_of = review.as_of
    counts = {
        s: sum(1 for b in review.break_glass if b.status == s)
        for s in ("cosigned_on_time", "cosigned_late", "overdue_unsigned", "awaiting_cosign")
    }
    items = [
        _item(
            1,
            "audit_chain",
            "Audit chain verification before the review",
            as_of,
            AUDIT_CITATION,
            values={"checked_to": _n(review.chain.checked_to_seq)},
            hints={
                "chain": "verified" if review.chain.ok else "broken",
                "notary": "signed" if review.chain.signed_head_seq is not None else "unsigned",
            },
        ),
        _item(
            2,
            "clock_outcomes",
            "Decision clocks met, missed and still open at the review time",
            as_of,
            AUDIT_CITATION,
            values={
                "met": _n(len(review.met)),
                "missed": _n(len(review.missed)),
                "open": _n(len(review.open)),
            },
        ),
        _item(
            3,
            "break_glass",
            "Break-glass uses (incident commander alone) and their co-signature status",
            as_of,
            AUDIT_CITATION,
            values={"uses": _n(len(review.break_glass))} | {k: _n(v) for k, v in counts.items()},
            hints={"flag": "after_action_review" if review.break_glass else "none"},
        ),
        _item(
            4,
            "interruption_record",
            "South Carolina system interruption under the state's interruption-of-service rule",
            as_of,
            SC_CITATION,
            values={
                "started": _t(sc.system.started_at),
                **({"restored": _t(sc.system.restored_at)} if sc.system.restored_at is not None else {}),
                "duration": _h(sc.system.duration_h),
                "customers": _n(sc.system.customers_interrupted),
                "counties_reportable": _n(len(sc.reportable)),
                "threshold": _h(sc.threshold_h),
            },
            hints={
                "report": "required" if sc.system.report_required else "not_required",
                **({} if sc.system.restored_at is not None else {"restored": "no"}),
            },
        ),
    ]
    if not review.chain.ok:
        items.append(
            _item(
                len(items) + 1,
                "unverifiable",
                "Decision clocks and break-glass uses that cannot be verified: the audit chain is broken"
                " after the last trusted record",
                as_of,
                AUDIT_CITATION,
                values={
                    "clocks": _n(len(review.unverifiable)),
                    "break_glass": _n(sum(1 for b in review.break_glass if b.status == "unverifiable")),
                    "trusted_to": _n(review.chain.trusted_to_seq),
                },
                hints={"use": "not_for_use"},
            )
        )
    for c in review.missed:
        items.append(
            _item(
                len(items) + 1,
                "missed_clock",
                f"{c.title} ({c.step}, decision case {c.decision_case_id})",
                as_of,
                AUDIT_CITATION,
                values={"decide_by": _t(c.effective_decide_by)}
                | ({"decided_at": _t(c.decided_at)} if c.decided_at else {}),
                hints={"how": c.decided_by or "not_decided"},
                entity_ids=[c.decision_case_id],
            )
        )
    return items
