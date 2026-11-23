"""The plain fallback answer: when the model cannot write the answer (no recording for the current state,
gateway down, failed checks), code answers in a few short rows from the same evidence and read models the
pages use, instead of listing every evidence item.

- The lead says why there is no AI answer, honestly (the recording no longer matches the state, none is
  recorded for this question at this moment, the AI is unavailable, or its answer failed the source check).
- Decisions come first: the ones the question names (with what they depend on), or the whole queue for a
  question about decisions and deadlines; open ones first with their deadline, then what became of the rest
  (decided on time, decided late, missed) at the scenario time: the outcome the decisions read carries
  (`sgw.approval.outcome`, as the Decisions page shows it), else the clock state rule. Rule-made cases
  (the hospital tanker) count like the advisory's cases.
- Customers out comes from the replayed county outage curve the Briefing reads; generators and stations from
  the water network; one procedure sentence with its source.
- Rows name decisions and assets only by id, which the reader sees as chips with plain names.
"Not found" only when no decision, asset, passage or platform number applies."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sgw.agent.copilot.clock_state import clock_state
from sgw.agent.copilot.fallback import DECISION_INTENTS, DECISION_WORDS, STOPWORDS, named_ids
from sgw.agent.copilot.investigate import NOT_IN_DOCS, CopilotAnswer, reader_time
from sgw.agent.copilot.link import asset_labels
from sgw.agent.copilot.tools import CopilotTools, _named, advisory_in_force
from sgw.agent.nodes import evidence_source as es
from sgw.agent.rag.answer import SopCitation
from sgw.agent.rag.tool import GuardedHit

LEAD = "Answer from platform data."
WHY = {
    "changed": "The recorded AI answer no longer matches the current state.",
    "unrecorded": "No AI answer is recorded for this question at this moment.",
    "unavailable": "The AI is not available right now.",
    "checks_failed": "The AI answer failed its source check.",
}
REPLAY_MISS = frozenset({"gateway_424", "replay_miss"})
MAX_ROWS = 5
MAX_DECISION_ROWS = 4
MAX_QUOTE = 220

OUTAGE_WORDS = re.compile(
    r"\b(?:customers?|outages?|without\s+power|power\s+out|lights?\s+out|klient\w*|odbiorc\w*|bez\s+pr[aą]du|"
    r"awari\w*\s+(?:pr[aą]du|zasilania)|kunden|stromausf[aä]ll\w*|clientes|apagones?|sin\s+luz|clients|pannes?)\b",
    re.I,
)
CREW_WORDS = re.compile(r"\bcrews?\b", re.I)
MISSED_WORDS = re.compile(r"\b(?:missed|miss|przegap\w*)\b", re.I)
GENERATOR_WORDS = re.compile(r"\bgenerators?\b", re.I)
PROCEDURE_WORDS = re.compile(
    r"\b(?:procedures?|require\w*|rules?|policy|sop|plan\s+says|who\s+(?:approves|signs)|must|revise\w*)\b",
    re.I,
)
DEADLINE_WORDS = re.compile(r"\b(?:decide|decisions?|deadlines?|due|sign\w*|overdue)\b", re.I)
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "eight": 8, "twelve": 12}
WINDOW = re.compile(
    r"\bnext\s+(\d+|" + "|".join(NUMBER_WORDS) + r")\s+(hours?|hrs?|h|minutes?|mins?)\b", re.I
)
FEEDER_SECTION = re.compile(r"\b(?:([Ff])eeder )?FDR-[A-Z]+-(\d+)-S(\d+)\b")
FEEDER = re.compile(r"\b(?:([Ff])eeder )?FDR-[A-Z]+-(\d+)\b")
VEHICLE = re.compile(r"\b(?:FTK|WTK|MGEN)-([A-Z]+)(?:-(\d+))?\b")
SECTION_NUMBER = re.compile(r"^\s*\d+(?:\.\d+)*\s+")
LABEL_WORDS = frozenset({"onsite", "portable", "power"})
ETR = re.compile(r"\bETRs?\b")
CLAUSE_NUMBER = re.compile(r"^\s*\d+\.\d+")
SHORT_STOPWORDS = frozenset(
    {"the", "and", "for", "are", "has", "was", "who", "how", "why", "can", "our", "all"}
)
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z]|\d+\.\d)")


CODE_FIRST = "code_first"


LEAD_PL = "Odpowiedź z danych platformy."
WHY_PL = {
    "changed": "Nagrana odpowiedź AI nie pasuje już do obecnego stanu.",
    "unrecorded": "Dla tego pytania w tym momencie nie ma nagranej odpowiedzi AI.",
    "unavailable": "AI jest teraz niedostępne.",
    "checks_failed": "Odpowiedź AI nie przeszła sprawdzenia źródeł.",
}


def polish_lead(lead: str) -> str:
    """The lead line of a code answer to a Polish question, in Polish (V4-04)."""
    if not lead.startswith(LEAD):
        return lead
    why = next((k for k, v in WHY.items() if lead.endswith(v)), None)
    return f"{LEAD_PL} {WHY_PL[why]}" if why else LEAD_PL


PL_STATUS = (
    (r"open, its deadline \((.+?)\) has passed", r"otwarta, termin (\1) minął"),
    (r"its deadline \((.+?)\) has passed", r"termin (\1) minął"),
    (r"missed, not signed by its deadline( \(.+?\))?", r"termin minął bez podpisu\1"),
    (r"missed, no proposal before its deadline( \(.+?\))?", r"termin minął bez propozycji decyzji\1"),
    (r"draft, decide by (.+?)$", r"szkic, decyzja do \1"),
    (r"open, decide by (.+?) \(in (.+?)\)$", r"otwarta, decyzja do \1 (za \2)"),
    (r"open, decide by (.+?)$", r"otwarta, decyzja do \1"),
    (r"decided on time", "podjęta w terminie"),
    (r"decided late", "podjęta po terminie"),
    (r"decided", "podjęta"),
    (r"withdrawn", "wycofana"),
    (r"open", "otwarta"),
)
PL_COUNTS = {
    "decided on time": "w terminie",
    "decided late": "po terminie",
    "decided": "podjęte",
    "missed": "przegapione",
    "withdrawn": "wycofane",
    "sent back or withdrawn": "odesłane lub wycofane",
    "open": "otwarte",
}
PL_ROWS = (
    (
        r"^It also depends on (\d+) more decisions?: (.+)\.$",
        lambda m: f"Zależy też od {m[1]} innych decyzji: {pl_counts(m[2])}.",
    ),
    (
        r"^(.*?)Closed so far: (.+)\.$",
        lambda m: f"{polish_row(m[1].strip())} Zamknięte dotąd: {pl_counts(m[2])}.".lstrip(),
    ),
    (
        r"^(\d+) more open decisions?, (\d+) of them drafts?, (?:is|are) on the Decisions page\.$",
        lambda m: f"Kolejne otwarte decyzje ({m[1]}, w tym szkice: {m[2]}) są na stronie Decisions.",
    ),
    (
        r"^(\d+) more open decisions? (?:is|are) on the Decisions page\.$",
        lambda m: f"Kolejne otwarte decyzje ({m[1]}) są na stronie Decisions.",
    ),
    (r"^No decision was missed\.$", lambda m: "Żadna decyzja nie została przegapiona."),
    (
        r"^(\d+) more missed decisions? (?:is|are) on the Decisions page\. (.+)$",
        lambda m: f"Kolejne przegapione decyzje ({m[1]}) są na stronie Decisions. {polish_row(m[2])}",
    ),
    (
        r"^(\d+) open on the Decisions page(?:, (\d+) of them drafts?)?\.$",
        lambda m: f"Otwarte na stronie Decisions: {m[1]}" + (f", w tym szkice: {m[2]}." if m[2] else "."),
    ),
    (
        r"^(\d+) more decisions? due in the (.+?) (?:is|are) on the Decisions page\.$",
        lambda m: f"Kolejne decyzje z terminem ({m[1]}) są na stronie Decisions.",
    ),
    (r"^No decision is open\.$", lambda m: "Żadna decyzja nie jest otwarta."),
    (
        r"^No open decision needs more than one team to sign\.$",
        lambda m: "Żadna otwarta decyzja nie wymaga podpisu więcej niż jednego zespołu.",
    ),
    (
        r"^(\d+) more open decisions? needs? two teams; the Decisions page lists them\.$",
        lambda m: f"Kolejne decyzje wymagające dwóch zespołów ({m[1]}) są na stronie Decisions.",
    ),
    (r"^Nothing is due in the (.+)\.$", lambda m: "W tym czasie żadna decyzja nie ma terminu."),
    (r"^Next: ([^,]+), (.+)\.$", lambda m: f"Następna: {m[1]}, {pl_status(m[2])}."),
    (
        r"^([\d,]+) customers are out in (\d+) count(?:y|ies) \(as of (.+)\)\.$",
        lambda m: (
            f"Bez prądu jest {m[1]} klientów w {m[2]} {'hrabstwie' if m[2] == '1' else 'hrabstwach'}"
            f" (stan na {m[3]})."
        ),
    ),
    (r"^(\d+) crews(?:: (.+))?\.$", lambda m: f"Brygady: {m[1]}" + (f" ({m[2]})." if m[2] else ".")),
    (
        r"^(.+) have an onsite generator; (.+) have none\.$",
        lambda m: (
            f"Własny generator mają: {m[1].replace(' and ', ' i ')};"
            f" nie mają: {m[2].replace(' and ', ' i ')}."
        ),
    ),
    (
        r"^(.+) have an onsite generator\.$",
        lambda m: f"Własny generator mają: {m[1].replace(' and ', ' i ')}.",
    ),
    (
        r"^No station has an onsite generator(?:; .+)?\.$",
        lambda m: "Żadna stacja nie ma własnego generatora.",
    ),
    (
        r"^(PS-\d+) serves (\S+) and has an onsite generator\.$",
        lambda m: f"{m[1]} zasila {m[2]} i ma własny generator.",
    ),
    (
        r"^(PS-\d+) serves (\S+) and has no onsite generator\.$",
        lambda m: f"{m[1]} zasila {m[2]} i nie ma własnego generatora.",
    ),
    (r"^The procedure says: (.+)$", lambda m: f"Procedura mówi: {m[1]}"),
    (
        r"^A field record \(unverified\) says: (.+)$",
        lambda m: f"Raport z terenu (niezweryfikowany) mówi: {m[1]}",
    ),
    (
        r"^([A-Z][\w-]+): (two|three|four|\d+) teams sign it, (.+); (.+)\.$",
        lambda m: (
            f"{m[1]}: podpisują ją {PL_TEAMS.get(m[2], m[2])} zespoły, {m[3].replace(' and ', ' i ')};"
            f" {pl_status(m[4])}."
        ),
    ),
    (r"^(DC-[\w-]+): (.+)\.$", lambda m: f"{m[1]}: {pl_status(m[2])}."),
)


PL_TEAMS = {"two": "dwa", "three": "trzy", "four": "cztery"}


def pl_status(text: str) -> str:
    for pattern, repl in PL_STATUS:
        if re.fullmatch(pattern, text):
            return re.sub(pattern, repl, text)
    return text


def pl_counts(text: str) -> str:
    """ "14 (12 decided on time, 2 missed)" or "2 decided on time, 1 open" in Polish."""
    words = sorted(PL_COUNTS, key=len, reverse=True)
    return re.sub(
        r"(\d+) (" + "|".join(map(re.escape, words)) + r")", lambda m: f"{m[1]} {PL_COUNTS[m[2]]}", text
    )


def polish_row(sentence: str) -> str:
    """A code-answer row in Polish for a Polish question (F6): rows never stay English under one."""
    for pattern, repl in PL_ROWS:
        m = re.match(pattern, sentence)
        if m:
            return repl(m)
    return sentence


def framing(reason: str | None, recorded: bool) -> str:
    """The lead line: what the answer is and, unless code answers this kind of question by design, why the AI
    did not write it."""
    if reason == CODE_FIRST:
        return LEAD
    if reason == "checks_failed":
        key = "checks_failed"
    elif reason in REPLAY_MISS:
        key = "changed" if recorded else "unrecorded"
    else:
        key = "unavailable"
    return f"{LEAD} {WHY[key]}"


@dataclass(frozen=True)
class Case:
    case_id: str
    title: str
    due: datetime | None
    needs: tuple[str, ...] = ()
    assets: tuple[str, ...] = ()
    state: Mapping[str, str] = field(default_factory=dict)
    signers: tuple[str, ...] = ()

    @property
    def decision(self) -> str:
        return self.state.get("decision", "")

    @property
    def is_open(self) -> bool:
        return self.decision in ("waiting", "missed", "no_proposal", "draft") and not self.closed_unsigned

    @property
    def closed_unsigned(self) -> bool:
        return self.decision == "no_proposal" and self.state.get("deadline") == "passed"


def plain_title(title: str) -> str:
    """A server title with vehicle and asset ids in words, like the Decisions page shows it."""
    names = asset_labels()

    def vehicle(m: re.Match[str]) -> str:
        name = m.group(1).capitalize()
        return name if m.group(0).startswith("MGEN") or m.group(2) is None else f"{name} {m.group(2)}"

    text = FEEDER_SECTION.sub(
        lambda m: f"{m[1] or 'f'}eeder {m[2]}, section {m[3]}", VEHICLE.sub(vehicle, title)
    )
    text = FEEDER.sub(lambda m: f"{m[1] or 'f'}eeder {m[2]}", text)
    return re.sub(
        r"\b[A-Z]{2,4}-[A-Z0-9]+(?:-[A-Z0-9]+)*\b",
        lambda m: m.group(0) if m.group(0).startswith("PS-") else names.get(m.group(0), ("", m.group(0)))[1],
        text,
    )


def board(
    member_table: Mapping[str, Any],
    now: datetime,
    proposals: Sequence[Any],
    decided_at: Mapping[str, datetime],
    hints: Mapping[str, Mapping[str, str]],
    advisory_cases: bool = True,
    missed: Sequence[Any] = (),
) -> list[Case]:
    """Every case the reader can see at `now`: the advisory's cases, then rule-made cases from the decisions
    read, then the cases whose deadline passed with no proposal (`missed`); each with its state from the
    proposals when they are known, else from the evidence hints."""
    advisory, _ = advisory_in_force(member_table, now)
    queue, _ = es.clock_queue(member_table, advisory)
    cases: dict[str, Case] = {}
    for c in es.ordered_cases(queue) if advisory_cases else ():
        case_id = c.case.decision_case_id
        cases[case_id] = Case(
            case_id,
            c.case.title,
            c.case.effective_decide_by_utc,
            tuple(c.case.prerequisite_ids),
            tuple(es.CASE_ASSETS.get(case_id, ())),
        )
    for p in proposals:
        if p.decision_case_id not in cases and p.state != "draft":
            cases[p.decision_case_id] = Case(
                p.decision_case_id, plain_title(p.title), p.effective_decide_by_utc
            )
    for m in missed:
        if m.decision_case_id not in cases:
            cases[m.decision_case_id] = Case(m.decision_case_id, plain_title(m.title), m.effective_decide_by)
    out: list[Case] = []
    for case in cases.values():
        mine = [p for p in proposals if p.decision_case_id == case.case_id]
        if proposals:
            state = {**clock_state(case.case_id, case.due, proposals, now, decided_at), **page_outcome(mine)}
            due = latest_due(mine) or case.due
        else:
            state = dict(hints.get(case.case_id) or fallback_state(case.due, now))
            due = case.due
        signers = tuple(str(f) for f in getattr(mine[-1], "functions_required", ())) if mine else ()
        out.append(Case(case.case_id, case.title, due, case.needs, case.assets, state, signers))
    return out


OUTCOME_STATE = {"on_time": "decided_on_time", "late": "decided_late", "missed": "expired"}


def page_outcome(proposals: Sequence[Any]) -> dict[str, str]:
    """The outcome the Decisions page shows for the case's latest proposal (`sgw.approval.outcome`, on the
    decisions read), when it has one."""
    if not proposals:
        return {}
    latest = max(proposals, key=lambda p: p.proposal_version)
    outcome = getattr(latest, "outcome", None)
    return {"decision": OUTCOME_STATE[outcome]} if outcome in OUTCOME_STATE else {}


def latest_due(proposals: Sequence[Any]) -> datetime | None:
    if not proposals:
        return None
    return max(proposals, key=lambda p: p.proposal_version).effective_decide_by_utc


def fallback_state(due: datetime | None, now: datetime) -> dict[str, str]:
    """No decisions read and no clock state: only the deadline is known."""
    passed = due is not None and due < now
    return {"deadline": "passed" if passed else "open", "decision": "unknown" if passed else "waiting"}


def title_words(title: str) -> set[str]:
    rest = " ".join(title.split()[1:])
    words = {w.lower() for w in re.findall(r"\b[A-Z][a-z]{4,}\b", rest)}
    return words | ({"hospital"} if "hospital" in title.lower() else set())


def named_cases(question: str, entities: Iterable[str], cases: Sequence[Case]) -> tuple[list[Case], set[str]]:
    """(the cases the question names followed by what they depend on, the ids of the named ones)."""
    ids = named_ids(question, entities)
    words = set(re.findall(r"[a-z]+", question.lower()))
    asked = stems(question)
    named = [
        c
        for c in cases
        if c.case_id in ids
        or ids & set(c.assets)
        or words & title_words(c.title)
        or len(asked & stems(c.title)) >= 2
    ]
    by_id = {c.case_id: c for c in cases}
    seen = {c.case_id for c in named}
    chain = list(named)
    for case in chain:
        for need in case.needs:
            if need in by_id and need not in seen:
                seen.add(need)
                chain.append(by_id[need])
    return chain, {c.case_id for c in named}


def window(question: str) -> tuple[timedelta, str] | None:
    """The span a question asks about ("in the next 3 hours") and its words."""
    m = WINDOW.search(question)
    if m is None:
        return None
    raw = m.group(1).lower()
    n = int(raw) if raw.isdigit() else NUMBER_WORDS[raw]
    span = timedelta(minutes=n) if m.group(2).lower().startswith("m") else timedelta(hours=n)
    return span, " ".join(m.group(0).split()).lower()


def duration(delta: timedelta) -> str:
    minutes = max(int(delta.total_seconds() // 60), 0)
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)
    if days:
        return f"{days} d {hours} h" if hours else f"{days} d"
    if hours:
        return f"{hours} h {mins} m" if mins else f"{hours} h"
    return f"{mins} m"


def status(case: Case, now: datetime) -> str:
    due = reader_time(case.due) if case.due is not None else None
    decision = case.decision
    if decision == "decided_on_time":
        return "decided on time"
    if decision == "decided_late":
        return "decided late"
    if decision == "decided":
        return "decided"
    if case.closed_unsigned:
        return "missed, no proposal before its deadline"
    if decision == "expired":
        return "missed, not signed by its deadline"
    if decision == "unknown":
        return f"its deadline ({due}) has passed"
    if decision == "closed":
        return "withdrawn"
    if decision == "missed":
        return f"open, its deadline ({due}) has passed"
    if due is None or case.due is None:
        return "open"
    if decision == "draft":
        return f"draft, decide by {due}"
    left = case.due - now
    return f"open, decide by {due}" + (f" (in {duration(left)})" if left <= timedelta(hours=24) else "")


def outcome_counts(cases: Sequence[Case]) -> str:
    words = {
        "decided_on_time": "decided on time",
        "decided_late": "decided late",
        "decided": "decided",
        "expired": "missed",
        "closed": "withdrawn",
    }
    counts: dict[str, int] = {}
    for c in cases:
        word = "missed" if c.closed_unsigned else words.get(c.decision)
        if word:
            counts[word] = counts.get(word, 0) + 1
    order = ["decided on time", "decided late", "decided", "missed", "withdrawn"]
    return ", ".join(f"{counts[w]} {w}" for w in order if w in counts)


def about_decisions(question: str, intent: str | None) -> bool:
    return intent in DECISION_INTENTS or bool(
        DECISION_WORDS.search(question) or DEADLINE_WORDS.search(question)
    )


def named_rows(named: Sequence[Case], direct: set[str], now: datetime) -> list[tuple[str, str]]:
    """Open cases first (the named ones, then what they depend on, soonest deadline first); then the closed
    ones in the order the question leads to them."""
    opened = sorted(
        (c for c in named if c.is_open), key=lambda c: (c.case_id not in direct, c.due is None, c.due or now)
    )
    ordered = opened + [c for c in named if not c.is_open]
    shown = ordered if len(ordered) <= MAX_ROWS else ordered[:MAX_DECISION_ROWS]
    rows = [(c.case_id, f"{c.case_id}: {status(c, now)}.") for c in shown]
    rest = ordered[len(shown) :]
    if rest:
        summary = outcome_counts(rest) or f"{len(rest)} open"
        noun = "decision" if len(rest) == 1 else "decisions"
        rows.append(("more", f"It also depends on {len(rest)} more {noun}: {summary}."))
    return rows


CLOSED_WORDS = {"on_time": "decided on time", "late": "decided late", "missed": "missed"}
OPEN_OR_DRAFT = frozenset({"proposed", "in_review", "escalated", "draft"})


def closed_counts(proposals: Sequence[Any], decided_at: Mapping[str, datetime], unproposed: int = 0) -> str:
    """The Closed tab of the Decisions page in words: every proposal that is neither open nor a draft, by its
    outcome (`sgw.approval.outcome`, the rule the queue and the card read), and each decision whose deadline
    passed with no proposal (`unproposed`) as missed, so the counts always match the page and After-action."""
    from sgw.approval.outcome import DECIDED, decision_outcome
    from sgw.contracts.vocab import ProposalState

    counts: dict[str, int] = {}
    for p in proposals:
        state = str(getattr(p.state, "value", p.state))
        if state in OPEN_OR_DRAFT:
            continue
        outcome = decision_outcome(
            state=state,
            effective_decide_by_utc=p.effective_decide_by_utc,
            decided_at=decided_at.get(p.proposal_id),
        )
        word = CLOSED_WORDS.get(outcome or "") or (
            "decided" if ProposalState(state) in DECIDED else "sent back or withdrawn"
        )
        counts[word] = counts.get(word, 0) + 1
    if unproposed:
        counts["missed"] = counts.get("missed", 0) + unproposed
    order = ["decided on time", "decided late", "decided", "missed", "sent back or withdrawn"]
    total = sum(counts.values())
    if not total:
        return ""
    return f"{total} (" + ", ".join(f"{counts[w]} {w}" for w in order if w in counts) + ")"


def more_row(hidden: int, words: str | None, drafts: int = 0) -> list[tuple[str, str]]:
    """The open decisions a list leaves out, counted: the soonest few never read as all of them."""
    from sgw.agent.tools.personas import EXTRA

    if hidden <= 0 or not EXTRA["on"]:
        return []
    noun = "decision" if hidden == 1 else "decisions"
    verb = "is" if hidden == 1 else "are"
    what = f"{hidden} more {noun} due in the {words}" if words else f"{hidden} more open {noun}"
    if drafts and not words:
        what += f", {drafts} of them {'draft' if drafts == 1 else 'drafts'},"
    return [("more", f"{what} {verb} on the Decisions page.")]


@dataclass(frozen=True)
class PageOpen:
    """The Decisions page's Open tab: every proposal waiting on signers or still a draft, by case."""

    cases: frozenset[str] = frozenset()
    count: int = 0
    drafts: int = 0

    @classmethod
    def of(cls, proposals: Sequence[Any]) -> PageOpen:
        states = [(p.decision_case_id, str(getattr(p.state, "value", p.state))) for p in proposals]
        pending = [(c, s) for c, s in states if s in OPEN_OR_DRAFT]
        return cls(frozenset(c for c, _ in pending), len(pending), sum(s == "draft" for _, s in pending))

    @property
    def total(self) -> int:
        return self.count

    def line(self) -> str:
        drafts = f", {self.drafts} of them {'draft' if self.drafts == 1 else 'drafts'}" if self.drafts else ""
        return f"{self.total} open on the Decisions page{drafts}."


def missed_rows(
    cases: Sequence[Case], now: datetime, page: PageOpen | None, closed: str
) -> list[tuple[str, str]]:
    """ "Which decisions were missed?": the decisions the Decisions page closes as missed (deadline passed
    with no proposal, or not signed by it), by deadline, then the page's open and closed counts."""
    missed = sorted(
        (c for c in cases if c.closed_unsigned or c.decision == "expired"),
        key=lambda c: (c.due is None, c.due or now),
    )
    shown = missed[:MAX_DECISION_ROWS]
    rows = [
        (c.case_id, f"{c.case_id}: {status(c, now)}{f' ({reader_time(c.due)})' if c.due else ''}.")
        for c in shown
    ]
    if not missed:
        rows.append(("none", "No decision was missed."))
    hidden = len(missed) - len(shown)
    noun = "decision is" if hidden == 1 else "decisions are"
    more = f"{hidden} more missed {noun} on the Decisions page." if hidden else ""
    opened = page.line() if page and page.total else ""
    counts = " ".join(t for t in (more, opened, f"Closed so far: {closed}." if closed else "") if t)
    return rows + ([("more" if hidden else "closed", counts)] if counts else [])


TWO_TEAMS = re.compile(
    r"\b(?:two|2|both|several|multiple|more\s+than\s+one)\s+(?:teams?|signatures?|signers?|functions?|"
    r"approv\w*|people|roles?|sign-?offs?)\b|\bco-?sign\w*|\bdual\s+(?:sign|approv)\w*|"
    r"\bdw[oó]ch\s+(?:zespo\w*|podpis\w*|os[oó]b)|\bdwa\s+(?:zespo\w*|podpisy)|\bdwie\s+(?:osoby|role)\b",
    re.IGNORECASE,
)


COUNT_WORDS = {2: "two", 3: "three", 4: "four"}


def team_rows(cases: Sequence[Case], now: datetime) -> list[tuple[str, str]]:
    """ "Which decisions need two teams?": the open decisions signed by more than one team, with the teams."""
    from sgw.agent.copilot.reader import team

    shared = sorted(
        (c for c in cases if c.is_open and c.decision != "draft" and len(c.signers) >= 2),
        key=lambda c: (c.due is None, c.due is not None and c.due < now, c.due or now),
    )
    if not shared:
        return [("none", "No open decision needs more than one team to sign.")]
    rows = [
        (
            c.case_id,
            f"{c.case_id}: {COUNT_WORDS.get(len(c.signers), str(len(c.signers)))} teams sign it,"
            f" {', '.join(team(f) for f in c.signers[:-1])} and {team(c.signers[-1])}; {status(c, now)}.",
        )
        for c in shared[:MAX_DECISION_ROWS]
    ]
    hidden = len(shared) - MAX_DECISION_ROWS
    if hidden > 0:
        noun = "decision needs" if hidden == 1 else "decisions need"
        rows.append(("more", f"{hidden} more open {noun} two teams; the Decisions page lists them."))
    return rows


def decision_rows(
    question: str,
    intent: str | None,
    entities: Sequence[str],
    cases: Sequence[Case],
    now: datetime,
    closed_summary: str = "",
    page: PageOpen | None = None,
) -> list[tuple[str, str]]:
    named, direct = named_cases(question, entities, cases)
    if named:
        return named_rows(named, direct, now)
    if not about_decisions(question, intent):
        return []
    if TWO_TEAMS.search(question) and any(c.signers for c in cases):
        return team_rows(cases, now)
    if MISSED_WORDS.search(question):
        return missed_rows(
            cases, now, page, closed_summary or outcome_counts([c for c in cases if not c.is_open])
        )
    waiting = (c for c in cases if c.is_open and c.decision != "draft")
    open_cases = sorted(
        waiting, key=lambda c: (c.due is None, c.due is not None and c.due < now, c.due or now)
    )
    closed = [c for c in cases if not c.is_open]
    asked = window(question)
    rows: list[tuple[str, str]] = []
    if asked is not None:
        span, words = asked
        due_soon = [c for c in open_cases if c.due is not None and c.due <= now + span]
        later = [c for c in open_cases if c not in due_soon]
        if not due_soon:
            rows.append(("none", f"Nothing is due in the {words}."))
            if later:
                rows.append((later[0].case_id, f"Next: {later[0].case_id}, {status(later[0], now)}."))
        open_cases = due_soon
    elif not open_cases:
        rows.append(("none", "No decision is open."))
    listed = open_cases[:MAX_DECISION_ROWS]
    rows += [(c.case_id, f"{c.case_id}: {status(c, now)}.") for c in listed]
    if asked is None and page is not None and page.total:
        more = more_row(page.total - sum(c.case_id in page.cases for c in listed), None, page.drafts)
    else:
        more = more_row(len(open_cases) - MAX_DECISION_ROWS, asked[1] if asked is not None else None)
    closed_text = closed_summary or outcome_counts(closed)
    if closed_text and (more or len(rows) < MAX_ROWS):
        closed_row = f"Closed so far: {closed_text}."
        return rows + ([("more", f"{more[0][1]} {closed_row}")] if more else [("closed", closed_row)])
    return rows + more


def customers_row(question: str, now: datetime, scenario: str = "helene") -> list[tuple[str, str]]:
    if not OUTAGE_WORDS.search(question):
        return []
    from sgw.reports.sources import replay_status
    from sgw.scenarios import packs
    from sgw.scenarios.reads import status as pack_status

    pack = packs.get(scenario)
    try:
        s = pack_status(pack, now) if pack is not None else replay_status(now)
    except (ValueError, OSError):
        return []
    if s is None:
        return []
    county = "county" if s.counties_out == 1 else "counties"
    return [
        (
            "customers",
            f"{s.customers_out_now:,} customers are out in {s.counties_out} {county}"
            f" (as of {reader_time(s.as_of)}).",
        )
    ]


def crews_row(question: str, tools: CopilotTools) -> list[tuple[str, str]]:
    if not CREW_WORDS.search(question):
        return []
    summary = next((i for i in tools.items if i.kind == "crew_summary"), None)
    if summary is None:
        return []
    values = {k: int(v.value) for k, v in summary.values.items() if isinstance(v.value, int | float)}
    total = values.pop("crews", 0)
    values.pop("people", None)
    parts = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in values.items() if n)
    return [("crews", f"{total} crews" + (f": {parts}." if parts else "."))]


def water_rows(question: str, entities: Iterable[str]) -> list[tuple[str, str]]:
    stations = _named()["pump_stations"]
    named = sorted(i for i in named_ids(question, entities) if i in stations)
    if GENERATOR_WORDS.search(question) and not named:
        have = [ps for ps, info in sorted(stations.items()) if info.get("onsite_generator")]
        lack = [ps for ps in sorted(stations) if ps not in have]
        text = (
            f"{' and '.join(have)} have an onsite generator" if have else "No station has an onsite generator"
        )
        return [("generators", text + (f"; {' and '.join(lack)} have none." if lack else "."))]
    rows: list[tuple[str, str]] = []
    for ps in named[:2]:
        info = stations[ps]
        gen = "an onsite generator" if info.get("onsite_generator") else "no onsite generator"
        rows.append((ps, f"{ps} serves {info['zone']} and has {gen}."))
    return rows


def asset_rows(question: str, entities: Iterable[str], mentioned: str) -> list[tuple[str, str]]:
    labels = asset_labels()
    rows: list[tuple[str, str]] = []
    for ref in sorted(named_ids(question, entities)):
        if ref in labels and ref not in mentioned and not ref.startswith("PS-"):
            rows.append((ref, f"{ref}: {labels[ref][1]}."))
    return rows[:2]


def ordered_stems(text: str) -> list[str]:
    spelled = ETR.sub("estimated time of restoration", text)
    words = (w.removesuffix("s") for w in re.findall(r"[a-z]{3,}", spelled.lower()) if w not in STOPWORDS)
    return list(dict.fromkeys(w[:5] for w in words if w not in SHORT_STOPWORDS))


def stems(text: str) -> set[str]:
    return set(ordered_stems(text))


def sentences(hits: Sequence[GuardedHit]) -> list[tuple[GuardedHit, str]]:
    out: list[tuple[GuardedHit, str]] = []
    for g in hits:
        for block in g.blocks:
            if not block.lstrip().startswith(("+", "|")):
                out += [(g, s) for s in SENTENCE.split(" ".join(block.split())) if len(s.split()) > 3]
    return out


def best_quote(question: str, hits: Sequence[GuardedHit]) -> tuple[GuardedHit, str] | None:
    """The passage sentence that shares most content words with the question, its first content word (the
    verb of "when do I have to revise ...") counting double; a numbered clause wins a tie over prose, then
    the first one gathered."""
    asked = stems(question)
    lead = next(iter(ordered_stems(question)), None)
    best: tuple[tuple[int, int], GuardedHit, str] | None = None
    for g, sentence in sentences(hits):
        shared = asked & stems(sentence)
        score = (len(shared) + (lead in shared), int(bool(CLAUSE_NUMBER.match(sentence))))
        if shared and (best is None or score > best[0]):
            best = (score, g, SECTION_NUMBER.sub("", sentence))
    if best is None:
        return None
    _, g, sentence = best
    return g, sentence if len(sentence) <= MAX_QUOTE else sentence[: MAX_QUOTE - 1].rsplit(" ", 1)[0] + "…"


def quote_row(question: str, hits: Sequence[GuardedHit]) -> tuple[tuple[str, str], SopCitation] | None:
    found = best_quote(question, hits)
    if found is None:
        return None
    g, sentence = found
    h = g.hit
    unverified = h.trust != "verified_internal"
    cite = SopCitation(
        1, h.chunk_id, h.doc_id, h.version, h.citation_id, h.section, h.pages, sentence, unverified
    )
    who = "A field record (unverified) says" if unverified else "The procedure says"
    return ("quote", f'{who}: "{sentence}" [1]'), cite


@dataclass
class PlainInput:
    question: str
    intent: str | None
    entities: Sequence[str]
    now: datetime
    lead: str
    member_table: Mapping[str, Any]
    proposals: Sequence[Any] = ()
    decided_at: Mapping[str, datetime] = field(default_factory=dict)
    scenario: str = "helene"
    missed: Sequence[Any] = ()


def clock_hints(tools: CopilotTools) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for item in tools.items:
        if item.kind == "decision_clock" and "decision" in item.hints and item.entity_ids:
            out[item.entity_ids[0]] = {k: item.hints[k] for k in ("deadline", "decision") if k in item.hints}
    return out


def names_a_place(question: str) -> bool:
    """The question names a place of the service area by its name ("Tallowbranch hospital", "Cedarfall")."""
    labels = asset_labels().values()
    places = {
        w.lower() for _, label in labels for w in re.findall(r"\b[A-Z][a-z]{4,}\b", label)
    } - LABEL_WORDS
    return bool(places & set(re.findall(r"[a-z]+", question.lower())))


def reroutes(question: str, route: Any) -> Any:
    """The intent a question gets when the router model was unavailable and the keyword baseline found no
    family, but the question is about decisions, outages, crews or water, or names an asset: platform data
    answers it, so it is not out of scope. None when the route stands (instruction-like text never moves)."""
    from sgw.agent.copilot.fallback import WATER_WORDS
    from sgw.agent.route.intent import Intent

    if route.path != "m2" or route.intent is not Intent.OUT_OF_SCOPE or route.instructions_detected:
        return None
    if route.reason == "only_instructions":
        return None
    if DECISION_WORDS.search(question) or DEADLINE_WORDS.search(question):
        return Intent.ASSESS
    asks_data = OUTAGE_WORDS.search(question) or CREW_WORDS.search(question) or WATER_WORDS.search(question)
    if asks_data or route.entity_ids or names_a_place(question):
        return Intent.METRIC
    return None


def plain_answer(
    spec: PlainInput, tools: CopilotTools, reason: str | None
) -> tuple[CopilotAnswer, list[Case]]:
    """(the answer, the cases it may name). Rows are `[key] sentence`; the lead line says why."""
    from sgw.scenarios import packs

    cases = board(
        spec.member_table,
        spec.now,
        spec.proposals,
        spec.decided_at,
        clock_hints(tools),
        advisory_cases=not packs.is_pack(spec.scenario),
        missed=spec.missed,
    )
    closed = closed_counts(spec.proposals, spec.decided_at, len(spec.missed)) if spec.proposals else ""
    page = PageOpen.of(spec.proposals) if spec.proposals else None
    rows = decision_rows(spec.question, spec.intent, spec.entities, cases, spec.now, closed, page)
    rows += customers_row(spec.question, spec.now, spec.scenario)
    rows += crews_row(spec.question, tools)
    rows += water_rows(spec.question, spec.entities) if not rows and spec.scenario == "helene" else []
    rows += asset_rows(spec.question, spec.entities, " ".join(t for _, t in rows))
    hits = [g for g in tools.hits if stems(spec.question) & stems(" ".join([g.hit.title, *g.blocks]))]
    citations: list[SopCitation] = []
    wants_quote = not rows or bool(PROCEDURE_WORDS.search(spec.question))
    quoted = quote_row(spec.question, hits) if wants_quote and len(rows) < MAX_ROWS else None
    if quoted is not None:
        row, cite = quoted
        rows.append(row)
        citations.append(cite)
    rows = rows[:MAX_ROWS]
    if not rows:
        return CopilotAnswer(spec.question, "not_in_documents", NOT_IN_DOCS, NOT_IN_DOCS, reason=reason), []
    from sgw.agent.copilot.language import language_of

    polish = language_of(spec.question) == "pl"
    lead = polish_lead(spec.lead) if polish else spec.lead
    rows = [(key, polish_row(sentence)) for key, sentence in rows] if polish else rows
    text = "\n".join(
        [lead, *(f"[{key}] {sentence}" for key, sentence in rows), *(c.line() for c in citations)]
    )
    named = {c.case_id for c in cases if c.case_id in text}
    return (
        CopilotAnswer(spec.question, "m2", text, text, citations=citations, reason=reason),
        [c for c in cases if c.case_id in named],
    )


def decision_refs(cases: Iterable[Case]) -> list[dict[str, str]]:
    """References for the cases an answer names, with their plain titles (rule-made cases included)."""
    return [
        {"kind": "decision", "id": c.case_id, "label": plain_title(c.title), "match": c.case_id}
        for c in cases
    ]
