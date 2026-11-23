"""Over HTTP with the real app lifespan on a scratch database seeded like `sgw seed` plus the WP-17
story estimates: the ETR read routes, the planner's D4 draft through the run routes, the two signatures by
command and operations, the publish wake-up, the after-action drafts, permissions and audit records."""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from tests.unit.agent.agent_testkit import DownLlm
from tests.unit.agent.graphs.reports_testkit import ESTIMATES

from sgw.agent.nodes.run_store import PostgresRunStore
from sgw.api.app import app_routes, create_app
from sgw.api.readmodels import etr as etr_rm
from sgw.api.routers import runs
from sgw.api.settings import ApiSettings
from sgw.api.users import seed_users
from sgw.approval import testkit as tk
from sgw.approval.deps import OPA_ENV
from sgw.common import numbers
from sgw.contracts.api_models import AfterActionDraft, EtrArea, EtrView, contract_routes
from sgw.models.restoration import publish
from sgw.reports import sources

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
NO_OPA = "no OPA: set SGW_TEST_OPA_URL or start docker"
PASSWORD = "cb3-" + secrets.token_hex(12)
BEFORE = "2024-09-27T12:00:00Z"
ETR_TIME = "2024-09-28T18:00:00Z"
REVIEW = "2024-10-06T02:00:00Z"
NOTICES_LIFTED = "2024-09-30T12:00:00Z"
ROUTES = {
    ("GET", "/api/etr"),
    ("GET", "/api/etr/areas/{region_id}"),
    ("GET", "/api/after-action/drafts"),
    ("POST", "/api/after-action/drafts"),
}


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    from sgw.approval.seed import run_seed

    with tk.scratch_database("sgw_cb3_etr_t") as url:
        run_seed(url, use_default_ledger=False)
        seed_users(url, PASSWORD)
        with psycopg.connect(url, autocommit=True) as conn:
            publish.write(conn, sources.load_estimates(ESTIMATES), "cb3-test")
        yield url


def _offline(factory: Any) -> Any:
    def build(request: Any) -> Any:
        return replace(factory(request), llm=DownLlm())

    return build


@pytest.fixture(scope="module")
def opa_url() -> Iterator[str]:
    from sgw.approval.breakglass_policy import OpaGovernance
    from sgw.approval.policy import OpaPolicy

    with tk.opa_server() as url:
        if url is None:
            pytest.skip(NO_OPA)  # sgw-allow-skip: signs through the OPA approval policy
        for policy in (OpaPolicy(url, allow_load=True), OpaGovernance(url, allow_load=True)):
            policy.load()
            policy.close()
        before = os.environ.get(OPA_ENV)
        os.environ[OPA_ENV] = url
        yield url
        if before is None:
            os.environ.pop(OPA_ENV, None)
        else:
            os.environ[OPA_ENV] = before


@pytest.fixture(scope="module")
def client(db_url: str, opa_url: str) -> Iterator[TestClient]:
    settings = ApiSettings(
        database_url=db_url, demo_mode=True, cookie_secure=False, login_ip_burst=1000, login_user_burst=1000
    )
    app = create_app(settings)
    with TestClient(app) as c:
        app.state.agent_runtime = runs.AgentRuntime(
            deps_factory=_offline(runs.default_deps),
            graph_deps={g: _offline(runs.report_deps) for g in runs.REPORT_GRAPHS},
            store=PostgresRunStore(app.state.sgw.pool),
            checkpointer=InMemorySaver(),
        )
        yield c


def login(c: TestClient, user_id: str) -> dict[str, str]:
    c.cookies.clear()
    r = c.post("/api/auth/login", json={"user_id": user_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": c.cookies["sgw_csrf"]}


def seek(c: TestClient, at: str) -> None:
    csrf = login(c, "ic_01")
    assert c.post("/api/scenario", json={"action": "pause"}, headers=csrf).status_code == 200
    r = c.post("/api/scenario", json={"action": "seek", "scenario_time": at}, headers=csrf)
    assert r.status_code == 200, r.text


def etr_view(c: TestClient, user_id: str) -> EtrView:
    login(c, user_id)
    r = c.get("/api/etr")
    assert r.status_code == 200, r.text
    return EtrView.model_validate(r.json())


def wait_run(db_url: str, run_id: str, until: set[str], timeout_s: float = 60) -> str:
    deadline = time.monotonic() + timeout_s
    status = ""
    while time.monotonic() < deadline:
        with psycopg.connect(db_url, autocommit=True) as conn:
            row = conn.execute("SELECT status FROM agent_run WHERE run_id = %s", (run_id,)).fetchone()
        status = row[0] if row else ""
        if status in until:
            return status
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} still {status!r}")


def sign(c: TestClient, user_id: str, proposal_id: str) -> None:
    csrf = login(c, user_id)
    card = c.get(f"/api/proposals/{proposal_id}")
    assert card.status_code == 200, card.text
    body = card.json()
    r = c.post(
        f"/api/proposals/{proposal_id}/approvals",
        json={
            "decision": "approve",
            "proposal_version": body["proposal_version"],
            "action_hash": body["action_hash"],
        },
        headers={**csrf, "If-Match": card.headers.get("etag", "")},
    )
    assert r.status_code == 200, r.text


def audit_kinds(db_url: str, subject: str) -> list[str]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT kind FROM audit_event WHERE subject = %s ORDER BY seq", (subject,)
        ).fetchall()
    return [r[0] for r in rows]


def pub_case(db_url: str, proposal_id: str) -> str:
    with psycopg.connect(db_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT decision_case_id FROM proposal WHERE proposal_id = %s", (proposal_id,)
        ).fetchone()
    assert row is not None
    return str(row[0])


def test_routes_are_mounted_and_in_the_contract() -> None:
    app = create_app(ApiSettings(database_url="postgresql://unused/unused", demo_mode=True))
    assert app_routes(app) >= ROUTES
    assert contract_routes() >= ROUTES


def test_reads_need_a_session(client: TestClient) -> None:
    client.cookies.clear()
    for path in ("/api/etr", "/api/etr/areas/GLOBAL", "/api/after-action/drafts"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/after-action/drafts").status_code == 401


def test_before_the_first_issue_nothing_is_shown_but_the_issue_time(client: TestClient) -> None:
    seek(client, BEFORE)
    doc = etr_view(client, "plan_etr_01")
    assert doc.whole is None and doc.areas == [] and doc.issued_at is None
    assert doc.next_issue_utc == datetime(2024, 9, 28, 17, 30, tzinfo=UTC)
    assert doc.can_draft is False and doc.can_publish is False
    assert client.get("/api/etr/areas/GLOBAL").status_code == 404


def test_estimates_are_the_snapshot_values_with_area_names(client: TestClient) -> None:
    seek(client, ETR_TIME)
    doc = etr_view(client, "exec_01")
    stored = {e.region_id: e for e in sources.load_estimates(ESTIMATES)}
    assert doc.whole is not None and doc.whole.name == "Whole service area"
    g = stored["GLOBAL"]
    assert (doc.whole.p50_utc, doc.whole.p90_utc, doc.whole.p50_h) == (
        g.p50_utc,
        g.p90_utc,
        g.hours_from_as_of["p50"],
    )
    assert doc.whole.still_out_ppm == round(g.customers_out_now / g.peak_customers_out * 1_000_000)
    assert len(doc.areas) == len(stored) - 1
    assert [a.p50_h for a in doc.areas] == sorted((a.p50_h for a in doc.areas), reverse=True)
    sandhill = next(a for a in doc.areas if a.region_id == "OPA-AIK-SANDHILL")
    assert sandhill.name == "Aiken area" and sandhill.county == "Aiken County"
    assert sandhill.range_h == round((sandhill.p90_utc - sandhill.p10_utc).total_seconds() / 3600, 1)
    caveat = sources.etr_caveat()
    assert doc.coverage80_ppm == caveat.coverage80_ppm and doc.real_storm_checked is False
    assert doc.provenance.model_id == g.model_version and doc.provenance.label.value == "S"
    assert doc.can_draft is False, "only the policy's proposer drafts"
    r = client.get("/api/etr/areas/OPA-AIK-SANDHILL")
    assert r.status_code == 200 and EtrArea.model_validate(r.json()) == sandhill
    assert client.get("/api/etr/areas/OPA-NOWHERE").status_code == 404


def test_planner_drafts_two_functions_sign_planner_publishes(client: TestClient, db_url: str) -> None:
    seek(client, ETR_TIME)
    doc = etr_view(client, "plan_etr_01")
    assert doc.can_draft is True and doc.publication is None
    csrf = login(client, "plan_etr_01")
    thread = client.post("/api/threads", json={"module": "forecast"}, headers=csrf).json()["thread_id"]
    r = client.post(f"/api/threads/{thread}/runs", json={"graph": "etr", "input": {}}, headers=csrf)
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    assert wait_run(db_url, run_id, {"paused", "done", "error"}) == "paused"

    doc = etr_view(client, "plan_etr_01")
    pub = doc.publication
    assert pub is not None and pub.state.value == "proposed" and pub.run_id == run_id
    assert pub.proposed_by == "plan_etr_01" and pub.estimate_id == doc.whole.estimate_id  # type: ignore[union-attr]
    assert sorted(f.value for f in pub.required_functions) == ["command", "operations"]
    assert pub.signed_functions == [] and doc.can_draft is False and doc.can_publish is False
    assert "proposal_created" in audit_kinds(db_url, pub.proposal_id)

    sign(client, "ic_01", pub.proposal_id)
    mid = etr_view(client, "plan_etr_01").publication
    assert mid is not None and [f.value for f in mid.signed_functions] == ["command"]
    sign(client, "ops_dm_01", pub.proposal_id)
    ready = etr_view(client, "plan_etr_01")
    assert ready.publication is not None and ready.publication.state.value == "approved"
    assert ready.can_publish is True
    assert etr_view(client, "ic_01").can_publish is False, "only the proposer publishes"

    csrf = login(client, "plan_etr_01")
    r = client.post(f"/api/runs/{run_id}/resume", json={}, headers=csrf)
    assert r.status_code == 202, r.text
    assert wait_run(db_url, run_id, {"done", "error"}) == "done"

    final = etr_view(client, "audit_01")
    done = final.publication
    assert done is not None and done.state.value == "executed"
    assert done.published_by == "plan_etr_01" and done.published_at == datetime(
        2024, 9, 28, 18, 0, tzinfo=UTC
    )
    assert done.audit_seq is not None and final.can_draft is False
    kinds = audit_kinds(db_url, pub.proposal_id)
    assert kinds[-2:] == ["execution_token_burned", "etr_published"]
    assert etr_view(client, "plan_etr_01").can_draft is False, "the same estimate is not drafted twice"
    assert final.revision is not None and final.revision.due is False

    seek(client, NOTICES_LIFTED)
    later = etr_view(client, "plan_etr_01")
    assert later.revision is not None and later.revision.due is True and later.revision.ahead_h > 12
    assert later.can_draft is True, "a published ETR that actuals moved by more than 12 h can be revised"
    assert later.whole is not None and later.whole.actual_out_now == 168_598
    assert later.actual_as_of == datetime(2024, 9, 30, 12, 0, tzinfo=UTC)
    assert etr_view(client, "exec_01").can_draft is False
    assert later.revision.published_p50_utc == done.p50_utc
    assert later.revision.revised_p50_utc is not None
    assert later.revision.revised_p50_utc < done.p50_utc - timedelta(hours=12)
    assert "DOM 14.206" not in later.revision.reason and "P50" not in later.revision.reason

    csrf = login(client, "plan_etr_01")
    thread = client.post("/api/threads", json={"module": "forecast"}, headers=csrf).json()["thread_id"]
    r = client.post(f"/api/threads/{thread}/runs", json={"graph": "etr", "input": {}}, headers=csrf)
    assert r.status_code == 202, r.text
    assert wait_run(db_url, r.json()["run_id"], {"paused", "done", "error"}) == "paused"
    revising = etr_view(client, "plan_etr_01")
    draft = revising.publication
    assert draft is not None and draft.state.value == "proposed" and draft.proposal_id != pub.proposal_id
    assert revising.revision is not None and revising.revision.published_p50_utc == done.p50_utc
    assert revising.can_draft is False
    login(client, "ops_dm_01")
    card = client.get(f"/api/proposals/{draft.proposal_id}").json()
    window = timedelta(hours=numbers.value("policy_etr_revise_publish_within_h"))
    lifted = datetime(2024, 9, 30, 12, 0, tzinfo=UTC)
    decide_by = datetime.fromisoformat(card["effective_decide_by_utc"].replace("Z", "+00:00"))
    assert lifted < decide_by <= lifted + window, "the revision's clock starts when it is drafted"
    assert card["severity"] != "critical" and card["decision_case_id"] != pub_case(db_url, pub.proposal_id)
    assert card["title"].startswith("Publish the revised global")


def test_after_action_draft_is_for_command_and_audit_and_audited(client: TestClient, db_url: str) -> None:
    seek(client, REVIEW)
    for user in ("ops_dm_01", "plan_etr_01", "exec_01"):
        csrf = login(client, user)
        r = client.post("/api/after-action/drafts", headers=csrf)
        assert r.status_code == 403, (user, r.text)
    csrf = login(client, "audit_01")
    assert client.post("/api/after-action/drafts").status_code == 403, "CSRF is checked"
    r = client.post("/api/after-action/drafts", headers=csrf)
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    assert wait_run(db_url, run_id, {"done", "error"}) == "done"
    assert audit_kinds(db_url, run_id) == ["after_action_drafted"]

    login(client, "ic_01")
    items = [AfterActionDraft.model_validate(d) for d in client.get("/api/after-action/drafts").json()]
    mine = next(d for d in items if d.run_id == run_id)
    assert mine.status == "draft" and mine.drafted_by == "audit_01" and mine.path == "m2"
    assert mine.as_of_utc == datetime(2024, 10, 6, 2, 0, tzinfo=UTC)
    assert mine.markdown is not None and mine.markdown.startswith("# After-action review")
    assert mine.summary and mine.usable is True
    login(client, "ops_dm_01")
    assert client.get("/api/after-action/drafts").json() == [], "others see only their own drafts"

    csrf = login(client, "ic_01")
    second = client.post("/api/after-action/drafts", headers=csrf)
    assert second.status_code == 202, second.text
    assert wait_run(db_url, second.json()["run_id"], {"done", "error"}) == "done"


def test_permissions_follow_the_tier_table() -> None:
    assert etr_rm.may_propose("plan_etr_01") and not etr_rm.may_propose("ic_01")
    assert {f.value for f in etr_rm.RULE.approver_functions} == {"command", "operations"}
