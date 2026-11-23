"""Report graphs against Postgres (SGW_TEST_DATABASE_URL): the after-action review read back from a real audit
chain (approval met, break-glass missed, late co-sign, tamper), the ETR published through the approval service
and the outbox only after two functions approved, and the sitrep on the M2 path when `FAULT_LLM_DOWN=1`."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from sgw.agent.nodes.gate import db_gate
from sgw.agent.nodes.ports import ApprovalServicePort
from sgw.agent.render.evidence import EvidenceBundle
from sgw.agent.render.slots import slot_values
from sgw.approval import audit
from sgw.approval import audit_testkit as atk_audit
from sgw.approval import testkit as atk
from sgw.approval.breakglass import BreakGlassService
from sgw.approval.breakglass_policy import ReferenceGovernance
from sgw.approval.ledger import MemorySink
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService, Revision
from sgw.approval.signer import Keyring
from sgw.contracts import golden
from sgw.contracts.api_models import BreakGlassRequest, ProposalCreate
from sgw.contracts.events import EtrPublished
from sgw.contracts.vocab import DegradedMode
from sgw.contracts.wire import WireEvent
from sgw.ops import testkit as ops_tk
from sgw.reports import after_action as aa
from sgw.reports.nodes import ETR_CASE, GLOBAL_TARGET
from sgw.reports.publisher import AlreadyPublished, NotApproved, OutboxEtrPublisher, estimates_digest

from ..agent_testkit import ScriptedLlm, text_reply
from . import reports_testkit as rk
from .test_report_graphs import GOOD

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
Conn = psycopg.Connection[Any]
START = golden.ADVISORY_N.issued + timedelta(minutes=10)
REASON = "Pressure floor at the hospital connection at risk; logistics chief unreachable"
LATE_CASE = "DC-D2-CREWS-AIK-LATE"


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if atk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with ops_tk.ops_database() as url:
        yield url


@pytest.fixture
def conn(db_url: str) -> Iterator[Conn]:
    with psycopg.connect(db_url, autocommit=True) as c:
        yield c


SIGNER = ops_tk.TEST_SIGNER


def _keyring() -> Keyring:
    """The ops notary's key signs checkpoints in this database too (kill switch and mode changes)."""
    return ops_tk.Notary().keyring


def _review(conn: Conn, at: Any) -> aa.AfterActionReview:
    return aa.review(conn, at, keyring=_keyring())


def _copy_case(conn: Conn, new_id: str, step: str = "D2") -> None:
    conn.execute(
        "INSERT INTO decision_case (decision_case_id, step, title, region_id, domain, clock_kind,"
        " consequence_utc, consequence_p10_utc, consequence_p90_utc, consequence_basis, action_lead_time_min,"
        " lead_time_basis, decide_by_utc, decide_by_p10_utc, decide_by_p90_utc, effective_decide_by_utc,"
        " on_critical_path, next_advisory_utc, if_late) SELECT %s, %s, title || ' (second staging)',"
        " region_id, domain, clock_kind, consequence_utc, consequence_p10_utc, consequence_p90_utc,"
        " consequence_basis, action_lead_time_min, lead_time_basis, decide_by_utc, decide_by_p10_utc,"
        " decide_by_p90_utc, effective_decide_by_utc, on_critical_path, next_advisory_utc, if_late"
        " FROM decision_case WHERE decision_case_id = %s ON CONFLICT (decision_case_id) DO NOTHING",
        (new_id, step, golden.CASE_CREWS),
    )


def _due(conn: Conn, case: str) -> Any:
    row = conn.execute(
        "SELECT effective_decide_by_utc, consequence_utc FROM decision_case WHERE decision_case_id = %s",
        (case,),
    ).fetchone()
    assert row is not None
    return row


def _story(conn: Conn) -> dict[str, Any]:
    """Crews approved by two functions before the clock; a second staging broken open after its clock and
    co-signed late."""
    clock = atk.MutableClock(START)
    approvals = ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=clock)
    bgs = BreakGlassService(approvals, ReferenceGovernance(), envelopes=None, signer=lambda: (SIGNER, None))
    met = atk.new_crew_proposal(conn, approvals)
    approvals.decide(conn, user_id="ic_01", proposal_id=met.proposal_id, request=atk.approve_req(met))
    approvals.decide(conn, user_id="log_01", proposal_id=met.proposal_id, request=atk.approve_req(met))
    _copy_case(conn, LATE_CASE)
    due, _consequence = _due(conn, LATE_CASE)
    clock.at = due + timedelta(minutes=20)
    late = approvals.create(
        conn,
        proposed_by="ops_dm_01",
        request=ProposalCreate.model_validate(
            {**atk.crew_request(10, 6).model_dump(mode="json"), "decision_case_id": LATE_CASE}
        ),
    ).value
    clock.at = due + timedelta(minutes=36)
    bgs.invoke(
        conn,
        user_id="ic_01",
        proposal_id=late.proposal_id,
        request=BreakGlassRequest(
            proposal_version=late.proposal_version, action_hash=late.action_hash, reason=REASON
        ),
    )
    clock.at = due + timedelta(hours=26)
    bgs.cosign(conn, user_id="log_01", proposal_id=late.proposal_id)
    audit.checkpoint(conn, SIGNER, None)
    return {
        "met": met.proposal_id,
        "late": late.proposal_id,
        "due": due,
        "review_at": due + timedelta(hours=30),
    }


@pytest.fixture(scope="module")
def story(db_url: str) -> dict[str, Any]:
    with psycopg.connect(db_url, autocommit=True) as c:
        return _story(c)


def test_review_reads_clocks_and_break_glass_from_the_verified_chain(
    conn: Conn, story: dict[str, Any]
) -> None:
    review = _review(conn, story["review_at"])
    assert review.chain.ok and review.chain.first_bad_seq is None, review.chain.problems
    assert review.chain.signed_head_seq == review.chain.checked_to_seq
    clocks = {c.decision_case_id: c for c in review.clocks}
    crews, late = clocks[golden.CASE_CREWS], clocks[LATE_CASE]
    assert crews.outcome == "met" and crews.decided_by == "approval" and crews.proposal_id == story["met"]
    assert late.outcome == "missed" and late.decided_by == "break_glass" and late.margin_min == -36
    [bg] = [b for b in review.break_glass if b.proposal_id == story["late"]]
    assert bg.status == "cosigned_late" and bg.cosigned_by == "log_01" and bg.ic_id == "ic_01"
    assert bg.table_agrees and bg.reason == REASON
    kinds = [t.kind for t in review.timeline if t.subject == story["late"]]
    assert (
        kinds[:1] == ["proposal_created"] and "break_glass_used" in kinds and "break_glass_cosigned" in kinds
    )


def test_a_deadline_that_passed_with_no_proposal_is_missed_on_every_page(
    conn: Conn, story: dict[str, Any]
) -> None:
    """V4-10b: one rule for a decision that never got a proposal: missed once its deadline passed, in the
    review (After-action and its report) and in `missed_unproposed` (Decisions > Closed and Ask)."""
    case = "DC-D2-CREWS-AIK-NEVER"
    _copy_case(conn, case)
    try:
        due, _ = _due(conn, case)
        assert case not in {c.decision_case_id for c in aa.missed_unproposed(conn, due)}
        listed = {c.decision_case_id: c for c in aa.missed_unproposed(conn, story["review_at"])}
        assert listed[case].effective_decide_by == due and listed[case].domain == "electric"
        clocks = {c.decision_case_id: c for c in _review(conn, story["review_at"]).clocks}
        assert clocks[case].outcome == "missed" and clocks[case].proposed is False
        assert clocks[golden.CASE_CREWS].proposed is True
        assert {c for c, r in clocks.items() if r.outcome == "missed" and not r.proposed} == set(listed)
    finally:
        conn.execute("DELETE FROM decision_case WHERE decision_case_id = %s", (case,))


async def test_after_action_graph_on_the_db_review_drafts_the_reports(
    conn: Conn, story: dict[str, Any]
) -> None:
    def review(at: Any) -> aa.AfterActionReview:
        return _review(conn, at)

    task = rk.run_task(
        "after_action", ScriptedLlm({}), review=review, as_of=story["review_at"], run_id="run-aa-db"
    )
    await task.run()
    state = await task.state()
    assert state["status"] == "draft_ready" and task.frames[-1].type is WireEvent.RUN_END
    text = state["narrative"]["rendered"]
    assert "The audit chain verified" in text and "1 missed" in text and "late 1" in text
    md = state["report"]["after_action_markdown"]
    assert f"| {LATE_CASE} | D2 |" in md and "| break_glass | missed | -36 min |" in md


async def test_tampered_chain_marks_later_facts_unverifiable_alerts_and_bans_the_drafts() -> None:
    with ops_tk.ops_database() as url, psycopg.connect(url, autocommit=True) as conn:
        story = _story(conn)
        row = conn.execute(
            "SELECT seq, payload FROM audit_event WHERE kind = 'break_glass_cosigned' AND subject = %s",
            (story["late"],),
        ).fetchone()
        assert row is not None
        seq, payload = int(row[0]), dict(row[1])
        atk_audit.tamper(url, audit.STREAM, seq, {**payload, "late": False}, recompute_chain=True)
        review = _review(conn, story["review_at"])
        assert not review.chain.ok and review.chain.first_bad_seq is not None
        assert review.chain.first_bad_seq <= seq and review.chain.trusted_to_seq < seq
        [bg] = [b for b in review.break_glass if b.proposal_id == story["late"]]
        assert bg.cosigned_by is None and not bg.table_agrees, "the rewritten co-sign record is not trusted"
        assert bg.status == "unverifiable", "never overdue against the named people on a broken chain"
        clocks = {c.decision_case_id: c.outcome for c in review.clocks}
        assert clocks[golden.CASE_CREWS] == "met", "decided by a trusted record"
        assert "missed" not in {c.outcome for c in review.clocks if c.decided_at is None}
        assert {c for c, o in clocks.items() if o == "unverifiable"} == {
            c.decision_case_id for c in review.clocks if c.decided_at is None
        }

        task = rk.run_task(
            "after_action",
            ScriptedLlm({}),
            review=lambda at: _review(conn, at),
            on_chain_broken=lambda chain: aa.record_chain_alert(conn, chain, story["review_at"]),
            as_of=story["review_at"],
            run_id="run-aa-tampered",
        )
        await task.run()
        state = await task.state()
        alerts = conn.execute(
            "SELECT payload FROM audit_event WHERE kind = 'security_alert'"
            " AND actor_id = 'system:after_action'"
        ).fetchall()
    assert [a["code"] for a in state["alerts"]] == ["SEC-52"]
    assert len(alerts) == 1 and alerts[0][0]["first_bad_seq"] == review.chain.first_bad_seq
    report = state["report"]
    assert report["usable"] is False
    for key in ("after_action_markdown", "sc_103_314_markdown"):
        assert report[key].startswith("> CHAIN BROKEN, NOT FOR USE."), key
    assert "unverifiable, not missed or overdue" in state["narrative"]["rendered"]
    assert "| unverifiable |" in report["after_action_markdown"]


def _etr_task(db_url: str, sink: MemorySink, service: ApprovalService, run_id: str) -> Any:
    def connect() -> Conn:
        return psycopg.connect(db_url, autocommit=True)

    return rk.run_task(
        "etr",
        ScriptedLlm({"etr_brief": text_reply(GOOD["etr_brief"])}),
        port=ApprovalServicePort(connect=connect, service=service),
        publisher=OutboxEtrPublisher(connect=connect, sink=sink, approvals=service),
        run_id=run_id,
    )


async def test_etr_publishes_through_the_execution_token_only_after_command_and_operations(
    db_url: str, conn: Conn
) -> None:
    sink, service = MemorySink(), ApprovalService(ReferencePolicy())
    task = _etr_task(db_url, sink, service, "run-etr-db")
    await task.run()
    state = await task.state()
    pid = state["approval"]["proposal_id"]
    row = conn.execute(
        "SELECT tier, required_functions::text[], state, proposed_by, rationale, decision_case_id, targets,"
        " params FROM proposal WHERE proposal_id = %s",
        (pid,),
    ).fetchone()
    assert row is not None and row[0] == "T3" and sorted(row[1]) == ["command", "operations"]
    assert row[2] == "proposed" and row[3] == "plan_etr_01" and "real storm" in row[4]
    assert row[5] == ETR_CASE and row[6] == [GLOBAL_TARGET], "seeded D4 case and territory asset"
    assert row[7]["estimates_digest"] == estimates_digest(rk.estimates()), "every estimate is in the hash"
    card = service.card(conn, pid)
    service.decide(conn, user_id="ic_01", proposal_id=pid, request=atk.approve_req(card))
    await task.resume("wake")
    assert (await task.state())["status"] == "awaiting_approval" and sink.queued == []
    service.decide(conn, user_id="ops_dm_01", proposal_id=pid, request=atk.approve_req(card))
    await task.resume("wake")
    final = await task.state()
    assert final["status"] == "executed", final["audit"][-3:]
    published = [e.payload for e in sink.queued]
    assert len(published) == len(rk.estimates()) and all(isinstance(e, EtrPublished) for e in published)
    first = published[0]
    assert isinstance(first, EtrPublished) and first.estimate_id == row[7]["estimate_id"]
    assert first.p50_utc.isoformat() == row[7]["p50_utc"]
    assert sink.drained == sink.queued
    state_row = conn.execute("SELECT state FROM proposal WHERE proposal_id = %s", (pid,)).fetchone()
    effect = conn.execute("SELECT effect_id, channel FROM effect WHERE proposal_id = %s", (pid,)).fetchall()
    token = atk.repo_token(conn, pid)
    assert state_row == ("executed",) and effect == [(f"EFF-{pid}", "etr_publication")]
    assert token is not None and token["burned_at"] is not None
    kinds = [
        r[0] for r in conn.execute("SELECT kind FROM audit_event WHERE subject = %s ORDER BY seq", (pid,))
    ]
    assert kinds[-2:] == ["execution_token_burned", "etr_published"]

    def connect() -> Conn:
        return psycopg.connect(db_url, autocommit=True)

    again = OutboxEtrPublisher(connect=connect, sink=sink, approvals=service)
    with pytest.raises(AlreadyPublished) as err:
        again.publish(
            pid,
            rk.estimates(),
            proposal_version=card.proposal_version,
            action_hash=card.action_hash,
            params=row[7],
            published_by="plan_etr_01",
            at=START,
        )
    assert err.value.status == 409 and len(sink.queued) == len(published), (
        "second execution publishes nothing"
    )
    await task.resume("wake")
    assert (await task.state())["status"] == "executed" and len(sink.queued) == len(published)

    review = _review(conn, START + timedelta(days=30))
    assert review.chain.ok, review.chain.problems
    assert "etr_published" in {t.kind for t in review.timeline}
    assert {c.decision_case_id: c.outcome for c in review.clocks}[ETR_CASE] in ("met", "missed")


async def test_etr_revised_after_the_run_showed_it_publishes_nothing(db_url: str, conn: Conn) -> None:
    sink, service = MemorySink(), ApprovalService(ReferencePolicy())
    task = _etr_task(db_url, sink, service, "run-etr-revised")
    await task.run()
    shown = (await task.state())["approval"]
    pid = shown["proposal_id"]
    card = service.card(conn, pid)
    params = {**card.params, "p50_utc": "2024-10-03T00:00:00+00:00"}
    revised = service.revise(
        conn, actor="plan_etr_01", proposal_id=pid, change=Revision(params=params), reason="later P50"
    ).value
    assert revised.proposal_version == 2 and revised.action_hash != shown["action_hash"]
    service.decide(conn, user_id="ic_01", proposal_id=pid, request=atk.approve_req(revised))
    service.decide(conn, user_id="ops_dm_01", proposal_id=pid, request=atk.approve_req(revised))
    await task.resume("wake")
    assert (await task.state())["status"] == "blocked" and sink.queued == []

    def connect() -> Conn:
        return psycopg.connect(db_url, autocommit=True)

    with pytest.raises(NotApproved):
        OutboxEtrPublisher(connect=connect, sink=sink, approvals=service).publish(
            pid,
            rk.estimates(),
            proposal_version=revised.proposal_version,
            action_hash=revised.action_hash,
            params=params,
            published_by="plan_etr_01",
            at=START,
        )
    token = atk.repo_token(conn, pid)
    assert sink.queued == [] and token is not None and token["burned_at"] is None


async def test_fault_llm_down_sitrep_takes_the_template_with_identical_slots(
    db_url: str, conn: Conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    def connect() -> Conn:
        return psycopg.connect(db_url, autocommit=True)

    ops_tk.reset_control(db_url)
    up_llm = ScriptedLlm({"sitrep": text_reply(GOOD["sitrep"])})
    up = rk.run_task("sitrep", up_llm, llm_gate=db_gate(connect), run_id="run-sitrep-up")
    await up.run()

    monkeypatch.setenv("FAULT_LLM_DOWN", "1")
    svc = ops_tk.service({"FAULT_LLM_DOWN": os.environ["FAULT_LLM_DOWN"]})
    assert svc.reconcile(conn).after is DegradedMode.M2
    down_llm = ScriptedLlm({"sitrep": text_reply(GOOD["sitrep"])})
    down = rk.run_task("sitrep", down_llm, llm_gate=db_gate(connect), run_id="run-sitrep-m2")
    await down.run()
    ops_tk.reset_control(db_url)

    a, b = await up.state(), await down.state()
    assert a["narrative"]["path"] == "llm" and len(up_llm.requests) == 1
    assert b["narrative"]["path"] == "m2" and b["narrative"]["reason"] == "llm_disabled"
    assert down_llm.requests == [], "the model is never called while the gate is closed"
    assert slot_values(EvidenceBundle.model_validate(a["bundle"])) == slot_values(
        EvidenceBundle.model_validate(b["bundle"])
    )
    for key, shown in a["narrative"]["slots_shown"].items():
        assert b["narrative"]["slots_shown"][key] == shown
    assert b["status"] == "draft_ready"
