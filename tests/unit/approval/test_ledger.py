from __future__ import annotations

import sys
import types
from typing import Any

import psycopg
import pytest

from sgw.approval import testkit as tk
from sgw.approval.ledger import ORIGIN, MemorySink, OutboxSink
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.contracts.events import EVENT_MODELS
from sgw.contracts.vocab import Classification

Conn = psycopg.Connection[Any]


def test_approval_events_go_through_the_outbox_in_order(conn: Conn, clock: tk.MutableClock) -> None:
    sink = MemorySink()
    svc = ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=clock, ledger=sink)
    card = tk.new_crew_proposal(conn, svc)
    for user in ("ic_01", "log_01"):
        svc.decide(conn, user_id=user, proposal_id=card.proposal_id, request=tk.approve_req(card))
    types_ = [e.type for e in sink.queued]
    assert types_ == ["ProposalCreated", "ApprovalRecorded", "ApprovalRecorded", "DecisionApproved"]
    assert sink.drained == sink.queued
    assert set(sink.drain_states) == {(True, "IDLE")}
    for event in sink.queued:
        again = EVENT_MODELS[event.type].model_validate(event.model_dump(mode="json"))
        assert again.event_id == event.event_id and event.ledger_seq is None
        assert event.source_id == "sgw-platform" and event.classification is Classification.C1
        assert event.scenario_known_at == clock.at and event.region_id == card.case.region_id
    assert len({e.dedup_key for e in sink.queued}) == 4


def test_refused_decisions_queue_nothing(conn: Conn, clock: tk.MutableClock) -> None:
    sink = MemorySink()
    svc = ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=clock, ledger=sink)
    card = tk.new_crew_proposal(conn, svc)
    before = len(sink.queued)
    with pytest.raises(Exception):  # noqa: B017
        svc.decide(conn, user_id="ops_dm_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    assert len(sink.queued) == before


def test_outbox_sink_calls_wp07_enqueue_then_drain(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []
    outbox = types.ModuleType("sgw.ingest.outbox")
    relay = types.ModuleType("sgw.ingest.relay")
    outbox.enqueue = lambda conn, events, *, origin: (
        calls.append(("enqueue", (events, origin))) or len(events)
    )  # type: ignore[attr-defined]
    relay.drain = lambda conn: calls.append(("drain", conn))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sgw.ingest.outbox", outbox)
    monkeypatch.setitem(sys.modules, "sgw.ingest.relay", relay)
    sink = OutboxSink()
    assert sink.enqueue("conn", ["e1", "e2"]) == 2  # type: ignore[arg-type, list-item]
    sink.drain("conn")  # type: ignore[arg-type]
    assert calls == [("enqueue", (["e1", "e2"], ORIGIN)), ("drain", "conn")]


def test_no_drain_inside_a_caller_transaction(conn: Conn, clock: tk.MutableClock) -> None:
    sink = MemorySink()
    svc = ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=clock, ledger=sink)
    with conn.transaction():
        tk.new_crew_proposal(conn, svc)
    assert [e.type for e in sink.queued] == ["ProposalCreated"] and sink.drained == []


class BrokenDrainSink(MemorySink):
    def drain(self, conn: Conn) -> None:
        raise RuntimeError("relay down")


def test_drain_failure_after_commit_keeps_the_committed_approval(
    conn: Conn, clock: tk.MutableClock, caplog: pytest.LogCaptureFixture
) -> None:
    sink = BrokenDrainSink()
    svc = ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=clock, ledger=sink)
    card = tk.new_crew_proposal(conn, svc)
    out = svc.decide(conn, user_id="ic_01", proposal_id=card.proposal_id, request=tk.approve_req(card))
    assert out.value.proposal_state.value == "in_review"
    assert svc.card(conn, card.proposal_id).state.value == "in_review"
    assert [e.type for e in sink.queued] == ["ProposalCreated", "ApprovalRecorded"]
    assert "relay will retry" in caplog.text


def test_seed_queues_proposal_created_once(db_url: str) -> None:
    from sgw.approval.seed import run_seed
    from sgw.contracts import golden

    sink = MemorySink()
    with tk.scratch_database() as url:
        first = run_seed(url, ledger=sink)
        second = run_seed(url, ledger=sink)
    assert first.proposal_created and not second.proposal_created
    assert [(e.type, e.payload.proposal_id) for e in sink.drained] == [
        ("ProposalCreated", golden.PROPOSAL_CREWS)
    ]  # type: ignore[attr-defined]
