"""Never-break fallback for the copilot: when the model cannot write the answer (replay miss, kill switch,
gateway error, refusal, truncation), a fixed planner reads what the question names and the M2 template
renders it by code.

The plan comes only from the question and the router's registry entity ids, never from model text:
- decision cases named by id, by an asset or yard they involve, or by a distinctive word of their title
  ("Tallowbranch"); every case when the question is about decisions but names none;
- the water network status when the question names a station, zone, tank or generator or asks about them;
- a procedure search on the question, whenever search is available.
Calls go through `CopilotTools.run`, so they are recorded, emitted live and refused like model calls."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from sgw.agent.copilot.tools import CopilotTools, _named, advisory_in_force
from sgw.agent.extract.registry import resolve
from sgw.agent.nodes import evidence_source as es
from sgw.agent.rag.tool import GuardedHit
from sgw.agent.route.intent import _REF_RE

MAX_CALLS = 8
DECISION_WORDS = re.compile(
    r"\b(?:decisions?|decide|deadlines?|decide-?by|advisory|act\s+now|wait|priorit\w*|due)\b", re.IGNORECASE
)
WATER_WORDS = re.compile(r"\b(?:pump\s+stations?|generators?|tanks?|(?:water|pressure)\s+zones?)\b", re.I)
WATER_PREFIXES = ("PS-", "WZ-", "TNK-", "GEN-PS")
DECISION_INTENTS = frozenset({"assess", "plan", "what_if", "sitrep"})


def named_ids(question: str, entities: Iterable[str]) -> set[str]:
    ids = set(entities)
    for ref in _REF_RE.findall(question):
        rid = resolve(ref)
        ids.add(rid or ref)
    return ids


STOPWORDS = frozenset(
    [
        "what",
        "which",
        "when",
        "where",
        "does",
        "have",
        "this",
        "that",
        "with",
        "from",
        "there",
        "about",
        "like",
        "they",
        "their",
        "would",
        "should",
        "could",
        "into",
        "been",
        "being",
        "will",
        "mean",
        "today",
        "your",
        "yours",
        "ours",
        "need",
        "needs",
        "much",
        "many",
        "some",
    ]
)


def _title_words(title: str) -> set[str]:
    """Distinctive words of a case title: its proper names (not the leading verb) and "hospital"."""
    rest = " ".join(title.split()[1:])
    return {w.lower() for w in re.findall(r"\b[A-Z][a-z]{4,}\b", rest)} | (
        {"hospital"} if "hospital" in title.lower() else set()
    )


def relevant(question: str, hit: GuardedHit) -> bool:
    """A searched passage shares a content word with the question (search always returns its top results)."""
    asked = {w for w in re.findall(r"[a-z]{4,}", question.lower()) if w not in STOPWORDS}
    h = hit.hit
    text = " ".join([h.title, h.section, *hit.blocks]).lower()
    return bool(asked & set(re.findall(r"[a-z]{4,}", text)))


def pick_cases(
    question: str,
    entities: Iterable[str],
    intent: str | None,
    member_table: Mapping[str, Any],
    as_of: Any,
) -> list[tuple[str, str]]:
    """(decision case id, domain) of the cases the question names by id, by an asset or yard they involve or
    by a distinctive title word; every case when it is about decisions but names none."""
    ids = named_ids(question, entities)
    words = set(re.findall(r"[a-z]+", question.lower()))
    advisory, _ = advisory_in_force(member_table, as_of)
    queue, _ = es.clock_queue(member_table, advisory)
    cases = [(c, es.case_item(1, c, as_of)) for c in es.ordered_cases(queue)]
    picked = [
        (c.case.decision_case_id, item.hints["domain"])
        for c, item in cases
        if c.case.decision_case_id in ids or ids & set(item.entity_ids) or words & _title_words(c.case.title)
    ]
    if not picked and (intent in DECISION_INTENTS or DECISION_WORDS.search(question)):
        picked = [(c.case.decision_case_id, item.hints["domain"]) for c, item in cases]
    return picked


def plan(
    question: str,
    entities: Iterable[str],
    intent: str | None,
    member_table: Mapping[str, Any],
    tools: CopilotTools,
) -> list[tuple[str, dict[str, Any]]]:
    picked = pick_cases(question, entities, intent, member_table, tools.ctx.as_of)
    calls: list[tuple[str, dict[str, Any]]] = [
        ("get_decision_case", {"decision_case_id": c}) for c, _ in picked
    ]
    zones = water_zones(named_ids(question, entities))
    if zones is not None or WATER_WORDS.search(question):
        calls.append(("get_water_status", {"zone_ids": sorted(zones or [])}))
    if tools.search is not None:
        calls.append(("search_procedures", {"query": " ".join(question.split())[:200]}))
    return calls[:MAX_CALLS]


def water_zones(ids: Iterable[str]) -> set[str] | None:
    """Zones of the named water assets (None when the question names none)."""
    stations = _named()["pump_stations"]
    named = [i for i in ids if i.startswith(WATER_PREFIXES)]
    if not named:
        return None
    zones = {i for i in named if i.startswith("WZ-")}
    for ps, info in stations.items():
        if {ps, info["tank"], info.get("onsite_generator")} & set(named):
            zones.add(info["zone"])
    return zones


def gather(
    question: str,
    entities: Iterable[str],
    intent: str | None,
    member_table: Mapping[str, Any],
    tools: CopilotTools,
) -> None:
    """Run the plan, skipping calls the model already made; passages its own search found are kept only when
    they share a content word with the question."""
    done = {(c["tool"], repr(sorted(c["args"].items()))) for c in tools.calls}
    before = len(tools.hits)
    for name, args in plan(question, entities, intent, member_table, tools):
        if (name, repr(sorted(args.items()))) not in done:
            tools.run(name, args)
    tools.hits[before:] = [g for g in tools.hits[before:] if relevant(question, g)]
