"""Persist a computed queue: K1 `decision_case` and `decision_dependency` rows plus the waterfall terms
(migration 2300). One transaction per queue; dependencies and terms are replaced as a set per case."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from sgw.contracts.clocks import ClockBasis
from sgw.models.clocks.service import SERVICE_ID, SERVICE_VERSION, ComputedCase, QueueResult

_UPSERT_CASE = """
INSERT INTO decision_case (
    decision_case_id, step, title, region_id, domain, clock_kind,
    consequence_utc, consequence_p10_utc, consequence_p90_utc, consequence_basis,
    action_lead_time_min, lead_time_basis, decide_by_utc, decide_by_p10_utc, decide_by_p90_utc,
    effective_decide_by_utc, on_critical_path, no_regret_share_ppm, no_regret_verdict, next_advisory_utc,
    if_late, snapshot_id, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
ON CONFLICT (decision_case_id) DO UPDATE SET
    step = EXCLUDED.step, title = EXCLUDED.title, region_id = EXCLUDED.region_id, domain = EXCLUDED.domain,
    clock_kind = EXCLUDED.clock_kind, consequence_utc = EXCLUDED.consequence_utc,
    consequence_p10_utc = EXCLUDED.consequence_p10_utc, consequence_p90_utc = EXCLUDED.consequence_p90_utc,
    consequence_basis = EXCLUDED.consequence_basis, action_lead_time_min = EXCLUDED.action_lead_time_min,
    lead_time_basis = EXCLUDED.lead_time_basis, decide_by_utc = EXCLUDED.decide_by_utc,
    decide_by_p10_utc = EXCLUDED.decide_by_p10_utc, decide_by_p90_utc = EXCLUDED.decide_by_p90_utc,
    effective_decide_by_utc = EXCLUDED.effective_decide_by_utc, on_critical_path = EXCLUDED.on_critical_path,
    no_regret_share_ppm = EXCLUDED.no_regret_share_ppm, no_regret_verdict = EXCLUDED.no_regret_verdict,
    next_advisory_utc = EXCLUDED.next_advisory_utc, if_late = EXCLUDED.if_late,
    snapshot_id = EXCLUDED.snapshot_id, updated_at = now()
"""


def _basis(b: ClockBasis | None) -> Jsonb | None:
    return None if b is None else Jsonb(b.model_dump(mode="json"))


def _case_row(c: ComputedCase, snapshot_id: str | None) -> tuple[object, ...]:
    d, k = c.case, c.case.clock
    return (
        d.decision_case_id,
        d.step.value,
        d.title,
        d.region_id,
        d.domain.value,
        k.clock_kind.value,
        k.consequence_utc,
        k.consequence_p10_utc,
        k.consequence_p90_utc,
        _basis(k.consequence_basis),
        k.action_lead_time_min,
        _basis(k.lead_time_basis),
        k.decide_by_utc,
        k.decide_by_p10_utc,
        k.decide_by_p90_utc,
        d.effective_decide_by_utc,
        d.on_critical_path,
        d.no_regret_share_ppm,
        d.no_regret_verdict.value,
        d.next_advisory_utc,
        k.if_late,
        snapshot_id,
    )


def _ordered(cases: Iterable[ComputedCase]) -> list[ComputedCase]:
    return sorted(cases, key=lambda c: c.case.decision_case_id)


@dataclass(frozen=True)
class SaveResult:
    saved: int
    removed: tuple[str, ...]
    kept_referenced: tuple[str, ...]


def save_queue(conn: psycopg.Connection, result: QueueResult, snapshot_id: str | None = None) -> SaveResult:
    """Upsert clocked cases with dependencies, waterfall terms and clock state. Cases that fell into
    `no_clock` lose their dependencies, terms and state; their `decision_case` row is deleted unless a
    proposal or commitment references it (then it is reported in `kept_referenced`)."""
    computed_by = f"{SERVICE_ID}@{SERVICE_VERSION}"
    cases = _ordered(result.cases.values())
    ids = [c.case.decision_case_id for c in cases]
    gone = sorted(result.no_clock)
    removed: list[str] = []
    kept: list[str] = []
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(_UPSERT_CASE, [_case_row(c, snapshot_id) for c in cases])
        cur.execute(
            "DELETE FROM decision_dependency WHERE decision_case_id = ANY(%s) OR prerequisite_id = ANY(%s)",
            (ids + gone, gone),
        )
        cur.executemany(
            "INSERT INTO decision_dependency (decision_case_id, prerequisite_id, reason) VALUES (%s, %s, %s)",
            [
                (
                    c.case.decision_case_id,
                    pre,
                    f"{pre} must finish its action before {c.case.decision_case_id} is decided",
                )
                for c in cases
                for pre in sorted(c.case.prerequisite_ids)
            ],
        )
        cur.execute("DELETE FROM clock_waterfall_term WHERE decision_case_id = ANY(%s)", (ids + gone,))
        cur.execute("DELETE FROM clock_case_state WHERE decision_case_id = ANY(%s)", (ids + gone,))
        cur.executemany(
            "INSERT INTO clock_waterfall_term (decision_case_id, ord, label, term_kind, basis, unit,"
            " p10, p50, p90, context_p10, context_p90, computed_by)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    c.case.decision_case_id,
                    i,
                    r.label,
                    r.term_kind.value,
                    _basis(r.basis),
                    r.unit,
                    r.p10,
                    r.p50,
                    r.p90,
                    r.context_p10,
                    r.context_p90,
                    computed_by,
                )
                for c in cases
                for i, r in enumerate(c.waterfall_rows())
            ],
        )
        cur.executemany(
            "INSERT INTO clock_case_state (decision_case_id, effective_decide_by_p10_utc,"
            " effective_decide_by_p90_utc, verdict_basis_utc, bound_by_case_id, slack_min, derived, missed,"
            " computed_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    c.case.decision_case_id,
                    c.path.effective["p10"],
                    c.path.effective["p90"],
                    c.verdict_basis_utc,
                    c.path.bound_by_case_id,
                    c.path.slack_min,
                    c.path.derived,
                    c.missed,
                    computed_by,
                )
                for c in cases
            ],
        )
        for cid in gone:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM proposal WHERE decision_case_id = %s)"
                " OR EXISTS (SELECT 1 FROM commitment WHERE decision_case_id = %s)",
                (cid, cid),
            )
            row = cur.fetchone()
            if row is not None and row[0]:
                kept.append(cid)
                continue
            cur.execute("DELETE FROM decision_case WHERE decision_case_id = %s RETURNING 1", (cid,))
            if cur.fetchone() is not None:
                removed.append(cid)
    return SaveResult(saved=len(cases), removed=tuple(removed), kept_referenced=tuple(kept))
