"""The PS-17 demo story as thirteen API steps, each an operator's HTTP call as a seeded persona: the smoke
asserts them (with model provenance and the replay hit rate) and the bookmark build runs the same steps,
snapshotting the database at each bookmark and capturing each bookmark's key run as a K19 event log.

After a seek, a step reads the decisions the scenario jobs raise at the new time until they are there
(`until`): the seek answers once its own run is done, but on a busy database a rule proposal the policy
check could not clear in that run is raised by the next run a few seconds later (R35 defect 5)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from sgw.demo.bookmarks import (
    ADVISORY_N,
    ADVISORY_N1,
    BEFORE_N,
    ETR_TIME,
    MORNING_AFTER,
    NOTICES_LIFTED,
    REVIEW_TIME,
    Bookmark,
    bookmark,
)
from sgw.demo.client import DemoError, Persona, Run

BREAK_GLASS_REASON = "Logistics chief unreachable; storm onset forces crew staging now."
PS17_QUESTION = "What does advisory N do to PS-17's decide-by, and is it act now or wait?"
RULE_PREFIX = "PRP-ZR-"
OPEN = ("proposed", "in_review", "draft")
N1_RULE_CASES = {"DC-D3-PS17-FUEL", "DC-D3-HSP-TALLOWBRANCH-WATER"}
TANKER_CASE = "DC-D3-HSP-TALLOWBRANCH-TANKER"
LAURELSPUR_CASE = "DC-D3-PS23-LAURELSPUR-BWA"
COPPERLEAF_CASE = "DC-D3-PS38-COPPERLEAF-BWA"
DEERWATER_CASE = "DC-D3-PS52-DEERWATER-BWA"
CEDARFALL_LIFT_CASE = "DC-D3-PS17-CEDARFALL-BWA-LIFT"
COPPERLEAF_SIGNED = "2024-09-28T08:00:00Z"
DEERWATER_SIGNED = "2024-09-28T19:15:00Z"
CEDARFALL_LIFTED = "2024-09-30T08:45:00Z"
WATER_SIGNERS = ("wtr_lead_01", "wtr_comp_01")
MORNING_RULE_CASES = {
    TANKER_CASE,
    LAURELSPUR_CASE,
    "DC-D3-AIK-RESTORE-ORDER",
    "DC-D2-AIK-2231-S3-PATROL",
}
LIFT_CASES = {
    CEDARFALL_LIFT_CASE,
    "DC-D3-PS23-LAURELSPUR-BWA-LIFT",
    "DC-D3-PS38-COPPERLEAF-BWA-LIFT",
}
PERSONAS = ("ic_01", "ops_dm_01", "log_01", "wtr_lead_01", "wtr_comp_01", "plan_etr_01", "audit_01")
SETTLE_S = 30.0
POLL_S = 0.5


class StepFailed(AssertionError):
    pass


def expect(condition: object, message: str) -> None:
    if not condition:
        raise StepFailed(message)


def until[T](read: Callable[[], T], done: Callable[[T], bool], timeout_s: float = SETTLE_S) -> T:
    """`read()` again until `done` holds or `timeout_s` passed; the last value either way (the caller's
    `expect` then names what is missing)."""
    deadline = time.monotonic() + timeout_s
    value = read()
    while not done(value) and time.monotonic() < deadline:
        time.sleep(POLL_S)
        value = read()
    return value


class Hooks(Protocol):
    def bookmark(self, story: Story, bm: Bookmark) -> None: ...

    def key_run(self, story: Story, bm: Bookmark, run: Run) -> None: ...


class NoHooks:
    def bookmark(self, story: Story, bm: Bookmark) -> None:
        return None

    def key_run(self, story: Story, bm: Bookmark, run: Run) -> None:
        return None


@dataclass
class StepResult:
    n: int
    name: str
    ok: bool
    seconds: float
    detail: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class Story:
    base: str
    password_for: Callable[[str], str]
    hooks: Hooks = field(default_factory=NoHooks)
    personas: dict[str, Persona] = field(default_factory=dict)
    runs: dict[str, Run] = field(default_factory=dict)
    ids: dict[str, str] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def p(self, user_id: str) -> Persona:
        if user_id not in self.personas:
            self.personas[user_id] = Persona(self.base, user_id, self.password_for(user_id))
        return self.personas[user_id]

    def relogin(self) -> None:
        """After an API restart: sessions may be gone, and runs resume on a new task (frames from seq 0)."""
        for persona in self.personas.values():
            persona.close()
        self.personas.clear()
        for run in self.runs.values():
            run.restarted = True

    def close(self) -> None:
        for persona in self.personas.values():
            persona.close()
        self.personas.clear()

    def key_run(self, bookmark_id: str, persona: str, name: str) -> Run:
        bm = bookmark(bookmark_id)
        if bm.run_graph is None or bm.run_module is None:
            raise StepFailed(f"bookmark {bm.id} has no key run")
        run = self.p(persona).run(bm.run_graph, bm.run_input, bm.run_module)
        self.runs[name] = run
        self.hooks.key_run(self, bm, run)
        return run

    def resume(self, persona: str, run: Run) -> list[dict[str, Any]]:
        return self.p(persona).resume(run)

    def proposals(self) -> dict[str, dict[str, Any]]:
        return {x["proposal_id"]: x for x in self.p("ops_dm_01").get_json("/api/proposals")}

    def card(self, proposal_id: str) -> dict[str, Any]:
        return dict(self.p("ops_dm_01").card(proposal_id).json())

    def rule_proposals(self, states: tuple[str, ...] = OPEN) -> dict[str, dict[str, Any]]:
        """The visible zone-rule proposals in `states`, by decision case (one per case at a time)."""
        return {
            x["decision_case_id"]: x
            for x in self.proposals().values()
            if x["proposal_id"].startswith(RULE_PREFIX) and x["state"] in states
        }


def _llm_briefs(run: Run, label: str) -> list[dict[str, Any]]:
    briefs = run.artifacts("brief")
    expect(briefs, f"{label}: no brief artifact")
    misses = [b.get("path") for b in briefs if b.get("path") != "llm"]
    expect(not misses, f"{label}: brief took {misses} (replay miss or LLM down)")
    return briefs


def sign_water(story: Story, case_id: str, at: str) -> str:
    """Seek to `at` and have water operations and compliance sign the open rule proposal of `case_id`."""
    expect(story.p("ops_dm_01").seek(at)["scenario_time"] == at, f"seek {at}")
    open_now = until(story.rule_proposals, lambda rules: case_id in rules)
    expect(case_id in open_now, f"{case_id} is not open at {at}: {sorted(open_now)}")
    pid = str(open_now[case_id]["proposal_id"])
    lead, compliance = WATER_SIGNERS
    first = story.p(lead).decide(pid)
    expect(first["remaining_functions"] == ["compliance"], f"{case_id} after water operations: {first}")
    second = story.p(compliance).decide(pid)
    expect(second["proposal_state"] == "approved", f"{case_id}: {second}")
    return pid


def _case_clock(story: Story, proposal_id: str) -> dict[str, Any]:
    case = story.card(proposal_id)["case"]
    return {
        "decision_case_id": case.get("decision_case_id"),
        "effective_decide_by_utc": case.get("clock", {}).get("effective_decide_by_utc"),
        "no_regret_verdict": case.get("no_regret_verdict"),
    }


def step_personas_and_clock(story: Story) -> dict[str, Any]:
    me = story.p("ic_01").get_json("/api/me")
    expect(me["function"] == "command" and me["demo_mode"] is True, f"/api/me: {me}")
    state = story.p("ops_dm_01").seek(BEFORE_N)
    expect(state["scenario_time"] == BEFORE_N, f"seek before N: {state}")
    evaluation = story.p("ops_dm_01").get_json("/api/models/a2-excl-helene/evaluation")
    expect(evaluation.get("report_name") and evaluation.get("provenance"), "outage model has no provenance")
    story.hooks.bookmark(story, bookmark("before-n"))
    return {"outage_model": evaluation.get("name"), "report": evaluation.get("report_name")}


def effective_decide_by(answer: dict[str, Any]) -> list[str]:
    """The effective decide-by times an answer shows, whatever evidence number its engine gave the clock."""
    return [v for k, v in (answer.get("slots_shown") or {}).items() if k.endswith(".effective_decide_by")]


def step_advisory_n(story: Story) -> dict[str, Any]:
    dm = story.p("ops_dm_01")
    expect(dm.seek(ADVISORY_N)["scenario_time"] == ADVISORY_N, "seek N")
    water = story.key_run("before-n", "ops_dm_01", "water_n")
    expect(water.last["type"] == "run_end" and water.status == "no_action", f"water N: {water.last}")
    expect(not water.of("approval_required"), "water N raised a proposal")
    ask = dm.run("copilot", {"question": PS17_QUESTION}, module="ask")
    said = [m for m in ask.artifacts("message") if m.get("role") == "assistant"]
    expect(said and said[0].get("path") == "llm", f"copilot at N: {said[:1]}")
    shown = effective_decide_by(said[0])
    expect("Sep 27, 00:45 ET" in shown, f"PS-17 decide-by at N shown as {shown!r}")
    brief = dm.get_json("/api/brief")
    models = {n["key"]: (n.get("provenance") or {}).get("model_id") for n in brief["numbers"]}
    expect(models.get("customers_out") == "a2-excl-helene", f"brief customers_out model {models}")
    story.hooks.bookmark(story, bookmark("at-n"))
    return {"water_n": water.status, "ps17_decide_by_at_n": shown, "brief_models": models}


def step_assess_n(story: Story) -> dict[str, Any]:
    run = story.key_run("at-n", "ops_dm_01", "assess_n")
    expect(run.status == "paused", f"assess N: {run.last}")
    briefs = _llm_briefs(run, "assess N")
    pending = run.of("approval_required")[0]["proposal_id"]
    story.ids["pending"] = pending
    signed = story.p("ic_01").decide(pending)
    expect(signed["proposal_state"] == "in_review", f"IC sign at N: {signed}")
    clock = _case_clock(story, pending)
    return {"brief_paths": [b.get("path") for b in briefs], "crew_case_at_n": clock}


def step_advisory_n1(story: Story) -> dict[str, Any]:
    dm = story.p("ops_dm_01")
    expect(dm.seek(ADVISORY_N1)["scenario_time"] == ADVISORY_N1, "seek N+1")
    pending = story.ids["pending"]
    revised = until(lambda: story.card(pending), lambda card: card["proposal_version"] >= 2)
    expect(
        revised["proposal_version"] == 2 and revised["state"] == "proposed",
        f"crew at N+1: {revised['state']}",
    )
    expect(revised["approvals"] == [], "the N signature is still counted")
    expect(revised.get("voided_approvals"), "no voided signature on the re-planned crew proposal")
    rules = until(story.rule_proposals, lambda found: set(found) == N1_RULE_CASES)
    expect(set(rules) == N1_RULE_CASES, f"rule proposals at N+1: {sorted(rules)}")
    expect(all(r["tier"] == "T2" for r in rules.values()), f"N+1 rule tiers {rules}")
    story.hooks.bookmark(story, bookmark("at-n1"))
    return {
        "crew_version": revised["proposal_version"],
        "voided": len(revised["voided_approvals"]),
        "rule_proposals": sorted(r["proposal_id"] for r in rules.values()),
    }


def step_water_n1(story: Story) -> dict[str, Any]:
    dm = story.p("ops_dm_01")
    water = story.key_run("at-n1", "ops_dm_01", "water_n1")
    expect(water.status == "paused", f"water N+1: {water.last}")
    briefs = _llm_briefs(water, "water N+1")
    asked = {p["proposal_id"]: p for p in water.of("approval_required")}
    queue = story.proposals()
    by_action = {queue[pid]["action_type"]: pid for pid in asked}
    expect({"cross_domain_priority", "boil_water_notice"} <= set(by_action), f"water N+1 asked {by_action}")
    priority, bwa = by_action["cross_domain_priority"], by_action["boil_water_notice"]
    story.ids.update(priority=priority, bwa=bwa)
    expect(queue[priority]["effective_decide_by_utc"] == "2024-09-27T03:29:00Z", "PS-17 is not at 03:29Z")
    card = story.card(priority)
    expect(card["case"]["no_regret_verdict"] == "decide_now", "PS-17 verdict is not decide_now")
    basis = card["case"]["clock"]["consequence_basis"]
    expect(basis["basis_id"] == "water_twin.zone_drain_critical_node", f"clock basis {basis}")
    waterfall = dm.get_json(f"/api/proposals/{priority}/clock")
    expect(waterfall["bound_by_case_id"] == "DC-D3-PS17-PRESSURE", f"waterfall {waterfall}")
    evidence = dm.get_json(f"/api/proposals/{priority}/evidence")
    models = sorted({e["model_version"] for e in evidence if e.get("model_version")})
    expect(models, "no evidence record names its model version")
    return {
        "brief_paths": [b.get("path") for b in briefs],
        "clock_basis": basis["basis_id"],
        "evidence_models": models,
    }


def step_sign(story: Story) -> dict[str, Any]:
    priority, bwa = story.ids["priority"], story.ids["bwa"]
    water = story.runs["water_n1"]
    first = story.p("ic_01").decide(priority)
    expect(first["remaining_functions"] == ["water_operations"], f"priority after command: {first}")
    second = story.p("wtr_lead_01").decide(priority)
    expect(second["proposal_state"] == "approved", f"priority: {second}")
    story.resume("ops_dm_01", water)
    expect(story.card(priority)["state"] == "executed", "priority not executed")
    story.p("wtr_lead_01").decide(bwa)
    expect(story.p("wtr_comp_01").decide(bwa)["proposal_state"] == "approved", "BWA not approved")
    tail = story.resume("ops_dm_01", water)
    expect(tail and tail[-1]["payload"].get("status") == "executed", f"water run end: {tail[-1:]}")
    story.hooks.bookmark(story, bookmark("signed"))
    return {"priority": "executed", "bwa": story.card(bwa)["state"]}


def step_break_glass(story: Story) -> dict[str, Any]:
    assess = story.key_run("signed", "ops_dm_01", "assess_n1")
    expect(assess.status == "paused", f"assess N+1: {assess.last}")
    _llm_briefs(assess, "assess N+1")
    crew = assess.of("approval_required")[0]
    expect(crew["tier"] == "T3" and crew["functions_required"] == ["command", "logistics"], f"crew {crew}")
    story.ids["crew"] = crew["proposal_id"]
    bg = story.p("ic_01").write_on_card(crew["proposal_id"], "break-glass", {"reason": BREAK_GLASS_REASON})
    expect(bg.status_code == 200 and bg.json()["state"] == "approved", f"break-glass: {bg.status_code}")
    log = story.p("log_01")
    card = log.card(crew["proposal_id"])
    cosign = log.post(
        f"/api/proposals/{crew['proposal_id']}/cosign", {}, {"If-Match": card.headers.get("etag", "")}
    )
    expect(cosign.status_code == 200 and cosign.json()["cosigned_by"] == "log_01", "co-sign failed")
    tail = story.resume("ops_dm_01", assess)
    expect(tail and tail[-1]["payload"].get("status") == "executed", f"assess N+1 end: {tail[-1:]}")
    return {"crew": "executed", "break_glass_by": "ic_01", "cosigned_by": "log_01"}


def step_morning_after(story: Story) -> dict[str, Any]:
    expect(story.p("ops_dm_01").seek(MORNING_AFTER)["scenario_time"] == MORNING_AFTER, "seek morning after")
    rules = until(story.rule_proposals, lambda found: set(found) == MORNING_RULE_CASES)
    expect(set(rules) == MORNING_RULE_CASES, f"rule proposals at the morning after: {sorted(rules)}")
    tanker = rules[TANKER_CASE]
    expect(tanker["effective_decide_by_utc"] == "2024-09-27T14:05:00Z", f"tanker clock {tanker}")
    story.hooks.bookmark(story, bookmark("morning-after"))
    signed = story.p("log_01").decide(tanker["proposal_id"])
    expect(signed["proposal_state"] == "approved", f"tanker by logistics: {signed}")
    notice = rules[LAURELSPUR_CASE]["proposal_id"]
    first = story.p("wtr_lead_01").decide(notice)
    expect(first["remaining_functions"] == ["compliance"], f"Laurelspur after water operations: {first}")
    second = story.p("wtr_comp_01").decide(notice)
    expect(second["proposal_state"] == "approved", f"Laurelspur notice: {second}")
    story.ids.update(tanker=tanker["proposal_id"], laurelspur=notice)
    return {"rule_cases": sorted(rules), "tanker": "approved", "laurelspur": "approved"}


def step_copperleaf_notice(story: Story) -> dict[str, Any]:
    pid = sign_water(story, COPPERLEAF_CASE, COPPERLEAF_SIGNED)
    story.ids["copperleaf"] = pid
    return {"copperleaf": "approved", "signed_at": COPPERLEAF_SIGNED}


def step_notices_lifted(story: Story) -> dict[str, Any]:
    story.ids["deerwater"] = sign_water(story, DEERWATER_CASE, DEERWATER_SIGNED)
    story.ids["cedarfall_lift"] = sign_water(story, CEDARFALL_LIFT_CASE, CEDARFALL_LIFTED)
    state = story.p("ops_dm_01").seek(NOTICES_LIFTED)
    expect(state["scenario_time"] == NOTICES_LIFTED, "seek notices lifted")
    waiting = LIFT_CASES - {CEDARFALL_LIFT_CASE}
    rules = until(
        story.rule_proposals,
        lambda found: (
            {c for c in found if c.endswith("-BWA-LIFT")} == waiting and DEERWATER_CASE not in found
        ),
    )
    lifts = {c for c in rules if c.endswith("-BWA-LIFT")}
    expect(lifts == LIFT_CASES - {CEDARFALL_LIFT_CASE}, f"lift proposals at 30 Sep: {sorted(lifts)}")
    expect(DEERWATER_CASE not in rules, "the Deerwater notice is still open")
    expect(
        all(rules[c]["functions_required"] == ["water_operations", "compliance"] for c in lifts),
        f"lift signers {[rules[c]['functions_required'] for c in lifts]}",
    )
    late = [c for c in lifts if rules[c]["effective_decide_by_utc"] <= NOTICES_LIFTED]
    expect(not late, f"lifts already past their deadline at 30 Sep: {late}")
    story.hooks.bookmark(story, bookmark("notices-lifted"))
    return {"lifts": sorted(lifts), "lifted": [CEDARFALL_LIFT_CASE], "deerwater": "approved"}


def step_etr(story: Story) -> dict[str, Any]:
    dm = story.p("ops_dm_01")
    expect(dm.seek(ETR_TIME)["scenario_time"] == ETR_TIME, "seek ETR time")
    pending = until(lambda: story.card(story.ids["pending"]), lambda card: card["state"] == "expired")
    expect(pending["state"] == "expired", "the voided N crew proposal is open")
    etr = story.p("plan_etr_01").run("etr", {}, "brief")
    story.runs["etr"] = etr
    expect(etr.status == "paused", f"etr: {etr.last}")
    etr_pid = etr.of("approval_required")[0]["proposal_id"]
    story.ids["etr"] = etr_pid
    story.p("ic_01").decide(etr_pid)
    expect(dm.decide(etr_pid)["proposal_state"] == "approved", "ETR not approved")
    tail = story.resume("plan_etr_01", etr)
    expect(tail and tail[-1]["payload"].get("status") == "executed", f"etr end: {tail[-1:]}")
    events = story.p("audit_01").get_json("/api/audit", params={"subject": etr_pid})
    kinds = sorted({e["kind"] for e in events})
    expect("etr_published" in kinds, f"no etr_published audit event for {etr_pid}: {kinds}")
    story.hooks.bookmark(story, bookmark("etr-published"))
    ask = story.key_run("etr-published", "ops_dm_01", "ask_etr")
    said = [m for m in ask.artifacts("message") if m.get("role") == "assistant"]
    expect(said and said[0].get("path") == "llm" and said[0].get("citations"), f"copilot ETR: {said[:1]}")
    cited = said[0]["citations"]
    expect(any(c.startswith("DOM 14.206") for c in cited), f"ETR answer cites {cited}")
    return {"etr_proposal": etr_pid, "audit_events": kinds, "copilot_citations": cited}


def step_after_action(story: Story) -> dict[str, Any]:
    expect(story.p("ops_dm_01").seek(REVIEW_TIME)["scenario_time"] == REVIEW_TIME, "seek review time")
    story.hooks.bookmark(story, bookmark("after-action"))
    review = story.key_run("after-action", "ic_01", "after_action")
    expect(review.status == "draft_ready", f"after-action: {review.last}")
    briefs = _llm_briefs(review, "after-action")
    evidence = {i["kind"]: i["values"] for i in review.of("artifact")[0]["items"]}
    expect(evidence["break_glass"]["uses"] == "1", f"break-glass uses {evidence.get('break_glass')}")
    expect(review.artifacts("sc_103_314_markdown"), "no SC 103-314 draft")
    return {"brief_paths": [b.get("path") for b in briefs], "clock_outcomes": evidence.get("clock_outcomes")}


def step_audit(story: Story) -> dict[str, Any]:
    verify = story.p("audit_01").post("/api/audit/verify", {})
    expect(verify.status_code == 200, f"audit verify HTTP {verify.status_code}")
    body = verify.json()
    expect(body["ok"] is True and body["first_bad_seq"] is None, f"audit verify {body}")
    return {"checked_to_seq": body.get("checked_to_seq"), "notary": body.get("notary")}


STEPS: tuple[tuple[str, Callable[[Story], dict[str, Any]]], ...] = (
    ("personas and clock before advisory N", step_personas_and_clock),
    ("advisory N: water continuity raises nothing", step_advisory_n),
    ("advisory N: assess, command signs the crew", step_assess_n),
    ("advisory N+1: reorder, signature voided", step_advisory_n1),
    ("advisory N+1: water continuity proposes PS-17", step_water_n1),
    ("PS-17 priority and BWA signed and executed", step_sign),
    ("crew by break-glass, co-signed", step_break_glass),
    ("morning after: tanker and Laurelspur notice signed", step_morning_after),
    ("night 2: Copperleaf notice signed on time", step_copperleaf_notice),
    ("ETR published; copilot on revising it", step_etr),
    ("notices lifted: Deerwater signed, Cedarfall lifted, two lifts waiting", step_notices_lifted),
    ("after-action draft", step_after_action),
    ("audit chain verifies", step_audit),
)


def run_story(story: Story, stop_on_failure: bool = True) -> list[StepResult]:
    results: list[StepResult] = []
    for n, (name, fn) in enumerate(STEPS, start=1):
        started = time.perf_counter()
        try:
            prov = fn(story)
            results.append(StepResult(n, name, True, time.perf_counter() - started, provenance=prov))
        except (StepFailed, DemoError, KeyError, IndexError) as exc:
            detail = f"{type(exc).__name__}: {exc}"[:500]
            results.append(StepResult(n, name, False, time.perf_counter() - started, detail))
            if stop_on_failure:
                break
    return results
