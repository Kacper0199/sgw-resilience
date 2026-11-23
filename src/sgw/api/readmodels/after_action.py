"""After-action read model: the WP-25 review at the scenario time as one K3 document.

- review: `sgw.reports.after_action.review` (the audit chain is verified first; only records up to the last
  trusted sequence are used), with the decision-case title and the co-sign reason code added to each
  break-glass use;
- ETR scorecard: the latest WP-17 ETR publication in the database issued by the scenario time, scored by
  `sgw.reports.scorecard`; without one, the committed story scorecard when its estimates were issued by then;
  otherwise empty;
- SC 103-314 draft: `sgw.reports.sc_103_314` over the SC section outages that ended by the scenario time
  (nothing that ends later is shown), rendered as the Markdown draft; never filed.
- tamper demo: one record of an in-memory copy of the chain is altered and the copy is verified with the
  same row checks as `audit.verify`; the real chain is only read.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from sgw.approval import audit
from sgw.approval.signer import Keyring
from sgw.contracts.api_models import (
    AfterActionView,
    AuditChainCheck,
    AuditTimelineEntry,
    BreakGlassUseRow,
    ClockOutcomeRow,
    EtrScorecard,
    EtrScoreRow,
    Provenance,
    RegulatorReportDraft,
    TamperDemoResult,
)
from sgw.contracts.vocab import NumberLabel
from sgw.reports import after_action as aa
from sgw.reports import sc_103_314 as sc
from sgw.reports import scorecard as score
from sgw.reports.sources import OUTAGES, REPO_ROOT, db_estimates
from sgw.reports.sources import county_codes as network_county_codes

STORY_SCORECARD = REPO_ROOT / "data" / "artefacts" / "evals" / "etr_story_scorecard.json"
DEFAULT_TAMPER_KINDS = ("approval_recorded", "execution_token_issued", "break_glass_used")
TAMPER_NOTE = "payload.tampered_by_demo = true (one field added in the in-memory copy)"


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _break_glass_extras(conn: psycopg.Connection[Any]) -> dict[int, tuple[str | None, str | None]]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT b.break_glass_id, d.title,"
            " (SELECT a.reason_code FROM approval a WHERE a.proposal_id = b.proposal_id"
            "   AND a.approver_id = b.cosigned_by AND a.reason_code IS NOT NULL"
            "   ORDER BY a.created_at DESC LIMIT 1) AS reason_code"
            " FROM break_glass b JOIN proposal p ON p.proposal_id = b.proposal_id"
            " JOIN decision_case d ON d.decision_case_id = p.decision_case_id"
        ).fetchall()
    return {int(r["break_glass_id"]): (r["title"], r["reason_code"]) for r in rows}


UNRESOLVED = {
    "actual_utc": None,
    "p50_error_h": None,
    "abs_error_h": None,
    "analog_abs_error_h": None,
    "in_p25_p75": None,
    "in_p10_p90": None,
}


def known_scores(scores: list[score.EstimateScore], as_of: datetime) -> list[score.EstimateScore]:
    """Never an actual after the scenario clock: an estimate whose actual is still ahead is unresolved."""
    return [
        s if s.actual_utc is not None and s.actual_utc <= as_of else s.model_copy(update=UNRESOLVED)
        for s in scores
    ]


def _card(
    name: str,
    actual_label: str,
    source: str,
    issued: datetime | None,
    scores: list[score.EstimateScore],
    as_of: datetime,
) -> EtrScorecard:
    shown = known_scores(scores, as_of)
    resolved = [s for s in shown if s.actual_utc is not None]
    return EtrScorecard(
        name=name,
        label=NumberLabel.S,
        actual_label=actual_label,
        source=source,
        as_of=issued,
        resolved=len(resolved),
        total=len(shown),
        resolved_label=f"{len(resolved)} of {len(shown)} resolved",
        metrics=score.metric_rows(resolved),
        estimates=[EtrScoreRow.model_validate(s.model_dump()) for s in shown],
    )


def _scorecard(conn: psycopg.Connection[Any], as_of: datetime, story: Path) -> EtrScorecard:
    found = db_estimates(conn, as_of)
    if found:
        scores = score.score_publication(found)
        issued = max(e.as_of_utc for e in found)
        return _card("etr_story_scorecard", score.ACTUAL_LABEL, "snapshot", issued, scores, as_of)
    if story.is_file():
        data = json.loads(story.read_text(encoding="utf-8"))
        scores = [score.EstimateScore.model_validate(e) for e in data["estimates"]]
        issued_at = max((s.as_of_utc for s in scores), default=None)
        if issued_at is not None and issued_at <= as_of:
            source = str(story.relative_to(REPO_ROOT))
            return _card(str(data["name"]), str(data["actual_label"]), source, issued_at, scores, as_of)
    return _card("etr_story_scorecard", score.ACTUAL_LABEL, "none", None, [], as_of)


def regulator_draft(
    as_of: datetime, outages: Path = OUTAGES, banner: str | None = None
) -> RegulatorReportDraft | None:
    """The SC 103-314 draft over the SC section outages restored by `as_of`."""
    by_county: dict[str, list[dict[str, str]]] = defaultdict(list)
    with outages.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            back = r["customers_back_utc"]
            if r["fips"].startswith(sc.SC_FIPS_PREFIX) and back and sc._t(back) <= as_of:
                by_county[r["fips"]].append(r)
    if not by_county:
        return None
    codes = network_county_codes()
    event = "Hurricane Helene"
    counties = [
        sc._record(f"SC-{f}", "county", codes.get(f), rows, event) for f, rows in sorted(by_county.items())
    ]
    every = [r for rows in by_county.values() for r in rows]
    report = sc.InterruptionReport(
        citation=sc.CITATION,
        source_note=sc.SOURCE_NOTE,
        label=sc.SYNTHETIC_LABEL,
        threshold_h=sc.REPORT_THRESHOLD_H,
        event_name=event,
        system=sc._record(sc.SYSTEM_ID, "system", None, every, event),
        counties=sorted(counties, key=lambda r: (-r.customers_interrupted, r.area_id)),
    )
    body = report.model_dump(mode="json")
    return RegulatorReportDraft.model_validate(
        {**body, "filed": False, "markdown": sc.render_markdown(report, banner)}
    )


still_open = aa.still_open


def page_clocks(clocks: list[aa.ClockResult], open_cases: frozenset[str]) -> list[ClockOutcomeRow]:
    """The deadlines as Decisions and Ask count them (`aa.counted_clocks`)."""
    return [ClockOutcomeRow.model_validate(c.model_dump()) for c in aa.counted_clocks(clocks, open_cases)]


def view(
    conn: psycopg.Connection[Any],
    as_of: datetime,
    keyring: Keyring,
    anchors: audit.AnchorStore,
    story: Path = STORY_SCORECARD,
    outages: Path = OUTAGES,
) -> AfterActionView:
    as_of = _utc(as_of)
    review = aa.review(conn, as_of, keyring=keyring, anchors=anchors)
    extras = _break_glass_extras(conn)
    from sgw.reports.nodes import chain_banner

    banner = None if review.usable else chain_banner(review)
    return AfterActionView(
        as_of=as_of,
        usable=review.usable,
        chain=AuditChainCheck.model_validate(review.chain.model_dump()),
        clocks=page_clocks(review.clocks, still_open(conn)),
        break_glass=[
            BreakGlassUseRow.model_validate(
                {
                    **b.model_dump(),
                    "title": extras.get(b.break_glass_id, (None, None))[0],
                    "reason_code": extras.get(b.break_glass_id, (None, None))[1],
                }
            )
            for b in review.break_glass
        ],
        timeline=[AuditTimelineEntry.model_validate(t.model_dump()) for t in review.timeline],
        scorecard=_scorecard(conn, as_of, story),
        sc_report=regulator_draft(as_of, outages, banner),
        provenance=Provenance(
            source="audit_event (verified chain), break_glass, decision_case, snapshot(etr), outages.csv",
            rule_id="sgw.reports.after_action.review",
            as_of=as_of,
            label=NumberLabel.S,
        ),
    )


def _rows(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in audit.chain_rows(conn)]


def default_tamper_seq(rows: list[dict[str, Any]]) -> int | None:
    if not rows:
        return None
    for kind in DEFAULT_TAMPER_KINDS:
        hits = [int(r["seq"]) for r in rows if r["kind"] == kind]
        if hits:
            return hits[-1]
    return int(rows[(len(rows) - 1) // 2]["seq"])


def tampered_copy(rows: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    return [
        {**r, "payload": {**dict(r["payload"] or {}), "tampered_by_demo": True}}
        if int(r["seq"]) == target
        else r
        for r in rows
    ]


def tamper_demo(
    conn: psycopg.Connection[Any], seq: int | None, keyring: Keyring, anchors: audit.AnchorStore
) -> TamperDemoResult | None:
    """None when the chain is empty or `seq` is not in it. The verifier is `audit.verify_rows`, the same
    checks as `audit.verify` (truncation included), over the altered in-memory copy."""
    rows = _rows(conn)
    target = seq if seq is not None else default_tamper_seq(rows)
    if target is None or not any(int(r["seq"]) == target for r in rows):
        return None
    problems: list[str] = []
    heads, segments = audit.trusted_heads(conn, keyring, anchors, problems=problems)
    report = audit.verify_rows(tampered_copy(rows, target), heads, segments, problems)
    return TamperDemoResult(
        tampered_seq=target,
        altered=TAMPER_NOTE,
        result=report.result(),
        untrusted_from_seq=report.first_bad_seq,
        problems=report.problems[:20],
    )
