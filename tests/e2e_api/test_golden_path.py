"""Golden path through the API, no UI: "PS-17: one pump station, one hospital, one clock" (PLAN SC-1..SC-5,
SC-7 drills). A fresh scratch database is seeded the way the runbook does it (`docs/ops/golden-path-api.md`),
the API runs as a uvicorn subprocess on the runtime role with DEMO_MODE=1 and a replay-only gateway (no key,
no live call), and every step is an operator's HTTP call as a seeded persona.

Out-of-band stand-ins (no HTTP surface yet): the PS-17 queue store at an
advisory (`sgw clocks compute -d`), the webhook worker pass (`sgw integrations worker --once`) and the
commitment watch over the ledger (`sgw commitments replay-ps17` does the same for its seeded story)."""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest

from sgw.demo.story import effective_decide_by
from sgw.ingest.testing import scratch_database, server_available

from . import golden_kit as gk

pytestmark = pytest.mark.slow

ADVISORY_N = "2024-09-26T09:05:00Z"
ADVISORY_N1 = "2024-09-26T15:05:00Z"
MORNING_AFTER = "2024-09-27T12:00:00Z"
ETR_TIME = "2024-09-28T18:00:00Z"
REVIEW_TIME = "2024-10-06T02:00:00Z"
COPILOT_TIME = "2024-09-28T18:00:00Z"
PS17_QUESTION = "What does advisory N do to PS-17's decide-by, and is it act now or wait?"
COPILOT_QUESTION = "When do I have to revise a global ETR that is already out?"
NO_OPA = "no OPA: set SGW_TEST_OPA_URL or start docker"
BREAK_GLASS_REASON = "Logistics chief unreachable; storm onset forces crew staging now."


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[gk.Stack]:
    reason = server_available()
    if reason:
        pytest.skip(reason)  # sgw-allow-skip: needs Postgres (SGW_TEST_DATABASE_URL)
    workdir = tmp_path_factory.mktemp("golden")
    password = "golden-" + secrets.token_hex(12)
    with gk.opa() as opa_url:
        if opa_url is None:
            pytest.skip(NO_OPA)  # sgw-allow-skip: needs OPA (docker or SGW_TEST_OPA_URL)
        with scratch_database("golden") as db:
            gk.seed_world(db.admin_url, password)
            s = gk.Stack(db.runtime_url, db.admin_url, opa_url, password, workdir)
            try:
                s.start_gateway()
                s.start_api()
                yield s
            finally:
                s.close()


def _proposals(p: gk.Persona) -> dict[str, dict[str, Any]]:
    r = p.get("/api/proposals")
    assert r.status_code == 200, r.text
    return {x["proposal_id"]: x for x in r.json()}


def _ledger_types(admin_url: str, after: int) -> list[str]:
    with psycopg.connect(admin_url) as conn:
        rows = conn.execute("SELECT type FROM event WHERE ledger_seq > %s ORDER BY ledger_seq", (after,))
        return [r[0] for r in rows.fetchall()]


def _cases(admin_url: str) -> dict[str, tuple[str, str]]:
    with psycopg.connect(admin_url) as conn:
        rows = conn.execute(
            "SELECT decision_case_id, to_char(effective_decide_by_utc AT TIME ZONE 'UTC',"
            ' \'YYYY-MM-DD"T"HH24:MI:SS"Z"\'), no_regret_verdict::text FROM decision_case'
        ).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def _head(admin_url: str) -> int:
    with psycopg.connect(admin_url) as conn:
        row = conn.execute("SELECT coalesce(max(ledger_seq), 0) FROM event").fetchone()
        return int(row[0]) if row else 0


def _token_audit(p: gk.Persona, proposal_id: str) -> list[str]:
    r = p.get("/api/audit")
    assert r.status_code == 200, r.text
    return [e["kind"] for e in r.json() if e["subject"] == proposal_id and "token" in e["kind"]]


def _webhook_pass(stack: gk.Stack, ca: Path) -> dict[str, int]:
    from sgw.integrations.keys import IntegrationKeys, decode_key
    from sgw.integrations.urls import UrlPolicy
    from sgw.integrations.worker import WebhookRunner, tls_context

    runner = WebhookRunner(
        stack.runtime_url,
        keys=IntegrationKeys.from_master(decode_key(stack.integration_key)),
        url_policy=UrlPolicy(allow_hosts=frozenset({stack.hook_host})),
        tls=tls_context(str(ca)),
    )
    return dict(asyncio.run(runner.run(once=True)))


def _commitment_watch(admin_url: str, case_id: str) -> Any:
    from sgw.approval.ledger import OutboxSink as ApprovalOutbox
    from sgw.approval.policy import ReferencePolicy
    from sgw.approval.service import ApprovalService
    from sgw.models.commitments import seed
    from sgw.models.commitments.service import CommitmentWatch, OutboxSink, replay

    at: list[datetime] = []
    approvals = ApprovalService(
        ReferencePolicy(), scenario_clock=lambda: at[-1], token_clock=lambda: at[-1], ledger=ApprovalOutbox()
    )
    with psycopg.connect(admin_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT event_id::text, type, event_time, payload, ledger_seq, dedup_key FROM event"
            " WHERE type = 'DecisionApproved' AND payload->>'decision_case_id' = %s",
            (case_id,),
        ).fetchall()
        assert rows, f"no DecisionApproved for {case_id} in the ledger"
        approved = [
            {
                "event_id": r[0],
                "type": r[1],
                "event_time": r[2].isoformat(),
                "payload": r[3],
                "ledger_seq": r[4],
                "dedup_key": r[5],
            }
            for r in rows
        ]
        since = min(r[2] for r in rows).isoformat()[:19]
        micro = [e for e in seed.micro_events() if e["event_time"] >= since]
        return replay(
            conn, CommitmentWatch(approvals, ledger=OutboxSink()), approved + micro, set_time=at.append
        )


def test_golden_path_ps17_one_pump_station_one_hospital_one_clock(stack: gk.Stack, tmp_path: Path) -> None:
    sys.path.insert(0, str(gk.REPO / "tests" / "integration" / "integrations_webhooks"))
    from tls_testkit import make_pems

    def persona(user: str) -> gk.Persona:
        return gk.Persona(stack.base, user, stack.password)

    ic, dm, log = persona("ic_01"), persona("ops_dm_01"), persona("log_01")
    wlead, wcomp = persona("wtr_lead_01"), persona("wtr_comp_01")
    etr_lead, auditor, admin = persona("plan_etr_01"), persona("audit_01"), persona("admin_01")

    # 1. personas and the scenario clock
    me = ic.get("/api/me").json()
    assert me["function"] == "command" and me["demo_mode"] is True
    assert dm.seek(ADVISORY_N)["scenario_time"] == ADVISORY_N

    # 2. integration token + webhook subscription first, so later DecisionApproved events fan out
    expires = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    created = admin.post(
        "/api/admin/tokens",
        {
            "name": "Golden path bridge",
            "scopes": ["decisions:read", "commitments:read", "webhooks:manage"],
            "expires_at": expires,
        },
    )
    assert created.status_code == 201, created.text
    bearer = {"Authorization": f"Bearer {created.json()['token']}"}
    sub = httpx.post(
        f"{stack.base}/v1/webhooks",
        json={
            "url": stack.hook_url,
            "event_types": ["DecisionApproved", "CommitmentCreated", "CommitmentDrifted"],
        },
        headers=bearer,
    )
    assert sub.status_code == 201, sub.text
    (tmp_path / "tls").mkdir()
    pems = make_pems(tmp_path / "tls")
    received = tmp_path / "received.jsonl"
    stack.start_consumer(sub.headers["SGW-Webhook-Secret"], pems.ca, pems.cert, pems.key, received)

    # 3. advisory N: the stored queue holds PS-17 at 04:45Z, wait; water continuity raises nothing
    n_queue = {c: v for c, v in _cases(stack.admin_url).items()}
    assert n_queue["DC-D3-PS17-POWER"] == ("2024-09-27T04:45:00Z", "wait_for_next_advisory"), n_queue
    water_n = dm.run("water_continuity", {"advisory": "N"}, module="water")
    assert water_n.last["type"] == "run_end" and water_n.last["payload"]["status"] == "no_action", (
        water_n.last
    )
    assert not water_n.of("approval_required")
    ask_n = dm.run("copilot", {"question": PS17_QUESTION}, module="ask")
    said = [m for m in ask_n.artifacts("message") if m.get("role") == "assistant"][0]
    assert said["path"] == "llm", said
    assert "Sep 27, 00:45 ET" in effective_decide_by(said), said

    # 3a. assess at N: the T3 crew proposal, signed by command only (pending)
    assess_n = dm.run("assess", {"advisory": "N"}, module="decisions")
    assert assess_n.last["type"] == "run_paused", assess_n.last
    assert all(b["path"] == "llm" for b in assess_n.artifacts("brief")), "replay miss on the assess N brief"
    pending = assess_n.of("approval_required")[0]["proposal_id"]
    signed = ic.decide(pending)
    assert signed.status_code == 200 and signed.json()["proposal_state"] == "in_review", signed.text

    # 4. advisory N+1: the clock command re-plans the queue (PS-17 effective 03:29Z, decide_now) and the
    # pending crew signature is voided by a new proposal version (SC-3)
    head = _head(stack.admin_url)
    dm.seek(ADVISORY_N1)
    n1_queue = _cases(stack.admin_url)
    assert n1_queue["DC-D3-PS17-POWER"] == ("2024-09-27T03:29:00Z", "decide_now"), n1_queue
    revised = dm.card(pending).json()
    assert revised["proposal_version"] == 2 and revised["state"] == "proposed", revised
    assert revised["approvals"] == [], revised["approvals"]
    assert revised["params"]["decide_by_advisory"] == "N+1"
    assert "ProposalUpdated" in _ledger_types(stack.admin_url, head)
    water = dm.run("water_continuity", {"advisory": "N+1"}, module="water")
    assert water.last["type"] == "run_paused", water.last
    asked = {p["proposal_id"]: p for p in water.of("approval_required")}
    by_action = {_proposals(dm)[pid]["action_type"]: pid for pid in asked}
    priority, bwa = by_action["cross_domain_priority"], by_action["boil_water_notice"]
    assert asked[priority]["functions_required"] == ["command", "water_operations"]
    assert asked[bwa]["functions_required"] == ["water_operations", "compliance"]
    assert all(b["path"] == "llm" for b in water.artifacts("brief")), "replay miss on the water brief"

    # 5. decision queue: PS-17 with its clock, critical path and verdict; the waterfall cites the twin
    queue = _proposals(dm)
    assert queue[priority]["effective_decide_by_utc"] == "2024-09-27T03:29:00Z"
    assert queue[priority]["on_critical_path"] is True
    card = dm.card(priority).json()
    assert card["case"]["no_regret_verdict"] == "decide_now"
    assert card["case"]["clock"]["consequence_basis"]["basis_id"] == "water_twin.zone_drain_critical_node"
    waterfall = dm.get(f"/api/proposals/{priority}/clock").json()
    assert waterfall["action_lead_time_min"] == 150
    assert waterfall["decide_by_utc"] == "2024-09-27T03:59:00Z"
    assert waterfall["effective_decide_by_utc"] == "2024-09-27T03:29:00Z"
    assert waterfall["bound_by_case_id"] == "DC-D3-PS17-PRESSURE", waterfall

    # 6. assess at N+1 pauses on the T3 crew proposal (command + logistics)
    assess = dm.run("assess", {"advisory": "N+1"}, module="decisions")
    assert assess.last["type"] == "run_paused", assess.last
    crew = assess.of("approval_required")[0]
    assert all(b["path"] == "llm" for b in assess.artifacts("brief")), "replay miss on the assess N+1 brief"
    assert crew["tier"] == "T3" and crew["functions_required"] == ["command", "logistics"]

    # 7. T3 priority: command + water_operations sign; the run executes and burns the execution token
    head = _head(stack.admin_url)
    first = ic.decide(priority)
    assert first.status_code == 200 and first.json()["remaining_functions"] == ["water_operations"], (
        first.text
    )
    second = wlead.decide(priority)
    assert second.status_code == 200 and second.json()["proposal_state"] == "approved", second.text
    dm.resume(water)
    assert dm.card(priority).json()["state"] == "executed"
    assert _token_audit(auditor, priority)[-1] == "execution_token_burned"
    assert "DecisionApproved" in _ledger_types(stack.admin_url, head)

    # 8. BWA: water_operations + compliance; the run ends executed
    assert wlead.decide(bwa).status_code == 200
    assert wcomp.decide(bwa).json()["proposal_state"] == "approved"
    tail = dm.resume(water)
    assert tail[-1]["type"] == "run_end" and tail[-1]["payload"]["status"] == "executed", tail[-1]
    assert dm.card(bwa).json()["state"] == "executed"

    # 9. break-glass by the IC alone, with a reason; the logistics co-sign task; the run executes
    c = ic.card(crew["proposal_id"])
    bg = ic.post(
        f"/api/proposals/{crew['proposal_id']}/break-glass",
        {
            "proposal_version": c.json()["proposal_version"],
            "action_hash": c.json()["action_hash"],
            "reason": BREAK_GLASS_REASON,
        },
        headers={"If-Match": c.headers.get("etag", "")},
    )
    assert bg.status_code == 200 and bg.json()["state"] == "approved", bg.text
    task = log.card(crew["proposal_id"]).json()["break_glass"]
    assert task["ic_id"] == "ic_01" and task["cosigned_by"] is None and task["flagged_for_after_action"]
    c = log.card(crew["proposal_id"])
    cosign = log.post(
        f"/api/proposals/{crew['proposal_id']}/cosign", {}, {"If-Match": c.headers.get("etag", "")}
    )
    assert cosign.status_code == 200 and cosign.json()["cosigned_by"] == "log_01", cosign.text
    tail = dm.resume(assess)
    assert tail[-1]["payload"]["status"] == "executed", tail[-1]

    # 9b. morning after landfall (SGW_ZONE_RULES): rules raised the observed hospital tanker (T2, logistics
    # signs alone, decide by 14:05Z) and the Laurelspur advisory (T3, water operations + compliance)
    dm.seek(MORNING_AFTER)
    rules = {
        x["decision_case_id"]: x
        for x in _proposals(dm).values()
        if x["proposal_id"].startswith("PRP-ZR-") and x["state"] in ("proposed", "in_review", "draft")
    }
    tanker, laurelspur = rules["DC-D3-HSP-TALLOWBRANCH-TANKER"], rules["DC-D3-PS23-LAURELSPUR-BWA"]
    assert tanker["effective_decide_by_utc"] == "2024-09-27T14:05:00Z" and tanker["tier"] == "T2", tanker
    assert tanker["proposed_by"]["user_id"] == "system:rule:zone_hospital_tanker"
    signed = log.decide(tanker["proposal_id"])
    assert signed.status_code == 200 and signed.json()["proposal_state"] == "approved", signed.text
    assert wlead.decide(laurelspur["proposal_id"]).json()["remaining_functions"] == ["compliance"]
    assert wcomp.decide(laurelspur["proposal_id"]).json()["proposal_state"] == "approved"

    # 10. ETR: the ETR specialist runs `etr`, command + operations approve, EtrPublished reaches the ledger
    dm.seek(ETR_TIME)
    stale = [x for x in _proposals(dm).values() if x["state"] in ("proposed", "in_review")]
    assert not [x for x in stale if x["expires_at"] and x["expires_at"] < ETR_TIME], stale
    assert dm.card(pending).json()["state"] == "expired"
    assert pending not in _proposals(dm), "the queue lists only the latest crew proposal of the case"
    head = _head(stack.admin_url)
    etr = etr_lead.run("etr", {}, module="brief")
    assert etr.last["type"] == "run_paused", etr.last
    etr_pid = etr.of("approval_required")[0]["proposal_id"]
    assert ic.decide(etr_pid).status_code == 200
    assert dm.decide(etr_pid).json()["proposal_state"] == "approved"
    tail = etr_lead.resume(etr)
    assert tail[-1]["payload"]["status"] == "executed", tail[-1]
    assert "EtrPublished" in _ledger_types(stack.admin_url, head)

    # 11. sitrep with the LLM down (FAULT_LLM_DOWN=1 -> M2 template, same slots)
    stack.restart_api({"FAULT_LLM_DOWN": "1"})
    dm = persona("ops_dm_01")
    deadline = time.monotonic() + 20
    while dm.get("/api/control/mode").json()["degraded_mode"] != "M2" and time.monotonic() < deadline:
        time.sleep(0.5)
    assert dm.get("/api/control/mode").json()["degraded_mode"] == "M2"
    sitrep = dm.run("sitrep", {}, module="brief")
    draft = sitrep.artifacts("sitrep_draft")[0]
    assert draft["path"] == "m2" and "Template text" in draft["rendered"], draft
    assert sitrep.last["payload"]["status"] == "draft_ready"
    stack.restart_api()
    dm, ic, auditor = persona("ops_dm_01"), persona("ic_01"), persona("audit_01")
    deadline = time.monotonic() + 20
    while dm.get("/api/control/mode").json()["degraded_mode"] != "M0" and time.monotonic() < deadline:
        time.sleep(0.5)
    assert dm.get("/api/control/mode").json()["degraded_mode"] == "M0"

    # 12. after-action: clocks met/missed, the break-glass use, the SC 103-314 draft
    dm.seek(REVIEW_TIME)
    review = ic.run("after_action", {}, module="after_action")
    assert review.last["payload"]["status"] == "draft_ready", review.last
    assert all(b["path"] == "llm" for b in review.artifacts("brief")), "replay miss on the after-action brief"
    evidence = {i["kind"]: i["values"] for i in review.of("artifact")[0]["items"]}
    assert evidence["break_glass"]["uses"] == "1" and evidence["break_glass"]["cosigned_on_time"] == "1"
    assert int(evidence["clock_outcomes"]["met"]) >= 1
    assert review.artifacts("sc_103_314_markdown"), "no SC 103-314 draft"

    # 13. audit chain verifies
    verify = auditor.post("/api/audit/verify", {})
    assert (
        verify.status_code == 200 and verify.json()["ok"] is True and verify.json()["first_bad_seq"] is None
    )

    # 14. kill switch K1 by the IC; approvals stop; restore needs command + compliance
    wcomp = persona("wtr_comp_01")
    k1 = ic.post("/api/control/kill", {"kill_level": "K1", "reason": "Golden-path drill: stop execution"})
    assert k1.status_code == 200 and k1.json()["kill_level"] == "K1", k1.text
    caps = ic.get("/api/control/capabilities").json()["capabilities"]
    assert caps["approve_and_execute"] is False
    half = ic.post("/api/control/kill", {"kill_level": "K0", "reason": "Drill over, restore"})
    assert half.status_code == 202 and "awaiting=compliance" in half.headers.get("x-sgw-restore", "")
    again = ic.post("/api/control/kill", {"kill_level": "K0", "reason": "Drill over, restore"})
    assert again.status_code == 409
    done = wcomp.post("/api/control/kill", {"kill_level": "K0", "reason": "Compliance co-signs restore"})
    assert done.status_code == 200 and done.json()["kill_level"] == "K0", done.text

    # 15. /v1: decisions readable with the token; the example consumer verified DecisionApproved
    decisions = httpx.get(f"{stack.base}/v1/decisions", headers=bearer)
    assert decisions.status_code == 200
    states = {d["decision_case_id"]: d["state"] for d in decisions.json()}
    assert states["DC-D3-PS17-POWER"] == "executed"
    totals = _webhook_pass(stack, pems.ca)
    assert totals.get("delivered", 0) >= 3, totals
    got = [json.loads(line)["event"] for line in received.read_text(encoding="utf-8").splitlines()]
    approved = {e["data"]["proposal_id"] for e in got if e["type"] == "DecisionApproved"}
    assert {priority, bwa, etr_pid} <= approved, approved

    # 16. copilot: a procedure question answered with citations
    dm.seek(COPILOT_TIME)
    ask = dm.run("copilot", {"question": COPILOT_QUESTION}, module="ask")
    answer = [m for m in ask.artifacts("message") if m.get("role") == "assistant"][0]
    assert answer["path"] == "llm" and answer["citations"], answer
    assert any(c.startswith("DOM 14.206") for c in answer["citations"]), answer["citations"]
    messages = dm.get(f"/api/threads/{ask.thread_id}/messages").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]

    # 17. commitments: the approved PS-17 priority becomes a commitment that drifts in the replay
    result = _commitment_watch(stack.admin_url, "DC-D3-PS17-POWER")
    assert result.created and any(d["state"] == "drifted" for d in result.drifted), result
    commitments = httpx.get(f"{stack.base}/v1/commitments", headers=bearer).json()
    ps17 = [x for x in commitments if x["decision_case_id"] == "DC-D3-PS17-POWER"]
    assert ps17 and ps17[0]["state"] == "drifted", commitments
    totals = _webhook_pass(stack, pems.ca)
    got = [json.loads(line)["event"]["type"] for line in received.read_text(encoding="utf-8").splitlines()]
    assert "CommitmentCreated" in got and "CommitmentDrifted" in got, got
