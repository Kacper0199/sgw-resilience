from sgw.agent.copilot.notices import notice_line, zone_states


def decision(case: str, state: str) -> dict[str, object]:
    return {"kind": "decision", "entity_ids": [f"P-{case}", case], "hints": {"state": state}}


ITEMS = [
    decision("DC-D3-PS17-CEDARFALL-BWA", "executed"),
    decision("DC-D3-PS17-CEDARFALL-BWA-LIFT", "approved"),
    decision("DC-D3-PS23-LAURELSPUR-BWA", "approved"),
    decision("DC-D3-PS23-LAURELSPUR-BWA-LIFT", "proposed"),
    decision("DC-D3-PS38-COPPERLEAF-BWA", "approved"),
    decision("DC-D3-PS52-DEERWATER-BWA", "expired"),
    decision("DC-D3-PS17-FUEL", "expired"),
    {"kind": "pump_station", "entity_ids": ["DC-D3-PS17-CEDARFALL-BWA"], "hints": {}},
]


def test_zone_states_follow_the_lift_then_the_notice() -> None:
    expected = {"Cedarfall": "lifted", "Laurelspur": "lift_waiting", "Copperleaf": "in_force"}
    assert zone_states(ITEMS) == expected


def test_line_names_every_zone_when_the_answer_names_none() -> None:
    line = notice_line(ITEMS, "Power is falling. PS-17 pressure is above its floor.", "en")
    assert line == (
        "Boil-water notices: Cedarfall lifted; Laurelspur lift waiting for signatures;"
        " Copperleaf still in force."
    )


def test_line_adds_only_the_zones_the_answer_leaves_out() -> None:
    text = "The Laurelspur lift is waiting for Water operations to sign. Cedarfall pressure is 3.8 psi."
    line = notice_line(ITEMS, text, "en")
    assert line == "Other boil-water notices: Cedarfall lifted; Copperleaf still in force."


def test_polish_line() -> None:
    line = notice_line(ITEMS, "Komunikat dla Laurelspur czeka na podpisy.", "pl")
    assert line == (
        "Pozostałe komunikaty o gotowaniu wody: Cedarfall – zniesiony; Copperleaf – nadal obowiązuje."
    )


def test_no_line_when_all_named_or_no_notice() -> None:
    text = "Cedarfall's notice is lifted; Laurelspur's lift waits; Copperleaf's boil-water notice stays."
    assert notice_line(ITEMS, text, "en") == ""
    assert notice_line([decision("DC-D3-PS17-FUEL", "approved")], "", "en") == ""
