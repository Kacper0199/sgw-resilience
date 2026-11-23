"""Clock job: compute a queue (and store it when a connection is given) inside one K12 span."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import psycopg

from sgw.common.telemetry import sgw_span
from sgw.contracts.vocab import Classification, RunMode
from sgw.models.clocks.service import CaseSpec, QueueResult, compute_queue
from sgw.models.clocks.store import save_queue


def run_clock_job(
    specs: Sequence[CaseSpec],
    *,
    run_id: str,
    run_mode: RunMode = RunMode.REPLAY,
    conn: psycopg.Connection | None = None,
    snapshot_id: str | None = None,
    now: datetime | None = None,
) -> QueueResult:
    regions = sorted({s.region_id for s in specs})
    with sgw_span(
        "clocks.compute",
        run_id=run_id,
        classification=Classification.C1,
        user_role="system",
        run_mode=run_mode,
        node="clocks",
        region_id=",".join(regions),
    ):
        result = compute_queue(specs, now=now)
        if conn is not None:
            save_queue(conn, result, snapshot_id)
    return result
