from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from sgw.ingest.testing import ScratchDb, scratch_database, server_available
from sgw.models.clocks.ps17 import CASE_CREWS, CASE_POWER, CASE_PRESSURE, ps17_specs
from sgw.models.clocks.service import compute_queue
from sgw.models.clocks.store import save_queue

INPUTS = json.loads((Path(__file__).with_name("data") / "wp06_helene_ps17_members.json").read_text("utf-8"))


@pytest.fixture
def scratch_db() -> Iterator[ScratchDb]:
    reason = server_available()
    if reason:
        pytest.skip(reason)  # sgw-allow-skip: database tests need the local Postgres stack (port 5434)
    with scratch_database("wp12") as db:
        yield db


def test_save_queue_round_trips_and_replaces(scratch_db: ScratchDb) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        n = compute_queue(ps17_specs(INPUTS["advisories"]["N"], INPUTS))
        n1 = compute_queue(ps17_specs(INPUTS["advisories"]["N+1"], INPUTS))
        assert save_queue(conn, n).saved == 5
        assert save_queue(conn, n1).saved == 5
        row = conn.execute(
            "SELECT decide_by_utc, effective_decide_by_utc, no_regret_verdict, no_regret_share_ppm,"
            " on_critical_path FROM decision_case WHERE decision_case_id = %s",
            (CASE_POWER,),
        ).fetchone()
        case = n1.cases[CASE_POWER].case
        assert row == (
            case.clock.decide_by_utc,
            case.effective_decide_by_utc,
            "act_now",
            case.no_regret_share_ppm,
            True,
        )
        deps = conn.execute(
            "SELECT prerequisite_id FROM decision_dependency WHERE decision_case_id = %s ORDER BY 1",
            (CASE_POWER,),
        ).fetchall()
        assert [d[0] for d in deps] == sorted(["DC-D3-PS17-FUEL", CASE_CREWS])
        terms = conn.execute(
            "SELECT ord, basis->>'basis_id', p50, term_kind FROM clock_waterfall_term"
            " WHERE decision_case_id = %s ORDER BY ord",
            (CASE_POWER,),
        ).fetchall()
        expected = [
            (r.basis.basis_id if r.basis else None, r.term_kind.value)
            for r in n1.cases[CASE_POWER].waterfall_rows()
        ]
        assert [(t[1], t[3]) for t in terms] == expected
        assert terms[-1][2] == -30.0
        state = conn.execute(
            "SELECT effective_decide_by_p10_utc, effective_decide_by_p90_utc, verdict_basis_utc,"
            " bound_by_case_id FROM clock_case_state WHERE decision_case_id = %s",
            (CASE_POWER,),
        ).fetchone()
        path = n1.cases[CASE_POWER].path
        assert state == (
            path.effective["p10"],
            path.effective["p90"],
            n1.cases[CASE_POWER].verdict_basis_utc,
            CASE_PRESSURE,
        )
        count = conn.execute("SELECT count(*) FROM clock_waterfall_term").fetchone()
        assert count is not None and count[0] == sum(len(c.waterfall_rows()) for c in n1.cases.values())
        bound = conn.execute(
            "SELECT count(*) FROM decision_dependency WHERE prerequisite_id = %s", (CASE_POWER,)
        ).fetchone()
        assert bound is not None and bound[0] == 1
        assert CASE_PRESSURE in n1.cases


def test_save_queue_removes_cases_that_lost_their_clock(scratch_db: ScratchDb) -> None:
    adv = INPUTS["advisories"]["N"]
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        save_queue(conn, compute_queue(ps17_specs(adv, INPUTS)))
        blind = {**adv, "members": [{**m, "crew_ts_onset_utc": None} for m in adv["members"]]}
        result = compute_queue(ps17_specs(blind, INPUTS))
        assert CASE_CREWS in result.cases and result.cases[CASE_CREWS].path.derived
        hospital_blind = {
            **adv,
            "members": [{**m, "exposure_utc": None, "crew_ts_onset_utc": None} for m in adv["members"]],
        }
        gone = compute_queue(ps17_specs(hospital_blind, INPUTS))
        assert set(gone.no_clock) == {
            CASE_CREWS,
            "DC-D3-PS17-FUEL",
            CASE_POWER,
            CASE_PRESSURE,
            "DC-D3-HSP-TALLOWBRANCH-WATER",
        }
        saved = save_queue(conn, gone)
        assert saved.saved == 0 and len(saved.removed) == 5 and saved.kept_referenced == ()
        row = conn.execute(
            "SELECT (SELECT count(*) FROM decision_case) + (SELECT count(*) FROM decision_dependency)"
            " + (SELECT count(*) FROM clock_waterfall_term) + (SELECT count(*) FROM clock_case_state)"
        ).fetchone()
        assert row is not None and row[0] == 0
