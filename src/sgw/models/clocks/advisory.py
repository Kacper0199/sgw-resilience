"""The decision queue follows the scenario clock: the advisory in force (the latest one issued at or
before the scenario time) is recomputed and stored whenever its cases differ from the stored ones (D1),
and every open proposal whose case clock moved is revised through the approval service with its new
decide-by basis, so the change is material, the version rises and the existing signatures are voided by
the version rule (D2, SC-3). The member table is the water twin's, the same one the runs use."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import psycopg

from sgw.approval.errors import ApprovalError
from sgw.models.clocks.job import run_clock_job
from sgw.models.clocks.ps17 import ps17_specs
from sgw.models.clocks.service import QueueResult

REPO_ROOT = Path(__file__).resolve().parents[4]
TABLE_ENV = "SGW_PS17_MEMBER_TABLE"
TWIN_TABLE = REPO_ROOT / "data" / "artefacts" / "water_twin" / "ps17_clock_members.json"
ACTOR = "system:clock-replanner"
OPEN_STATES = ("proposed", "in_review")
LOCK_KEY = 2300_0001


class Reviser(Protocol):
    def __call__(
        self, conn: psycopg.Connection[Any], *, proposal_id: str, params: dict[str, Any], reason: str
    ) -> int: ...


@dataclass
class QueueSync:
    advisory: str | None
    stored: bool = False
    moved: dict[str, tuple[str | None, str]] = field(default_factory=dict)
    revised: dict[str, int] = field(default_factory=dict)
    refused: dict[str, str] = field(default_factory=dict)


def member_table(path: Path | None = None) -> dict[str, Any]:
    source = path or Path(os.environ.get(TABLE_ENV, str(TWIN_TABLE)))
    data: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
    return data


def _issued(adv: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(adv["issued_utc"]).replace("Z", "+00:00"))


def advisory_in_force(table: dict[str, Any], now: datetime) -> str | None:
    issued = [(_issued(a), label) for label, a in table["advisories"].items() if _issued(a) <= now]
    return max(issued)[1] if issued else None


def compute(table: dict[str, Any], advisory: str, conn: psycopg.Connection[Any] | None = None) -> QueueResult:
    adv = table["advisories"][advisory]
    return run_clock_job(ps17_specs(adv, table), run_id=f"clocks-{advisory}", conn=conn, now=_issued(adv))


def _key(effective: datetime, verdict: str) -> str:
    return f"{effective.isoformat()}|{verdict}"


def _stored(conn: psycopg.Connection[Any], ids: list[str]) -> dict[str, str]:
    rows = conn.execute(
        "SELECT decision_case_id, effective_decide_by_utc, no_regret_verdict FROM decision_case"
        " WHERE decision_case_id = ANY(%s)",
        (ids,),
    ).fetchall()
    return {r[0]: _key(r[1], str(r[2])) for r in rows}


def basis_of(advisory: str, result: QueueResult, case_id: str) -> dict[str, Any]:
    c = result.cases[case_id].case
    return {
        "decide_by_advisory": advisory,
        "decide_by_effective_utc": c.effective_decide_by_utc.isoformat().replace("+00:00", "Z"),
        "decide_by_verdict": c.no_regret_verdict.value,
    }


def sync_queue(
    conn: psycopg.Connection[Any],
    now: datetime,
    *,
    revise: Reviser | None = None,
    table: dict[str, Any] | None = None,
) -> QueueSync:
    """Store the queue of the advisory in force when it differs from the stored one and revise the open
    proposals of the cases that moved. Idempotent; serialised by an advisory lock. `conn` is autocommit."""
    table = table or member_table()
    advisory = advisory_in_force(table, now)
    sync = QueueSync(advisory)
    if advisory is None:
        return sync
    conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
    try:
        fresh = compute(table, advisory)
        wanted = {
            cid: _key(c.case.effective_decide_by_utc, c.case.no_regret_verdict.value)
            for cid, c in fresh.cases.items()
        }
        before = _stored(conn, list(wanted))
        if before == wanted:
            return sync
        result = compute(table, advisory, conn)
        sync.stored = True
        sync.moved = {
            cid: (before[cid], key) for cid, key in wanted.items() if cid in before and before[cid] != key
        }
        if revise is not None:
            _revise_open(conn, advisory, result, sync, revise)
        return sync
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))


def _revise_open(
    conn: psycopg.Connection[Any], advisory: str, result: QueueResult, sync: QueueSync, revise: Reviser
) -> None:
    rows = conn.execute(
        "SELECT proposal_id, decision_case_id, params FROM proposal"
        " WHERE decision_case_id = ANY(%s) AND state = ANY(%s) ORDER BY proposal_id",
        (list(sync.moved), list(OPEN_STATES)),
    ).fetchall()
    for proposal_id, case_id, params in rows:
        old, _ = sync.moved[case_id]
        basis = basis_of(advisory, result, case_id)
        reason = (
            f"advisory {advisory} moved {case_id}: effective decide-by {old.split('|')[0] if old else '-'}"
            f" -> {basis['decide_by_effective_utc']} ({basis['decide_by_verdict']}); signatures voided"
        )
        try:
            sync.revised[proposal_id] = revise(
                conn, proposal_id=proposal_id, params={**dict(params), **basis}, reason=reason
            )
        except (ApprovalError, psycopg.Error) as error:
            sync.refused[proposal_id] = f"{type(error).__name__}: {error}"
