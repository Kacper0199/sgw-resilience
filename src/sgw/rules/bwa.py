"""Boil-water rules engine (SC and GA): triggers, lift (rescission) checks, lifecycle tasks, notice draft.

Every result names the clause it applies (`bwa_rules.yaml`): the regulation or guidance text and, where SGW's
controlled procedure restates it, the SOP section of the revision in force at the decision time (resolved
against the RAG corpus, never assumed). Floors apply at the customer's service connection (SC R.61-58.7.E(7),
GA 391-3-5-.10), so a pump-station sensor alone never triggers a pressure rule. Issuing, lifting and wording
stay T3 human decisions (`water_operations` + `compliance`); the engine only proposes and checks.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from sgw.models.water.floors import FlowCondition, State, pre_landfall_advisory, service_floor

RULES_PATH = Path(__file__).with_name("bwa_rules.yaml")


class NoticeKind(StrEnum):
    ADVISORY = "advisory"
    NOTICE = "notice"


class Cause(StrEnum):
    PRESSURE_LOSS = "pressure_loss"
    PRE_HURRICANE = "pre_hurricane"
    POSITIVE_SAMPLE = "positive_sample"


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class SopRef:
    doc_id: str
    section: str
    supports: tuple[str, ...] = ()


@dataclass(frozen=True)
class Clause:
    clause_id: str
    state: State
    rule_id: str
    summary: str
    citation: str
    label: str
    sop: SopRef | None = None


@dataclass(frozen=True)
class RuleBook:
    version: str
    clauses: dict[str, Clause]
    params: dict[str, Any]

    def clause(self, clause_id: str) -> Clause:
        try:
            return self.clauses[clause_id]
        except KeyError as exc:
            raise RuleError(f"bwa_rules.yaml: unknown clause {clause_id}") from exc

    def f(self, key: str) -> float:
        from sgw.common import numbers as numbers_mod

        return float(numbers_mod.value(str(self.params[key]["number"])))


@cache
def rulebook(path: Path = RULES_PATH) -> RuleBook:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    clauses = {
        cid: Clause(
            clause_id=cid,
            state=State(c["state"]),
            rule_id=str(c["rule_id"]),
            summary=str(c["summary"]),
            citation=str(c["citation"]),
            label=str(c["label"]),
            sop=SopRef(
                str(c["sop"]["doc_id"]),
                str(c["sop"]["section"]),
                tuple(str(t) for t in c.get("supports") or ()),
            )
            if c.get("sop")
            else None,
        )
        for cid, c in raw["clauses"].items()
    }
    return RuleBook(version=str(raw["version"]), clauses=clauses, params=dict(raw["params"]))


@dataclass(frozen=True)
class SopCitation:
    doc_id: str
    citation_id: str
    section: str
    section_text: str

    def text(self) -> str:
        return f"{self.citation_id} section {self.section}"


SECTION_START = re.compile(r"^(?:\d+\.\d+(?:\.\d+)*\s|#)")


def section_text(body: str, section: str) -> str | None:
    """The text of one numbered SOP section: its line and the lines up to the next numbered line or heading
    (lettered sub-items and notes belong to it)."""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"{section} "):
            out = [line]
            for nxt in lines[i + 1 :]:
                if SECTION_START.match(nxt):
                    break
                out.append(nxt)
            return " ".join(x.strip() for x in out if x.strip())
    return None


def sop_citation(clause: Clause, as_of: datetime) -> SopCitation | None:
    """The SOP revision in force at `as_of` that restates the clause. The cited section must exist and its
    own text must contain every `supports` phrase of the clause, so a citation cannot point at a section
    about something else."""
    if clause.sop is None:
        return None
    from sgw.agent.rag.corpus import in_force

    docs = [d for d in in_force(_corpus(), as_of) if d.doc_id == clause.sop.doc_id]
    if not docs:
        raise RuleError(f"{clause.clause_id}: no revision of {clause.sop.doc_id} in force at {as_of}")
    doc = docs[0]
    text = section_text(doc.body, clause.sop.section)
    if text is None:
        raise RuleError(f"{clause.clause_id}: {doc.citation_id} has no section {clause.sop.section}")
    if not clause.sop.supports:
        raise RuleError(f"{clause.clause_id}: a SOP citation needs `supports` phrases")
    missing = [t for t in clause.sop.supports if t.lower() not in text.lower()]
    if missing:
        raise RuleError(
            f"{clause.clause_id}: {doc.citation_id} section {clause.sop.section} does not say {missing}"
        )
    return SopCitation(doc.doc_id, doc.citation_id, clause.sop.section, text)


@cache
def _corpus() -> tuple[Any, ...]:
    from sgw.agent.rag.corpus import load_corpus

    return tuple(load_corpus())


def clause_text(clause: Clause, as_of: datetime) -> str:
    """Regulation or guidance citation plus the in-force SOP section, as the notice and card show it."""
    sop = sop_citation(clause, as_of)
    return (
        clause.citation
        if sop is None or sop.citation_id in clause.citation
        else (f"{clause.citation}; {sop.text()}")
    )


# ---- triggers ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PressureReading:
    node_id: str
    at_utc: datetime
    psi: float
    service_connection: bool
    heavy_flow: bool = False


@dataclass(frozen=True)
class RuleHit:
    clause: Clause
    kind: NoticeKind
    cause: Cause
    zone_id: str
    due_utc: datetime | None
    detail: dict[str, Any] = field(default_factory=dict)


PRESSURE_CLAUSE = {
    (State.SC, FlowCondition.NORMAL): "SC-P1",
    (State.SC, FlowCondition.HEAVY): "SC-P2",
    (State.GA, FlowCondition.NORMAL): "GA-P1",
    (State.GA, FlowCondition.HEAVY): "GA-P1",
}


def pressure_hits(state: State, zone_id: str, readings: Iterable[PressureReading]) -> list[RuleHit]:
    """A reading below the state floor at a service connection: SC 25 psi normal / 20 psi heavy flow
    (R.61-58.7.E(7)), GA 20 psi under all flows (391-3-5-.10). SC treats the loss of pressure as a
    precautionary advisory (SC DES guidance, SC-A1); GA's procedure issues the advisory (GA-P1)."""
    book = rulebook()
    hits: list[RuleHit] = []
    for r in sorted(readings, key=lambda x: (x.at_utc, x.node_id)):
        if not r.service_connection:
            continue
        condition = FlowCondition.HEAVY if r.heavy_flow else FlowCondition.NORMAL
        floor = service_floor(state, condition)
        if r.psi >= floor.psi:
            continue
        floor_clause = book.clause(PRESSURE_CLAUSE[(state, condition)])
        clause = book.clause("SC-A1") if state is State.SC else floor_clause
        hits.append(
            RuleHit(
                clause=clause,
                kind=NoticeKind.ADVISORY,
                cause=Cause.PRESSURE_LOSS,
                zone_id=zone_id,
                due_utc=r.at_utc,
                detail={
                    "node_id": r.node_id,
                    "psi": r.psi,
                    "floor_psi": floor.psi,
                    "floor_clause": floor_clause.clause_id,
                    "floor_rule_id": floor.rule_id,
                },
            )
        )
    return hits


def pre_landfall_hit(
    *,
    state: State,
    zone_id: str,
    now: datetime,
    landfall_utc: datetime,
    breach_p: float,
    on_backup_or_exposed: bool,
) -> RuleHit | None:
    """SC only, before landfall: a zone whose pumps are exposed or on backup power and whose forecast
    probability of breaching the service-connection floor reaches the SGW policy threshold
    (`policy_pre_landfall_breach_p`) gets a precautionary advisory due at landfall (SC-A2)."""
    if now >= landfall_utc:
        return None
    flag = pre_landfall_advisory(
        zone_id=zone_id,
        state=state,
        landfall_utc=landfall_utc,
        breach_p=breach_p,
        on_backup_or_exposed=on_backup_or_exposed,
    )
    if flag is None:
        return None
    return RuleHit(
        clause=rulebook().clause("SC-A2"),
        kind=NoticeKind.ADVISORY,
        cause=Cause.PRE_HURRICANE,
        zone_id=zone_id,
        due_utc=flag.due_utc,
        detail={"breach_p": breach_p, "basis_id": flag.basis.basis_id},
    )


def positive_sample_hit(state: State, zone_id: str, *, confirmed_at: datetime | None) -> RuleHit | None:
    """SC: a confirmed positive (routine plus repeat) makes it a boil water notice (SC-N1)."""
    if state is not State.SC or confirmed_at is None:
        return None
    return RuleHit(
        clause=rulebook().clause("SC-N1"),
        kind=NoticeKind.NOTICE,
        cause=Cause.POSITIVE_SAMPLE,
        zone_id=zone_id,
        due_utc=confirmed_at,
    )


# ---- lift (rescission) ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SampleSet:
    taken_utc: datetime
    samples: int
    site_ids: tuple[str, ...]
    total_coliform_positive: int


@dataclass(frozen=True)
class LiftEvidence:
    pressure_restored: bool
    integrity_restored: bool = True
    flushed_utc: datetime | None = None
    sample_sets: Sequence[SampleSet] = ()
    regulator_concurs: bool = False
    lost_pressure: bool | None = None
    quality_maintained: bool | None = None
    coliform_sites_total: int | None = None
    inspector_accepted_samples: int | None = None


@dataclass(frozen=True)
class LiftCheck:
    may_lift: bool
    met: tuple[str, ...]
    unmet: tuple[tuple[str, str], ...]
    path: str


class _Checks:
    def __init__(self) -> None:
        self.met: list[str] = []
        self.unmet: list[tuple[str, str]] = []

    def need(self, ok: bool, clause_id: str, reason: str) -> None:
        if ok:
            if clause_id not in self.met:
                self.met.append(clause_id)
        else:
            self.unmet.append((clause_id, reason))

    def result(self, path: str) -> LiftCheck:
        met = tuple(c for c in self.met if all(c != u for u, _ in self.unmet))
        return LiftCheck(not self.unmet, met, tuple(self.unmet), path)


def _negative(sets: Iterable[SampleSet]) -> bool:
    return all(s.total_coliform_positive == 0 for s in sets)


def _after(sets: Sequence[SampleSet], at: datetime | None) -> list[SampleSet]:
    return [s for s in sets if at is not None and s.taken_utc >= at]


def lift_check(state: State, cause: Cause, ev: LiftEvidence) -> LiftCheck:
    """May the advisory or notice be lifted? Returns the clauses met and each unmet clause with its reason."""
    book = rulebook()
    c = _Checks()
    if state is State.GA:
        sets = list(ev.sample_sets)
        c.need(
            ev.integrity_restored and ev.pressure_restored,
            "GA-L1",
            "integrity or positive pressure not restored",
        )
        c.need(ev.flushed_utc is not None, "GA-L1", "affected mains not flushed")
        gap = timedelta(hours=book.f("ga_sampling_after_flush_h"))
        early = [s for s in sets if ev.flushed_utc is not None and s.taken_utc < ev.flushed_utc + gap]
        c.need(bool(sets) and not early, "GA-L1", "samples taken sooner than the wait after flushing")
        samples = sum(s.samples for s in sets)
        sites = len({site for s in sets for site in s.site_ids})
        lo, hi = book.f("ga_rescission_samples_min"), book.f("ga_rescission_samples_max")
        if ev.inspector_accepted_samples is not None:
            if not lo <= ev.inspector_accepted_samples <= hi:
                raise RuleError(f"inspector-accepted sample count must be {lo} to {hi}")
            enough = samples >= ev.inspector_accepted_samples
        else:
            total = ev.coliform_sites_total or 0
            enough = total > 0 and sites >= book.f("ga_rescission_site_share") * total
        c.need(enough, "GA-L1", "too few coliform sites or samples")
        c.need(bool(sets) and _negative(sets), "GA-L1", "a total coliform result is positive or missing")
        c.need(ev.regulator_concurs, "GA-L1", "EPD concurrence not recorded")
        return c.result("ga_rescission")
    path = cause.value
    if cause is Cause.PRE_HURRICANE:
        if ev.lost_pressure is False and ev.quality_maintained is True:
            c.need(True, "SC-L3", "")
            c.need(ev.regulator_concurs, "SC-L4", "SCDES agreement not recorded")
            return c.result("pre_hurricane_no_loss")
        if ev.lost_pressure is None or ev.quality_maintained is None:
            c.need(False, "SC-L3", "post-storm evaluation of pressure and water quality not recorded")
            return c.result("pre_hurricane_unevaluated")
        c.need(True, "SC-L3", "")
        path = "pre_hurricane_with_loss"
    if cause is Cause.POSITIVE_SAMPLE:
        sets = sorted(_after(ev.sample_sets, ev.flushed_utc), key=lambda s: s.taken_utc)
        gap = timedelta(hours=book.f("sc_lift_sample_set_gap_h"))
        spaced: list[SampleSet] = []
        for s in sets:
            if not spaced or s.taken_utc - spaced[-1].taken_utc >= gap:
                spaced.append(s)
        c.need(ev.flushed_utc is not None, "SC-L2", "intense flushing not recorded")
        c.need(
            len(spaced) >= book.f("sc_lift_sample_sets"),
            "SC-L2",
            "fewer than the required sample sets taken far enough apart",
        )
        c.need(bool(sets) and _negative(sets), "SC-L2", "a coliform result is positive or missing")
    else:
        sets = _after(ev.sample_sets, ev.flushed_utc)
        c.need(ev.pressure_restored, "SC-L1", "pressure not restored")
        c.need(ev.flushed_utc is not None, "SC-L1", "flushing after restoration not recorded")
        c.need(bool(sets), "SC-L1", "no coliform samples after flushing")
        c.need(bool(sets) and _negative(sets), "SC-L1", "a coliform result is positive")
    c.need(bool(sets) and _negative(sets), "SC-L4", "not all total coliform results negative")
    c.need(ev.regulator_concurs, "SC-L4", "SCDES agreement not recorded")
    return c.result(path)


# ---- lifecycle tasks and notice draft ---------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    task_id: str
    phase: str
    title: str
    owner_function: str
    clause_id: str
    due_rule: str
    due_utc: datetime | None = None


def lifecycle_tasks(
    hit: RuleHit, *, critical_customers: Sequence[str] = (), landfall_utc: datetime | None = None
) -> list[Task]:
    """Tasks the advisory sets in motion, in order, each with its clause. Times are relative to release, which
    happens only after the T3 approval; `due_utc` is filled only for rule deadlines known now."""
    book = rulebook()
    z = hit.zone_id
    tasks: list[Task] = []

    def add(
        phase: str, title: str, owner: str, clause: str, due_rule: str, due: datetime | None = None
    ) -> None:
        tasks.append(Task(f"BWA-{z}-{len(tasks) + 1:02d}", phase, title, owner, clause, due_rule, due))

    if hit.clause.state is State.SC:
        if hit.cause is Cause.PRE_HURRICANE:
            add(
                "issue",
                "Decide and release the precautionary advisory",
                "water_operations",
                "SC-A2",
                "before landfall",
                hit.due_utc,
            )
        add("issue", "Notify SCDES of the advisory", "compliance", "SC-C1", "immediately on issue")
        for cust in critical_customers:
            add(
                "issue",
                f"Verbal notice to {cust} and the county EMA",
                "water_operations",
                "SC-I1",
                "first, before the written notice",
            )
        add(
            "issue",
            "Release the written notice with the next update time",
            "compliance",
            "SC-I1",
            f"within {book.f('sc_written_notice_h'):g} h of the verbal notice",
        )
        add("issue", "Forward a copy of the notice to SCDES", "compliance", "SC-C1", "as soon as possible")
        if hit.cause is Cause.PRE_HURRICANE:
            add(
                "monitor",
                "Evaluate the zone for pressure loss and water quality after the storm",
                "water_operations",
                "SC-L3",
                "immediately after the hurricane passes",
                None,
            )
        add(
            "lift",
            "Flush intensely once pressure is restored, then take coliform samples across the area",
            "water_operations",
            "SC-L1",
            "after pressure is restored",
        )
        add(
            "lift",
            "Confirm all total coliform results negative and SCDES agreement",
            "compliance",
            "SC-L4",
            "before the repeal",
        )
        add(
            "lift",
            "Release the repeal by the same channels and notify SCDES with a copy",
            "compliance",
            "SC-C1",
            "on repeal",
        )
        return tasks
    add(
        "issue",
        "Notify the EPD district inspector",
        "compliance",
        "GA-C1",
        "before the public notice where possible",
    )
    add(
        "issue",
        "Release the approved notice through the notice channels",
        "compliance",
        "GA-I1",
        f"within {book.f('ga_release_h'):g} h of the decision",
    )
    for cust in critical_customers:
        add("issue", f"Phone {cust} directly", "water_operations", "GA-I1", "on release")
    add(
        "issue",
        "Send the written notice copy to the district office",
        "compliance",
        "GA-C1",
        f"within {book.f('ga_written_copy_h'):g} h",
    )
    add(
        "lift",
        "Restore integrity, hold positive pressure and flush the affected mains",
        "water_operations",
        "GA-L1",
        "before sampling",
    )
    add(
        "lift",
        "Sample at least the required share of coliform sites",
        "water_operations",
        "GA-L1",
        f"no sooner than {book.f('ga_sampling_after_flush_h'):g} h after flushing",
    )
    add(
        "lift",
        "Send results to the EPD inspector and request concurrence; release the rescission",
        "compliance",
        "GA-L1",
        "after all total coliform results are negative",
    )
    return tasks


NOTICE_TEMPLATES = {
    State.SC: ("WQC 07.120", "ATTACHMENT A NOTICE WORDING", "Attachment A"),
    State.GA: ("WQC 07.114", "6.3.1 Prepare the notice from PCN 02.031", "section 6.3.1 (PCN 02.031)"),
}


def notice_template(state: State, as_of: datetime) -> str:
    """The notice wording's source in the SOP revision in force, checked to be in that revision's text."""
    from sgw.agent.rag.corpus import in_force

    doc_id, marker, where = NOTICE_TEMPLATES[state]
    docs = [d for d in in_force(_corpus(), as_of) if d.doc_id == doc_id]
    if not docs or marker not in docs[0].body:
        raise RuleError(f"no in-force {doc_id} with the notice wording at {as_of}")
    return f"{docs[0].citation_id} {where}"


@dataclass(frozen=True)
class NoticeDraft:
    title: str
    body: str
    clause_id: str
    clause: str
    template: str


def notice_draft(hit: RuleHit, *, zone_name: str, as_of: datetime, cause_text: str) -> NoticeDraft:
    """The public notice wording from the in-force SOP attachment (SC: WQC 07.120 Attachment A, GA: PCN
    02.031 via WQC 07.114 6.3.1), filled by code; issue and next-update times stay blanks for release."""
    clause_ref = clause_text(hit.clause, as_of)
    kind = "Boil Water Advisory" if hit.kind is NoticeKind.ADVISORY else "Boil Water Notice"
    regulator = (
        "the South Carolina Department of Environmental Services (SCDES)"
        if hit.clause.state is State.SC
        else "the Georgia Environmental Protection Division (EPD)"
    )
    template = notice_template(hit.clause.state, as_of)
    title = f"{kind.upper()} for customers of SGW in the {zone_name} water zone"
    body = (
        f"{title}. Issued: [date and time of release]. "
        f"{cause_text} Customers in the {zone_name} zone should boil water used for drinking and cooking. "
        "Bring water to a rolling boil for one minute, then let it cool before use. "
        "Use boiled or bottled water for drinking, making ice, brushing teeth, washing dishes "
        "and preparing food. "
        f"SGW is working with {regulator}. We will lift this {kind.lower()} when test results show the water "
        "is safe. For questions call SGW Water at [phone]. We will provide the next update at: [time]."
    )
    return NoticeDraft(
        title=title, body=body, clause_id=hit.clause.clause_id, clause=clause_ref, template=template
    )
