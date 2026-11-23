from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sgw.agent.copilot.plain import Case, PageOpen, decision_rows, polish_row
from sgw.agent.tools.executors import cut

NOW = datetime(2024, 9, 27, 12, tzinfo=UTC)
OPEN = {"decision": "waiting", "deadline": "open"}


def proposal(case: str, state: str) -> SimpleNamespace:
    return SimpleNamespace(decision_case_id=case, state=state)


def cases() -> list[Case]:
    return [
        Case("DC-OPEN-1", "Open one", NOW + timedelta(hours=1), state=OPEN),
        Case("DC-OPEN-2", "Open two", NOW + timedelta(hours=2), state=OPEN),
        Case("DC-ON-TIME", "Done", NOW - timedelta(hours=9), state={"decision": "decided_on_time"}),
        Case("DC-UNSIGNED", "Unsigned", NOW - timedelta(hours=4), state={"decision": "expired"}),
        Case(
            "DC-NEVER",
            "Never proposed",
            NOW - timedelta(hours=6),
            state={"decision": "no_proposal", "deadline": "passed"},
        ),
    ]


PAGE = PageOpen.of(
    [proposal("DC-OPEN-1", "proposed"), proposal("DC-OPEN-2", "in_review"), proposal("DC-DRAFT", "draft")]
)


def test_missed_question_names_the_missed_decisions_then_the_page_counts() -> None:
    rows = decision_rows(
        "Which decisions were missed?", None, (), cases(), NOW, "3 (1 decided on time, 2 missed)", PAGE
    )
    assert [k for k, _ in rows] == ["DC-NEVER", "DC-UNSIGNED", "closed"]
    assert rows[0][1].startswith("DC-NEVER: missed, no proposal before its deadline (")
    assert rows[1][1].startswith("DC-UNSIGNED: missed, not signed by its deadline (")
    assert (
        rows[2][1]
        == "3 open on the Decisions page, 1 of them draft. Closed so far: 3 (1 decided on time, 2 missed)."
    )


def test_no_missed_decision_says_so() -> None:
    rows = decision_rows("Which decisions were missed?", None, (), cases()[:3], NOW, "", PAGE)
    assert rows[0] == ("none", "No decision was missed.")


def test_open_list_counts_what_the_decisions_page_counts() -> None:
    many = [Case(f"DC-O{i}", f"O{i}", NOW + timedelta(hours=i + 1), state=OPEN) for i in range(6)]
    page = PageOpen.of([proposal(c.case_id, "proposed") for c in many] + [proposal("DC-D", "draft")])
    rows = decision_rows("Which decisions are open?", None, (), many, NOW, "", page)
    assert rows[-1] == ("more", "3 more open decisions, 1 of them draft, are on the Decisions page.")


def test_polish_missed_rows() -> None:
    assert polish_row("No decision was missed.") == "Żadna decyzja nie została przegapiona."
    assert (
        polish_row("14 open on the Decisions page, 3 of them drafts.")
        == "Otwarte na stronie Decisions: 14, w tym szkice: 3."
    )
    assert polish_row("DC-X: missed, not signed by its deadline (Sep 26, 21:59 ET).") == (
        "DC-X: termin minął bez podpisu (Sep 26, 21:59 ET)."
    )


def test_a_cut_decision_list_keeps_the_waiting_decisions() -> None:
    state = lambda s: SimpleNamespace(value=s)  # noqa: E731
    rows = [SimpleNamespace(state=state("executed"), n=i) for i in range(5)] + [
        SimpleNamespace(state=state("proposed"), n=9)
    ]
    assert [r.n for r in cut(rows, 3)] == [0, 1, 9]
    assert cut(rows, 10) == rows
