from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from sgw.api.readmodels import brief
from sgw.contracts.api_models import ProposalSummary

AT = datetime(2024, 9, 30, 12, 0, tzinfo=UTC)


def _summary(title: str, due: datetime) -> ProposalSummary:
    return ProposalSummary.model_construct(title=title, effective_decide_by_utc=due, proposal_id=title)


def _command(open_t3: list[ProposalSummary]) -> str:
    lines = brief.function_lines(open_t3, None, (0, 0), Counter(), at=AT)
    return lines[0].sentence


def test_a_future_deadline_reads_with_its_date_and_time_left() -> None:
    line = _command([_summary("Lift the notice", datetime(2024, 9, 30, 14, 30, tzinfo=UTC))])
    assert line == (
        "One decision needs two teams to sign; the next deadline is 30 Sep 10:30 ET (14:30Z),"
        " in 2 h 30 m (Lift the notice)."
    )


def test_a_passed_deadline_never_reads_as_next() -> None:
    late = _summary("Issue the notice", datetime(2024, 9, 28, 19, 45, tzinfo=UTC))
    later = _summary("Lift the notice", datetime(2024, 9, 30, 14, 30, tzinfo=UTC))
    line = _command([late, later])
    assert "next" not in line
    assert line == (
        "Two decisions need two teams to sign; the earliest deadline, 28 Sep 15:45 ET (19:45Z), passed"
        " 40 h 15 m ago (Issue the notice)."
    )
