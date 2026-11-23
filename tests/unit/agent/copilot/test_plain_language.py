"""F6: a code answer to a Polish question has Polish rows, not an English block under it."""

from __future__ import annotations

import pytest

from sgw.agent.copilot.plain import polish_row


@pytest.mark.parametrize(
    ("row", "polish"),
    [
        (
            "DC-D3-PS17-FUEL: open, its deadline (Sep 26, 21:59 ET) has passed.",
            "DC-D3-PS17-FUEL: otwarta, termin",
        ),
        (
            "DC-X: open, decide by Sep 27, 01:00 ET (in 2 h).",
            "DC-X: otwarta, decyzja do Sep 27, 01:00 ET (za 2 h).",
        ),
        (
            "Closed so far: 14 (12 decided on time, 2 missed).",
            "Zamknięte dotąd: 14 (12 w terminie, 2 przegapione).",
        ),
        ("5,137 customers are out in 1 county (as of Sep 26, 11:00 ET).", "Bez prądu jest 5,137 klientów"),
        (
            "PS-17 serves WZ-PS17-CEDARFALL and has no onsite generator.",
            "PS-17 zasila WZ-PS17-CEDARFALL i nie",
        ),
        ('The procedure says: "Revise the ETR." [1]', 'Procedura mówi: "Revise the ETR." [1]'),
    ],
)
def test_code_rows_follow_a_polish_question(row: str, polish: str) -> None:
    assert polish_row(row).startswith(polish)


def test_an_unknown_row_stays_as_it_is() -> None:
    assert polish_row("Something new.") == "Something new."
