"""Clocks met/missed and break-glass co-sign status from audit records (pure logic; the DB path is in
tests/unit/agent/graphs/test_reports_db.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sgw.reports.after_action import _Record, break_glass_uses, clock_outcomes

T0 = datetime(2024, 9, 26, 6, 0, tzinfo=UTC)


def _rec(
    seq: int, at: datetime, kind: str, subject: str, actor: str = "system:approval", **payload: Any
) -> _Record:
    return _Record(seq=seq, occurred_at=at, kind=kind, actor_id=actor, subject=subject, payload=payload)


def _case(case: str, due: datetime) -> dict[str, Any]:
    return {"decision_case_id": case, "step": "D2", "title": case, "effective_decide_by_utc": due}


def test_met_missed_and_open_follow_the_first_authority_record() -> None:
    cases = [
        _case("DC-A", T0 + timedelta(hours=2)),
        _case("DC-B", T0 + timedelta(hours=1)),
        _case("DC-C", T0 + timedelta(hours=3)),
        _case("DC-D", T0 + timedelta(hours=10)),
    ]
    proposals = {"P-A1": "DC-A", "P-A2": "DC-A", "P-B": "DC-B", "P-D": "DC-D"}
    records = [
        _rec(1, T0, "proposal_created", "P-A1", "ops_dm_01"),
        _rec(2, T0 + timedelta(hours=3), "execution_token_issued", "P-A2"),
        _rec(3, T0 + timedelta(minutes=90), "execution_token_issued", "P-A1"),
        _rec(4, T0 + timedelta(minutes=80), "break_glass_used", "P-B", "ic_01"),
        _rec(5, T0 + timedelta(minutes=5), "approval_recorded", "P-D", "ic_01"),
    ]
    out = {c.decision_case_id: c for c in clock_outcomes(cases, proposals, records, T0 + timedelta(hours=5))}
    assert out["DC-A"].outcome == "met" and out["DC-A"].proposal_id == "P-A1" and out["DC-A"].margin_min == 30
    assert out["DC-B"].outcome == "missed" and out["DC-B"].decided_by == "break_glass"
    assert out["DC-B"].margin_min == -20
    assert out["DC-C"].outcome == "missed" and out["DC-C"].decided_at is None, "passed with no decision"
    assert out["DC-D"].outcome == "open", "a single approval is not authority"
    assert [c.decision_case_id for c in clock_outcomes(cases, proposals, records, T0)] == [
        "DC-B",
        "DC-A",
        "DC-C",
        "DC-D",
    ]


def _used(seq: int, bg: int, at: datetime, subject: str) -> _Record:
    due = (at + timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    return _rec(
        seq, at, "break_glass_used", subject, "ic_01", break_glass_id=bg, cosign_due_utc=due, tier="T3"
    )


def test_break_glass_cosign_status_and_table_cross_check() -> None:
    records = [
        _used(1, 1, T0, "P-1"),
        _rec(
            2, T0 + timedelta(hours=3), "break_glass_cosigned", "P-1", "log_01", break_glass_id=1, late=False
        ),
        _used(3, 2, T0, "P-2"),
        _rec(
            4, T0 + timedelta(hours=30), "break_glass_cosigned", "P-2", "log_01", break_glass_id=2, late=True
        ),
        _used(5, 3, T0, "P-3"),
        _rec(6, T0 + timedelta(hours=25), "break_glass_cosign_overdue", "P-3", break_glass_id=3),
        _used(7, 4, T0 + timedelta(hours=20), "P-4"),
        _used(8, 5, T0, "P-5"),
    ]
    table = {
        1: {"proposal_id": "P-1", "ic_id": "ic_01", "cosigned_by": "log_01"},
        2: {"proposal_id": "P-2", "ic_id": "ic_01", "cosigned_by": "log_01"},
        3: {"proposal_id": "P-3", "ic_id": "ic_01", "cosigned_by": None},
        4: {"proposal_id": "P-4", "ic_id": "ic_01", "cosigned_by": "log_01"},
    }
    out = {b.break_glass_id: b for b in break_glass_uses(records, table, T0 + timedelta(hours=31))}
    assert [out[i].status for i in (1, 2, 3, 4, 5)] == [
        "cosigned_on_time",
        "cosigned_late",
        "overdue_unsigned",
        "awaiting_cosign",
        "overdue_unsigned",
    ]
    assert out[1].table_agrees and out[2].table_agrees and out[3].table_agrees
    assert not out[4].table_agrees, "table says co-signed, chain has no co-sign record"
    assert not out[5].table_agrees, "no table row"
    assert out[2].cosigned_by == "log_01" and out[2].cosigned_at == T0 + timedelta(hours=30)


def test_broken_chain_makes_undecided_clocks_and_unsigned_uses_unverifiable() -> None:
    cases = [_case("DC-A", T0 + timedelta(hours=1)), _case("DC-B", T0 + timedelta(hours=1))]
    records = [_rec(1, T0, "execution_token_issued", "P-A")]
    out = {
        c.decision_case_id: c.outcome
        for c in clock_outcomes(
            cases, {"P-A": "DC-A", "P-B": "DC-B"}, records, T0 + timedelta(hours=9), chain_ok=False
        )
    }
    assert out == {"DC-A": "met", "DC-B": "unverifiable"}
    late = [_used(2, 7, T0, "P-B")]
    shaky = [_used(9, 8, T0, "P-C")]
    uses = break_glass_uses(late, {}, T0 + timedelta(hours=30), chain_ok=False, untrusted=shaky)
    assert [(u.break_glass_id, u.status) for u in uses] == [(7, "unverifiable"), (8, "unverifiable")]


def test_record_own_kind_decides_how_a_clock_was_decided() -> None:
    cases = [_case("DC-A", T0 + timedelta(hours=1))]
    records = [
        _rec(1, T0, "execution_token_issued", "P-A"),
        _used(2, 1, T0, "P-A"),
    ]
    [c] = clock_outcomes(cases, {"P-A": "DC-A"}, records, T0)
    assert c.decided_by == "break_glass", "break-glass issues its token at the same time"
    [c] = clock_outcomes(cases, {"P-A": "DC-A"}, records[:1], T0)
    assert c.decided_by == "approval"


def test_the_page_counts_an_open_decision_past_its_deadline_as_open() -> None:
    """V4-10: After-action counts missed deadlines as Decisions and Ask do: a decision still open past its
    decide-by is open (Decisions: open, overdue), missed once it closed without a decision."""
    from sgw.api.readmodels.after_action import page_clocks

    cases = [_case("DC-OPEN", T0), _case("DC-CLOSED", T0)]
    review = clock_outcomes(cases, {"P-O": "DC-OPEN", "P-C": "DC-CLOSED"}, [], T0 + timedelta(hours=1))
    assert [c.outcome for c in review] == ["missed", "missed"]
    rows = {r.decision_case_id: r.outcome for r in page_clocks(review, frozenset({"DC-OPEN"}))}
    assert rows == {"DC-OPEN": "open", "DC-CLOSED": "missed"}


def test_the_ai_report_counts_an_open_decision_past_its_deadline_as_open() -> None:
    """The after-action report counts as the page does: open past its decide-by is open, not missed."""
    from sgw.reports.after_action import AfterActionReview, ChainCheck, counted_like_decisions

    cases = [_case("DC-OPEN", T0), _case("DC-CLOSED", T0)]
    clocks = clock_outcomes(cases, {"P-O": "DC-OPEN", "P-C": "DC-CLOSED"}, [], T0 + timedelta(hours=1))
    chain = ChainCheck(
        ok=True, checked_to_seq=0, first_bad_seq=None, signed_head_seq=None, trusted_to_seq=0, problems=[]
    )
    review = AfterActionReview(as_of=T0, chain=chain, clocks=clocks, break_glass=[], timeline=[])
    counted = counted_like_decisions(review, frozenset({"DC-OPEN"}))
    assert [c.decision_case_id for c in counted.missed] == ["DC-CLOSED"]
    assert [c.decision_case_id for c in counted.open] == ["DC-OPEN"]


def test_a_decision_never_proposed_is_missed_once_its_deadline_passed_and_stays_missed() -> None:
    """V4-10b: no proposal, so no authority record: missed after the deadline (open before it), never turned
    back into open by the Decisions rule, and marked as never proposed for the page."""
    from sgw.api.readmodels.after_action import page_clocks
    from sgw.reports.after_action import AfterActionReview, ChainCheck, counted_like_decisions

    cases = [_case("DC-NEVER", T0), _case("DC-OPEN", T0)]
    before = clock_outcomes(cases, {"P-O": "DC-OPEN"}, [], T0 - timedelta(minutes=1))
    assert {c.decision_case_id: c.outcome for c in before} == {"DC-NEVER": "open", "DC-OPEN": "open"}
    clocks = clock_outcomes(cases, {"P-O": "DC-OPEN"}, [], T0 + timedelta(hours=1))
    assert {c.decision_case_id: c.proposed for c in clocks} == {"DC-NEVER": False, "DC-OPEN": True}
    rows = {r.decision_case_id: (r.outcome, r.proposed) for r in page_clocks(clocks, frozenset({"DC-OPEN"}))}
    assert rows == {"DC-NEVER": ("missed", False), "DC-OPEN": ("open", True)}
    chain = ChainCheck(
        ok=True, checked_to_seq=0, first_bad_seq=None, signed_head_seq=None, trusted_to_seq=0, problems=[]
    )
    review = AfterActionReview(as_of=T0, chain=chain, clocks=clocks, break_glass=[], timeline=[])
    counted = counted_like_decisions(review, frozenset({"DC-OPEN"}))
    assert [c.decision_case_id for c in counted.missed] == ["DC-NEVER"]


def test_a_deadline_not_yet_due_and_not_yet_proposed_is_not_counted() -> None:
    """A deadline enters the count once it has a proposal or its deadline passed, so After-action's
    still-open equals Decisions > Open (proposals only)."""
    from sgw.api.readmodels.after_action import page_clocks
    from sgw.reports.after_action import counted_clocks

    cases = [_case("DC-LATER", T0 + timedelta(hours=5)), _case("DC-OPEN", T0 + timedelta(hours=5))]
    clocks = clock_outcomes(cases, {"P-O": "DC-OPEN"}, [], T0)
    assert [(c.decision_case_id, c.outcome) for c in counted_clocks(clocks, frozenset({"DC-OPEN"}))] == [
        ("DC-OPEN", "open")
    ]
    assert [r.decision_case_id for r in page_clocks(clocks, frozenset({"DC-OPEN"}))] == ["DC-OPEN"]
