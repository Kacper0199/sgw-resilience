"""The boil-water notice line of an overview (AB-OVR-014): after the final advisory the water analyst reads
every notice and lift case, but the writer named the zones' notices only in some samples. Code adds one
sentence for the zones the answer leaves out, in the question's language, from the same decision evidence
the writer saw, so an overview always says what became of each zone's notice."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

NOTICE_CASE = re.compile(r"^DC-[A-Z0-9-]+?-([A-Z]+)-BWA(-LIFT)?$")
DONE = frozenset({"approved", "executed"})
WAITING = frozenset({"proposed", "in_review", "escalated"})
STATES = {
    "en": {
        "lifted": "lifted",
        "lift_waiting": "lift waiting for signatures",
        "in_force": "still in force",
        "waiting": "waiting for signatures",
    },
    "pl": {
        "lifted": "zniesiony",
        "lift_waiting": "zniesienie czeka na podpisy",
        "in_force": "nadal obowiązuje",
        "waiting": "czeka na podpisy",
    },
}
LEAD = {
    "en": ("Boil-water notices", "Other boil-water notices"),
    "pl": ("Komunikaty o gotowaniu wody", "Pozostałe komunikaty o gotowaniu wody"),
}
NOTICE_WORDS = re.compile(r"boil|notice|lift|gotow|komunikat|zniesi", re.I)
SENTENCE = re.compile(r"[^.!?\n]+")


def _value(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, Mapping) else getattr(obj, name, None)


def zone_states(items: Iterable[Any]) -> dict[str, str]:
    """Each zone's notice state from the decision evidence: lifted (its lift approved or executed), lift
    waiting (proposed), still in force (notice approved, no lift yet) or waiting (notice proposed); zones
    in their evidence order. Rejected, withdrawn or expired cases say nothing."""
    notice: dict[str, str] = {}
    lift: dict[str, str] = {}
    order: list[str] = []
    for item in items:
        if _value(item, "kind") != "decision":
            continue
        state = str((_value(item, "hints") or {}).get("state", ""))
        for entity in _value(item, "entity_ids") or []:
            m = NOTICE_CASE.match(str(entity))
            if not m:
                continue
            zone = m[1].capitalize()
            if zone not in order:
                order.append(zone)
            (lift if m[2] else notice)[zone] = state
    out: dict[str, str] = {}
    for zone in order:
        if lift.get(zone) in DONE:
            out[zone] = "lifted"
        elif lift.get(zone) in WAITING:
            out[zone] = "lift_waiting"
        elif notice.get(zone) in DONE:
            out[zone] = "in_force"
        elif notice.get(zone) in WAITING:
            out[zone] = "waiting"
    return out


def named_with_notice(text: str, zone: str) -> bool:
    """The answer already speaks of the zone's notice: one sentence names the zone and a notice word."""
    return any(zone.lower() in s.lower() and NOTICE_WORDS.search(s) for s in SENTENCE.findall(text or ""))


def notice_line(items: Iterable[Any], text: str, language: str) -> str:
    """One sentence naming each zone's notice the answer leaves out; empty when it names them all or the
    evidence holds no notice."""
    lang = "pl" if language == "pl" else "en"
    states = zone_states(items)
    missing = [(z, s) for z, s in states.items() if not named_with_notice(text, z)]
    if not missing:
        return ""
    lead = LEAD[lang][1 if len(missing) < len(states) else 0]
    sep = " – " if lang == "pl" else " "
    return f"{lead}: " + "; ".join(f"{z}{sep}{STATES[lang][s]}" for z, s in missing) + "."
