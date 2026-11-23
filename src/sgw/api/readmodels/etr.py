"""ETR read model: the ETR planner's workspace.

- estimates: WP-17's latest `snapshot` of kind `etr` issued at or before the scenario time
  (`sgw.reports.sources.db_estimates`); nothing issued later is shown, only the time of the next issue;
- area names: the operating area of a crew yard (`OPA-AIK-SANDHILL` <- `STG-AIK-SANDHILL-YARD`) named after
  the yard's county (`Aiken area`);
- caveat: K17 coverage of the 80 percent range on family-A synthetic storms (`etr_caveat`), never checked on a
  real storm;
- publication: the latest `publish_global_etr` proposal of DC-D4-ETR-GLOBAL with its live signatures and the
  `etr_published` audit record once executed;
- permissions: the K8 tier table's proposer list for `publish_global_etr` (draft and publish); signing stays
  on the decision card.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from sgw.api.readmodels import etr_actuals
from sgw.contracts.api_models import EtrArea, EtrPublication, EtrRevision, EtrView, Provenance
from sgw.contracts.approval import tier_rule
from sgw.contracts.vocab import ActionType, ApprovalFunction, NumberLabel, ProposalState
from sgw.models.restoration.publish import TARGET_TEXT, EtrEstimate
from sgw.reports.seed import ETR_CASE, REVISION_PREFIX
from sgw.reports.sources import db_estimates, etr_caveat

WHOLE = "Whole service area"
PPM = 1_000_000
OPEN_STATES = frozenset(
    {ProposalState.DRAFT, ProposalState.PROPOSED, ProposalState.IN_REVIEW, ProposalState.ESCALATED}
)
LIVE_STATES = OPEN_STATES | {ProposalState.APPROVED, ProposalState.EXECUTED}
RULE = tier_rule(ActionType.PUBLISH_GLOBAL_ETR)
STOPPED = frozenset({"error", "cancelled"})


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _title(word: str) -> str:
    return word[:1].upper() + word[1:].lower()


def yard_areas(conn: psycopg.Connection[Any]) -> dict[str, tuple[str, str | None]]:
    """Operating area id -> (area name after its crew yard's county, that county's name)."""
    rows = conn.execute(
        "SELECT a.asset_id, r.name FROM asset a LEFT JOIN region r ON r.region_id = a.region_id"
        " WHERE a.kind = 'staging_yard'"
    ).fetchall()
    out: dict[str, tuple[str, str | None]] = {}
    for asset_id, county in rows:
        parts = str(asset_id).split("-")
        if len(parts) >= 4 and parts[0] == "STG":
            place = county.removesuffix(" County") if county else _title(parts[2])
            out[f"OPA-{parts[1]}-{parts[2]}"] = (f"{place} area", county)
    return out


def area(e: EtrEstimate, names: dict[str, tuple[str, str | None]]) -> EtrArea:
    name, county = (WHOLE, None) if e.scope == "global" else names.get(e.region_id, (e.region_id, None))
    peak = max(e.peak_customers_out, 0)
    share = round(min(e.customers_out_now, peak) / peak * PPM) if peak else 0
    h = e.hours_from_as_of
    return EtrArea(
        estimate_id=e.estimate_id,
        scope=e.scope,
        region_id=e.region_id,
        name=name,
        county=county,
        customers_out_now=e.customers_out_now,
        peak_customers_out=e.peak_customers_out,
        still_out_ppm=share,
        p10_utc=e.p10_utc,
        p50_utc=e.p50_utc,
        p90_utc=e.p90_utc,
        p50_h=float(h.get("p50", (e.p50_utc - e.as_of_utc).total_seconds() / 3600)),
        p90_h=float(h.get("p90", (e.p90_utc - e.as_of_utc).total_seconds() / 3600)),
        range_h=round((e.p90_utc - e.p10_utc).total_seconds() / 3600, 1),
        calibrated=e.calibrated,
    )


def with_actuals(a: EtrArea, found: dict[str, etr_actuals.AreaActual], at: datetime) -> EtrArea:
    actual = found.get(etr_actuals.GLOBAL if a.scope == "global" else a.region_id)
    if actual is None:
        return a
    return a.model_copy(
        update={
            "actual_out_now": actual.out_now,
            "actual_still_out_ppm": round(min(actual.share_now, 1.0) * PPM),
            "restored_utc": actual.restored_utc,
            "outcome": etr_actuals.outcome(a.p10_utc, a.p50_utc, a.p90_utc, actual, at),
        }
    )


def revision(
    published_p50: datetime,
    whole: EtrArea,
    issued: datetime,
    found: dict[str, etr_actuals.AreaActual],
    at: datetime,
) -> EtrRevision | None:
    actual = found.get(etr_actuals.GLOBAL)
    if actual is None or whole.peak_customers_out <= 0:
        return None
    share = min(whole.customers_out_now, whole.peak_customers_out) / whole.peak_customers_out
    ahead = etr_actuals.ahead_hours(issued, share, published_p50, actual, at)
    return EtrRevision(
        due=abs(ahead) > etr_actuals.margin_h(),
        ahead_h=round(ahead, 1),
        reason=etr_actuals.revision_reason(ahead, published_p50, actual, at),
        rule=etr_actuals.RULE,
        rule_name=etr_actuals.RULE_NAME,
        published_p50_utc=published_p50,
        revised_p50_utc=etr_actuals.revised_p50(ahead, published_p50, actual),
    )


QUANTILES = ("p10", "p25", "p50", "p75", "p90")


def _rebased(e: EtrEstimate, p50: datetime, actual: etr_actuals.AreaActual, at: datetime) -> EtrEstimate:
    """One estimate re-issued at `at` on the outage feed's counts: moved by its area's actual pace (never
    earlier than the issue time), or at the restored time once the area got there."""
    peak = max(e.peak_customers_out, 0)
    share = min(e.customers_out_now, peak) / peak if peak else 0.0
    issued = at.replace(second=0, microsecond=0)
    if actual.restored_utc is not None:
        times = dict.fromkeys(QUANTILES, actual.restored_utc)
    else:
        ahead = etr_actuals.ahead_hours(_utc(e.as_of_utc), share, p50, actual, at)
        shift = etr_actuals.revised_p50(ahead, p50, actual) - e.p50_utc
        times = {q: max(getattr(e, f"{q}_utc") + shift, issued) for q in QUANTILES}
    return e.model_copy(
        update={
            "estimate_id": f"{e.estimate_id.rsplit('-', 1)[0]}-{issued:%Y%m%dT%H%MZ}",
            "as_of_utc": issued,
            "customers_out_now": actual.out_now,
            "peak_customers_out": actual.peak,
            **{f"{q}_utc": t for q, t in times.items()},
            "hours_from_as_of": {q: round((t - issued) / timedelta(hours=1), 1) for q, t in times.items()},
            "basis": f"{e.basis}; revised at the actual restoration pace ({etr_actuals.RULE})",
        }
    )


def draft_estimates(conn: psycopg.Connection[Any], as_of: datetime) -> list[EtrEstimate]:
    """What a draft proposes: the stored estimates, or, when the published ETR is due for revision under the
    ETR revision rule, every estimate moved by its area's actual pace and re-issued at the scenario time (the
    revised likely time the Restoration times tab shows)."""
    as_of = _utc(as_of)
    estimates = db_estimates(conn, as_of)
    out = published(conn)
    g = next((e for e in estimates if e.scope == "global"), None)
    if out is None or g is None:
        return estimates
    found = etr_actuals.actuals(as_of)
    whole = with_actuals(area(g, {}), found, as_of)
    revise = revision(out.p50_utc, whole, _utc(g.as_of_utc), found, as_of)
    if revise is None or not revise.due:
        return estimates
    rebased: list[EtrEstimate] = []
    for e in estimates:
        actual = found.get(etr_actuals.GLOBAL if e.scope == "global" else e.region_id)
        done = e.scope == "region" and actual is not None and actual.restored_utc is not None
        p50 = out.p50_utc if e.scope == "global" else e.p50_utc
        rebased.append(e if actual is None or done else _rebased(e, p50, actual, as_of))
    return rebased


def next_issue(conn: psycopg.Connection[Any], as_of: datetime) -> datetime | None:
    row = conn.execute(
        "SELECT min(as_of) FROM snapshot WHERE kind = 'etr' AND as_of > %s", (as_of,)
    ).fetchone()
    return _utc(row[0]) if row and row[0] is not None else None


_PUBLICATIONS = (
    "SELECT proposal_id, run_id, state::text AS state, proposed_by, params, proposal_version,"
    " required_functions::text[] AS required, created_at FROM proposal"
    " WHERE action_type = 'publish_global_etr' AND (decision_case_id = %s OR decision_case_id LIKE %s)"
)


def _rows(conn: psycopg.Connection[Any], where: str = "") -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            f"{_PUBLICATIONS}{where} ORDER BY created_at DESC, proposal_id DESC LIMIT 20",  # noqa: S608
            (ETR_CASE, f"{REVISION_PREFIX}%"),
        ).fetchall()


def publication(conn: psycopg.Connection[Any]) -> EtrPublication | None:
    """The newest live D4 proposal (the first publication or a revision), else the newest closed one."""
    rows = _rows(conn)
    if not rows:
        return None
    live = [r for r in rows if ProposalState(r["state"]) in LIVE_STATES]
    return _publication(conn, (live or rows)[0])


def published(conn: psycopg.Connection[Any]) -> EtrPublication | None:
    """The newest executed D4 proposal: the global ETR that is out."""
    rows = _rows(conn, " AND state = 'executed'")
    return _publication(conn, rows[0]) if rows else None


def _publication(conn: psycopg.Connection[Any], p: dict[str, Any]) -> EtrPublication:
    with conn.cursor(row_factory=dict_row) as cur:
        signed = cur.execute(
            "SELECT DISTINCT function::text AS function FROM approval WHERE proposal_id = %s"
            " AND proposal_version = %s AND decision = 'approve' AND voided_at IS NULL",
            (p["proposal_id"], p["proposal_version"]),
        ).fetchall()
        run = cur.execute("SELECT status FROM agent_run WHERE run_id = %s", (p["run_id"],)).fetchone()
        done = cur.execute(
            "SELECT seq, actor_id, occurred_at FROM audit_event WHERE kind = 'etr_published' AND subject = %s"
            " ORDER BY seq LIMIT 1",
            (p["proposal_id"],),
        ).fetchone()
    params = dict(p["params"] or {})
    actor = str(done["actor_id"]) if done else None
    return EtrPublication(
        proposal_id=p["proposal_id"],
        run_id=p["run_id"],
        run_status=str(run["status"]) if run else None,
        state=ProposalState(p["state"]),
        proposed_by=p["proposed_by"],
        estimate_id=str(params.get("estimate_id", "")),
        p50_utc=datetime.fromisoformat(str(params["p50_utc"]).replace("Z", "+00:00")),
        required_functions=[ApprovalFunction(f) for f in p["required"]],
        signed_functions=sorted(
            (ApprovalFunction(r["function"]) for r in signed if r["function"] in p["required"]),
            key=lambda f: f.value,
        ),
        created_at=p["created_at"],
        published_at=_utc(done["occurred_at"]) if done else None,
        published_by=actor.removeprefix("agent:") if actor else None,
        audit_seq=int(done["seq"]) if done else None,
    )


def drafting(conn: psycopg.Connection[Any], user_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM agent_run WHERE graph = 'etr' AND user_id = %s AND status = 'running' LIMIT 1",
        (user_id,),
    ).fetchone()
    return row is not None


def may_propose(user_id: str) -> bool:
    return user_id in RULE.proposer


def view(conn: psycopg.Connection[Any], as_of: datetime, user_id: str) -> EtrView:
    as_of = _utc(as_of)
    estimates = db_estimates(conn, as_of)
    names = yard_areas(conn) if estimates else {}
    found = etr_actuals.actuals(as_of) if estimates else {}
    shown = [with_actuals(area(e, names), found, as_of) for e in estimates]
    whole = next((a for a in shown if a.scope == "global"), None)
    areas = sorted((a for a in shown if a.scope == "region"), key=lambda a: (-a.p50_h, a.region_id))
    first = next((e for e in estimates if e.scope == "global"), estimates[0] if estimates else None)
    caveat = etr_caveat() if estimates else None
    pub = publication(conn)
    out = published(conn)
    proposer = may_propose(user_id)
    stalled = pub is not None and pub.state is not ProposalState.EXECUTED and pub.run_status in STOPPED
    open_pub = not stalled and pub is not None and pub.state in OPEN_STATES | {ProposalState.APPROVED}
    running = proposer and drafting(conn, user_id)
    issued = _utc(first.as_of_utc) if first else None
    same_estimate = out is not None and whole is not None and out.estimate_id == whole.estimate_id
    revise = revision(out.p50_utc, whole, issued, found, as_of) if out and whole and issued else None
    actual_as_of = found[etr_actuals.GLOBAL].as_of if etr_actuals.GLOBAL in found else None
    return EtrView(
        as_of=as_of,
        issued_at=issued,
        next_issue_utc=None if estimates else next_issue(conn, as_of),
        target=TARGET_TEXT,
        whole=whole,
        areas=areas,
        coverage80_ppm=caveat.coverage80_ppm if caveat else None,
        n_storms=caveat.n_storms if caveat else None,
        real_storm_checked=bool(caveat and caveat.real_storm_checked),
        basis=first.basis if first else None,
        model_version=first.model_version if first else None,
        drafting=running,
        publication=pub,
        can_draft=proposer
        and whole is not None
        and not open_pub
        and not running
        and (not same_estimate or bool(revise and revise.due)),
        can_publish=proposer and pub is not None and pub.state is ProposalState.APPROVED and not stalled,
        provenance=Provenance(
            source="snapshot(etr), proposal, approval, audit_event(etr_published), evals/reports/etr.json",
            model_id=first.model_version if first else None,
            rule_id="sgw.models.restoration.publish",
            as_of=issued,
            label=NumberLabel.S,
            detail=first.label if first else None,
        ),
        actual_as_of=actual_as_of,
        revision=revise,
    )


def one_area(
    conn: psycopg.Connection[Any], as_of: datetime, region_id: str
) -> tuple[EtrArea, Provenance] | None:
    estimates = db_estimates(conn, _utc(as_of))
    found = next((e for e in estimates if e.region_id == region_id), None)
    if found is None:
        return None
    source = Provenance(
        source="snapshot(etr)",
        model_id=found.model_version,
        rule_id="sgw.models.restoration.publish",
        as_of=_utc(found.as_of_utc),
        label=NumberLabel.S,
        detail=found.label,
    )
    shown = with_actuals(area(found, yard_areas(conn)), etr_actuals.actuals(_utc(as_of)), _utc(as_of))
    return shown, source
