from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from sgw.approval import audit, testkit
from sgw.approval.ledger import MemorySink
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.contracts import golden
from sgw.contracts.api_models import ApprovalRequest
from sgw.contracts.events import CommitmentCreated, CommitmentDrifted
from sgw.models.clocks import lead_times
from sgw.models.commitments import learning, seed
from sgw.models.commitments.service import ACTOR, CommitmentWatch, OutboxSink, commitment_id_for, replay

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
HELENE_EAM = Path(__file__).resolve().parents[4] / "data" / "fixtures" / "helene" / "eam.jsonl"
CID = commitment_id_for(golden.PROPOSAL_PS17, 1)


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if testkit.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with testkit.seeded_database() as url:
        yield url


@pytest.fixture
def conn(db_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(db_url, autocommit=True) as c:
        yield c


@pytest.fixture(scope="module")
def drifted(db_url: str) -> dict[str, Any]:
    """Seed PS-17 through the approval service, then replay helene_micro through the watch (outbox sink)."""
    clock = testkit.MutableClock(golden.ADVISORY_N1.issued)
    approvals = ApprovalService(
        ReferencePolicy(), scenario_clock=clock, token_clock=clock, ledger=OutboxSink()
    )

    def set_time(at: Any) -> None:
        clock.at = at

    with psycopg.connect(db_url, autocommit=True) as c:
        seeded = seed.seed_ps17_approved(c, approvals, set_time)
        state = c.execute(
            "SELECT state FROM proposal WHERE proposal_id = %s", (seeded.proposal_id,)
        ).fetchone()
        watcher = CommitmentWatch(approvals, ledger=OutboxSink())
        events = [e for e in seed.micro_events() if e["event_time"] >= seeded.approved_at.isoformat()[:19]]
        result = replay(c, watcher, events, set_time=set_time)
    return {"seeded": seeded, "state_before": state[0] if state else None, "result": result}


def test_seeded_ps17_is_approved_through_the_service(drifted: dict[str, Any]) -> None:
    assert drifted["state_before"] == "approved"
    assert CID in drifted["result"].created


def test_ps17_commitment_drifts_in_the_replay_and_reopens_the_decision(
    drifted: dict[str, Any], conn: psycopg.Connection[Any]
) -> None:
    result = drifted["result"]
    assert golden.PROPOSAL_PS17 in result.reopened
    with conn.cursor(row_factory=dict_row) as cur:
        cmt = cur.execute("SELECT * FROM commitment WHERE commitment_id = %s", (CID,)).fetchone()
        drifts = cur.execute(
            "SELECT * FROM commitment_drift WHERE commitment_id = %s ORDER BY seq", (CID,)
        ).fetchall()
        prop = cur.execute(
            "SELECT state, proposal_version, preconditions FROM proposal WHERE proposal_id = %s",
            (golden.PROPOSAL_PS17,),
        ).fetchone()
        voided = cur.execute(
            "SELECT count(*) AS n FROM approval WHERE proposal_id = %s AND voided_at IS NOT NULL",
            (golden.PROPOSAL_PS17,),
        ).fetchone()
        ms = cur.execute(
            "SELECT seq, due_utc, met_utc FROM commitment_milestone WHERE commitment_id = %s ORDER BY seq",
            (CID,),
        ).fetchall()
    assert cmt is not None and cmt["state"] == "drifted"
    assert cmt["promised_by_utc"] == golden.ps17_clock(golden.ADVISORY_N1).consequence_utc
    final = drifts[-1]
    assert final["state"] == "drifted" and final["reason"] == "milestone_late" and final["reopened"]
    assert final["milestone_seq"] == 1
    assert final["drift_min"] > final["tolerance_min"]
    first_due = ms[0]["due_utc"]
    assert first_due < final["detected_at"] <= first_due + timedelta(minutes=2 * final["tolerance_min"])
    assert all(m["met_utc"] is None for m in ms)
    assert prop is not None and prop["state"] == "proposed" and prop["proposal_version"] == 2
    assert prop["preconditions"]["commitment_on_track"] is False
    assert voided is not None and voided["n"] == 2
    assert final["proposal_version"] == 2


def test_commitment_events_go_through_the_outbox_into_the_ledger(
    drifted: dict[str, Any], conn: psycopg.Connection[Any]
) -> None:
    rows = conn.execute(
        "SELECT type, payload, ledger_seq FROM event WHERE type IN ('CommitmentCreated', 'CommitmentDrifted')"
        " AND payload->>'commitment_id' = %s ORDER BY ledger_seq",
        (CID,),
    ).fetchall()
    types = [r[0] for r in rows]
    assert types[0] == "CommitmentCreated"
    assert "CommitmentDrifted" in types
    created = CommitmentCreated.model_validate(rows[0][1])
    assert created.proposal_id == golden.PROPOSAL_PS17 and len(created.milestones) == 3
    last = CommitmentDrifted.model_validate(rows[-1][1])
    assert last.state.value == "drifted" and last.drift_min > 0
    queued = conn.execute(
        "SELECT count(*) FROM job WHERE kind = 'ledger.append' AND payload->>'origin' = 'commitments'"
    ).fetchone()
    assert queued is not None and queued[0] >= 2
    ledger = conn.execute("SELECT type FROM event WHERE type = 'ProposalUpdated'").fetchall()
    assert ledger


def test_audit_rows_for_creation_drift_and_reopen(
    drifted: dict[str, Any], conn: psycopg.Connection[Any]
) -> None:
    kinds = {
        r[0]
        for r in conn.execute(
            "SELECT kind FROM audit_event WHERE subject IN (%s, %s)", (CID, golden.PROPOSAL_PS17)
        ).fetchall()
    }
    assert {"commitment_created", "commitment_drifted", "proposal_revised"} <= kinds
    actor = conn.execute(
        "SELECT actor_id FROM audit_event WHERE kind = 'proposal_revised' AND subject = %s",
        (golden.PROPOSAL_PS17,),
    ).fetchone()
    assert actor is not None and actor[0] == ACTOR
    assert audit.verify(conn).ok


def test_replay_is_idempotent_for_creation(drifted: dict[str, Any], conn: psycopg.Connection[Any]) -> None:
    watcher = CommitmentWatch(None, ledger=MemorySink())
    again = watcher.on_decision_approved(
        conn, proposal_id=golden.PROPOSAL_PS17, proposal_version=1, at=drifted["seeded"].approved_at
    )
    assert again is None
    n = conn.execute(
        "SELECT count(*) FROM commitment WHERE proposal_id = %s", (golden.PROPOSAL_PS17,)
    ).fetchone()
    assert n is not None and n[0] == 1


def test_unapproved_version_creates_no_commitment(
    drifted: dict[str, Any], conn: psycopg.Connection[Any]
) -> None:
    watcher = CommitmentWatch(None, ledger=MemorySink())
    assert (
        watcher.on_decision_approved(
            conn, proposal_id=golden.PROPOSAL_PS17, proposal_version=2, at=drifted["seeded"].approved_at
        )
        is None
    )


def test_material_input_change_drifts_and_logs(db_url: str) -> None:
    """A decide-by moving earlier than the promise can absorb drifts the commitment (input_changed)."""
    with testkit.seeded_database() as url, psycopg.connect(url, autocommit=True) as c:
        clock = testkit.MutableClock(golden.ADVISORY_N1.issued)
        sink = MemorySink()
        approvals = ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=clock, ledger=sink)

        def set_time(at: Any) -> None:
            clock.at = at

        seeded = seed.seed_ps17_approved(c, approvals, set_time)
        watcher = CommitmentWatch(approvals, ledger=sink)
        at = seeded.approved_at + timedelta(minutes=1)
        cid = watcher.on_decision_approved(c, proposal_id=seeded.proposal_id, proposal_version=1, at=at)
        assert cid == CID
        case = golden.ps17_clock(golden.ADVISORY_N1)
        moved = case.decide_by_utc - timedelta(minutes=60)
        result = watcher.on_event(
            c,
            {
                "type": "DecisionClockUpdated",
                "event_time": (at + timedelta(minutes=5)).isoformat(),
                "payload": {"decision_case_id": golden.CASE_PS17, "decide_by_utc": moved.isoformat()},
            },
        )
        assert result.drifted and result.drifted[0]["reason"] == "input_changed"
        assert result.drifted[0]["drift_min"] == 60
        assert result.reopened == [golden.PROPOSAL_PS17]
        types = [e.type for e in sink.queued]
        assert "CommitmentCreated" in types and "CommitmentDrifted" in types


def test_learning_loop_writes_a_t2_proposal_and_never_applies(conn: psycopg.Connection[Any]) -> None:
    before = hashlib.sha256(lead_times.LEAD_TIMES_PATH.read_bytes()).hexdigest()
    registry_before = {k: v.minutes for k, v in lead_times.load().items()}
    events = [json.loads(line) for line in HELENE_EAM.read_text(encoding="utf-8").splitlines()]
    rows = learning.evidence(
        learning.observe(e for e in events if "payload" in e), "fixture:helene/eam.jsonl"
    )
    at = golden.t(29, 12)
    change_id = learning.write_proposal(conn, rows, incident_id="INC-HELENE-2024", at=at)
    assert change_id is not None
    assert learning.write_proposal(conn, rows, incident_id="INC-HELENE-2024", at=at) == change_id
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            "SELECT *, required_functions::text[] AS functions FROM policy_change_proposal"
            " WHERE change_id = %s",
            (change_id,),
        ).fetchone()
        aud = cur.execute(
            "SELECT payload FROM audit_event WHERE kind = 'policy_change_proposed' AND subject = %s",
            (change_id,),
        ).fetchall()
    assert row is not None
    assert row["tier"] == "T2" and row["state"] == "proposed" and row["proposed_by"] == learning.ACTOR
    assert row["functions"] == ["compliance"]
    evidence = {e["key"]: e for e in row["evidence"]}
    fuel = evidence["fuel_truck_dispatch"]
    assert fuel["n"] == 1 and fuel["source"] == "fixture:helene/eam.jsonl"
    assert fuel["assumed_min"] == registry_before["fuel_truck_dispatch"]
    assert fuel["observations"][0]["work_order_id"] == "WO-SYN-FUEL-01"
    assert set(row["proposed_values"]) == {"fuel_truck_dispatch"}
    assert row["current_values"]["fuel_truck_dispatch"] == registry_before["fuel_truck_dispatch"]
    assert len(aud) == 1 and aud[0]["payload"]["applied"] is False
    assert hashlib.sha256(lead_times.LEAD_TIMES_PATH.read_bytes()).hexdigest() == before
    assert {k: v.minutes for k, v in lead_times.load().items()} == registry_before
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE policy_change_proposal SET state = 'applied' WHERE change_id = %s", (change_id,))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE policy_change_proposal SET tier = 'T1' WHERE change_id = %s", (change_id,))


def test_policy_change_goes_through_the_approval_service_as_t2_compliance(
    drifted: dict[str, Any], conn: psycopg.Connection[Any]
) -> None:
    events = [json.loads(line) for line in HELENE_EAM.read_text(encoding="utf-8").splitlines()]
    rows = learning.evidence(
        learning.observe(e for e in events if "payload" in e), "fixture:helene/eam.jsonl"
    )
    at = golden.t(29, 12)
    change_id = learning.write_proposal(conn, rows, incident_id="INC-HELENE-2024", at=at)
    assert change_id is not None
    clock = testkit.MutableClock(at)
    approvals = ApprovalService(
        ReferencePolicy(), scenario_clock=clock, token_clock=clock, ledger=OutboxSink()
    )
    assert drifted["seeded"].proposal_id
    case_id = golden.CASE_PS17
    pid = learning.route_for_approval(conn, approvals, change_id, decision_case_id=case_id)
    assert learning.route_for_approval(conn, approvals, change_id, decision_case_id=case_id) == pid
    with conn.cursor(row_factory=dict_row) as cur:
        proposal = cur.execute(
            "SELECT action_type, tier, state, proposed_by, initiator_kind, params,"
            " required_functions::text[] AS functions FROM proposal WHERE proposal_id = %s",
            (pid,),
        ).fetchone()
        link = cur.execute(
            "SELECT approval_proposal_id FROM policy_change_proposal WHERE change_id = %s", (change_id,)
        ).fetchone()
    assert proposal is not None and link is not None
    assert (proposal["action_type"], proposal["proposed_by"]) == ("policy_change", learning.ACTOR)
    assert proposal["initiator_kind"] == "system_rule"
    assert proposal["tier"] in ("T2", "T3") and proposal["state"] == "proposed"
    assert "compliance" in proposal["functions"]
    assert proposal["params"]["change_id"] == change_id
    assert link["approval_proposal_id"] == pid
    signers = {"compliance": "wtr_comp_01", "command": "ic_01"}
    card = approvals.card(conn, pid)
    for function in proposal["functions"]:
        clock.advance(minutes=1)
        approvals.decide(
            conn,
            user_id=signers[function],
            proposal_id=pid,
            request=ApprovalRequest(
                decision="approve", proposal_version=card.proposal_version, action_hash=card.action_hash
            ),
        )
    state = conn.execute("SELECT state FROM proposal WHERE proposal_id = %s", (pid,)).fetchone()
    assert state is not None and state[0] == "approved"
    approvers = conn.execute(
        "SELECT approver_id FROM approval WHERE proposal_id = %s AND voided_at IS NULL", (pid,)
    ).fetchall()
    assert learning.ACTOR not in {a[0] for a in approvers}
    assert "wtr_comp_01" in {a[0] for a in approvers}
    watcher = CommitmentWatch(None, ledger=MemorySink())
    assert watcher.on_decision_approved(conn, proposal_id=pid, proposal_version=1, at=at) is None


def test_k3_commitment_reads_show_the_drift_and_milestones(drifted: dict[str, Any], db_url: str) -> None:
    import asyncio

    from sgw.models.commitments import read

    async def go() -> tuple[Any, Any, Any, Any]:
        async with await psycopg.AsyncConnection.connect(db_url) as aconn:
            listed = await read.list_commitments(aconn)
            only_drifted = await read.list_commitments(aconn, "drifted")
            one = await read.detail(aconn, CID)
            missing = await read.detail(aconn, "CMT-NOPE")
            return listed, only_drifted, one, missing

    listed, only_drifted, one, missing = asyncio.run(go())
    assert missing is None
    row = next(c for c in listed if c.commitment_id == CID)
    assert row.decision_case_id == golden.CASE_PS17 and row.milestones_total >= 1
    assert one is not None and one.commitment_id == CID
    assert [m.seq for m in one.milestones] == sorted(m.seq for m in one.milestones)
    assert all(m.signal_type for m in one.milestones)
    assert any(d.state == "drifted" and d.reopened for d in one.drift_log)
    assert row.state == "drifted" and CID in {c.commitment_id for c in only_drifted}
    assert row.drift_min is not None and row.drift_min > 0


def test_commitment_drift_reaches_a_webhook_subscription(db_url: str) -> None:
    """A drift written through the commitments outbox lands in the ledger and fans out to a commitments:read
    webhook subscription (the WP-37 pipeline delivers it)."""
    import asyncio
    from datetime import UTC, datetime

    from psycopg import AsyncConnection

    from sgw.approval.ledger import OutboxSink as ApprovalOutbox
    from sgw.contracts.vocab import ApiScope
    from sgw.integrations import repository
    from sgw.integrations.dispatch import dispatch_all
    from sgw.integrations.testkit import ALLOWED_HOST, KEYS

    wall = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)
    with testkit.seeded_database() as url:

        async def subscribe() -> str:
            async with await AsyncConnection.connect(url, autocommit=True) as a:
                async with a.transaction():
                    issued, _ = await repository.create_token(
                        a,
                        KEYS,
                        name="Ossabaw commitments board",
                        scopes=[ApiScope.COMMITMENTS_READ],
                        expires_at=wall + timedelta(days=30),
                        created_by="admin_01",
                        now=wall,
                        via="test",
                    )
                    who = await repository.resolve_token(a, KEYS, issued.token, wall)
                    assert who is not None
                    sub, _ = await repository.create_subscription(
                        a,
                        KEYS,
                        who,
                        url=f"https://{ALLOWED_HOST}/hooks",
                        event_types=["CommitmentDrifted"],
                        now=wall,
                    )
                return sub.subscription_id

        async def fan_out(subscription_id: str) -> list[str]:
            async with await AsyncConnection.connect(url, autocommit=True) as a:
                await dispatch_all(a, wall)
                cur = await a.execute(
                    "SELECT e.type FROM webhook_delivery d JOIN event e ON e.event_id = d.event_id"
                    " WHERE d.subscription_id = %s",
                    (subscription_id,),
                )
                return [r[0] for r in await cur.fetchall()]

        subscription_id = asyncio.run(subscribe())
        with psycopg.connect(url, autocommit=True) as c:
            clock = testkit.MutableClock(golden.ADVISORY_N1.issued)
            approvals = ApprovalService(
                ReferencePolicy(), scenario_clock=clock, token_clock=clock, ledger=ApprovalOutbox()
            )

            def set_time(at: Any) -> None:
                clock.at = at

            seeded = seed.seed_ps17_approved(c, approvals, set_time)
            watcher = CommitmentWatch(approvals, ledger=OutboxSink())
            at = seeded.approved_at + timedelta(minutes=1)
            watcher.on_decision_approved(c, proposal_id=seeded.proposal_id, proposal_version=1, at=at)
            moved = golden.ps17_clock(golden.ADVISORY_N1).decide_by_utc - timedelta(minutes=60)
            result = watcher.on_event(
                c,
                {
                    "type": "DecisionClockUpdated",
                    "event_time": (at + timedelta(minutes=5)).isoformat(),
                    "payload": {"decision_case_id": golden.CASE_PS17, "decide_by_utc": moved.isoformat()},
                },
            )
            assert result.drifted
        assert asyncio.run(fan_out(subscription_id)) == ["CommitmentDrifted"]
