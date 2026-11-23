"""Over HTTP with the real app lifespan on a scratch database seeded like `sgw seed` (K18 users with a
password, the Helene decision cases and proposals): after-action review, tamper demo, admin integrations and
system link, agent runs. Every value check is traced to the engine, table or file it comes from."""

from __future__ import annotations

import json
import secrets
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from sgw.api.app import app_routes, create_app
from sgw.api.readmodels import after_action as aa_rm
from sgw.api.readmodels import brief as brief_rm
from sgw.api.readmodels import integrations as integrations_rm
from sgw.api.readmodels import obs
from sgw.api.readmodels import sitreps as sitreps_rm
from sgw.api.settings import ApiSettings
from sgw.api.users import seed_users
from sgw.approval import audit
from sgw.approval import testkit as tk
from sgw.approval.signer import Keyring, default_paths
from sgw.contracts.api_models import (
    AdminIntegrations,
    AfterActionView,
    AgentRunDetail,
    AgentRunSummary,
    BwaRegister,
    ExecutiveBrief,
    ProposalSummary,
    SitrepDraft,
    SystemMetricsLink,
    TamperDemoResult,
    contract_routes,
)
from sgw.contracts.vocab import Tier
from sgw.reports import after_action as aa
from sgw.reports.sources import COUNTY_HOURLY, REPO_ROOT, replay_status

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
PASSWORD = "beui3-" + secrets.token_hex(12)
READS = (
    "/api/after-action",
    "/api/admin/integrations",
    "/api/admin/system",
    "/api/runs",
    "/api/runs/run-x",
)
ADMIN_READS = ("/api/admin/integrations", "/api/admin/system")
EARLY = "2024-09-26T08:00:00Z"
MIDSTORM = "2024-09-27T14:00:00Z"
DAY_29 = "2024-09-29T20:00:00Z"
LATE = "2024-10-03T00:00:00Z"
STORY_ISSUE = "2024-09-28T17:30:00Z"
HOOK_URL = "https://hooks.tallowbranch-relay.test:8443/sgw/inbound?team=night"


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    from sgw.approval.seed import run_seed

    with tk.scratch_database("sgw_beui3_t") as url:
        run_seed(url, use_default_ledger=False)
        seed_users(url, PASSWORD)
        yield url


@pytest.fixture(scope="module")
def client(db_url: str) -> Iterator[TestClient]:
    settings = ApiSettings(
        database_url=db_url, demo_mode=True, cookie_secure=False, login_ip_burst=1000, login_user_burst=1000
    )
    app = create_app(settings)
    app.state.tamper_demo_window_s = 0.0
    with TestClient(app) as c:
        yield c


def login(c: TestClient, user_id: str) -> dict[str, str]:
    r = c.post("/api/auth/login", json={"user_id": user_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": c.cookies["sgw_csrf"]}


def seek(c: TestClient, at: str) -> None:
    csrf = login(c, "ic_01")
    assert c.post("/api/scenario", json={"action": "pause"}, headers=csrf).status_code == 200
    r = c.post("/api/scenario", json={"action": "seek", "scenario_time": at}, headers=csrf)
    assert r.status_code == 200, r.text


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _engine_review(db_url: str, at: str) -> aa.AfterActionReview:
    paths = default_paths()
    with psycopg.connect(db_url, autocommit=True) as conn:
        return aa.review(
            conn, _utc(at), keyring=Keyring.load(paths.keyring), anchors=audit.AnchorStore(paths.anchors)
        )


def test_routes_are_mounted_and_in_the_contract() -> None:
    app = create_app(ApiSettings(database_url="postgresql://unused/unused", demo_mode=True))
    served = app_routes(app)
    mine = {("GET", "/api/after-action"), ("POST", "/api/audit/tamper-demo"), ("GET", "/api/runs")}
    mine |= {("GET", "/api/runs/{run_id}"), ("GET", "/api/admin/integrations"), ("GET", "/api/admin/system")}
    assert mine <= served
    assert mine <= contract_routes()


def test_every_read_needs_a_session(client: TestClient) -> None:
    client.cookies.clear()
    for path in READS:
        r = client.get(path)
        assert r.status_code == 401, path
    assert client.post("/api/audit/tamper-demo", json={}).status_code == 401


def test_after_action_is_the_engine_review_at_the_scenario_time(client: TestClient, db_url: str) -> None:
    seek(client, LATE)
    login(client, "exec_01")
    r = client.get("/api/after-action")
    assert r.status_code == 200, r.text
    doc = AfterActionView.model_validate(r.json())
    engine = _engine_review(db_url, LATE)
    assert doc.as_of == _utc(LATE)
    assert doc.usable is engine.usable is True
    assert doc.chain.model_dump() == engine.chain.model_dump()
    with psycopg.connect(db_url) as conn:
        page = aa_rm.page_clocks(engine.clocks, aa_rm.still_open(conn))
    assert [c.model_dump() for c in doc.clocks] == [c.model_dump() for c in page]
    assert [(t.seq, t.kind) for t in doc.timeline] == [(t.seq, t.kind) for t in engine.timeline]
    assert len(doc.break_glass) == len(engine.break_glass)
    assert r.headers["ETag"]
    assert client.get("/api/after-action", headers={"If-None-Match": r.headers["ETag"]}).status_code == 304


def test_scorecard_follows_what_was_issued_by_then(client: TestClient) -> None:
    seek(client, EARLY)
    login(client, "audit_01")
    early = AfterActionView.model_validate(client.get("/api/after-action").json())
    assert early.scorecard.source == "none"
    assert early.scorecard.estimates == []
    seek(client, LATE)
    login(client, "audit_01")
    late = AfterActionView.model_validate(client.get("/api/after-action").json())
    story = json.loads(aa_rm.STORY_SCORECARD.read_text(encoding="utf-8"))
    assert late.scorecard.source == "data/artefacts/evals/etr_story_scorecard.json"
    assert late.scorecard.as_of == _utc(STORY_ISSUE)
    assert [e.estimate_id for e in late.scorecard.estimates] == [e["estimate_id"] for e in story["estimates"]]
    after_all = sum(1 for e in story["estimates"] if _utc(e["actual_utc"]) <= _utc(LATE))
    assert (late.scorecard.resolved, late.scorecard.total) == (after_all, len(story["estimates"]))
    assert late.scorecard.resolved_label == f"{after_all} of {len(story['estimates'])} resolved"


def test_scorecard_never_shows_an_actual_after_the_scenario_clock(client: TestClient) -> None:
    seek(client, DAY_29)
    login(client, "audit_01")
    card = AfterActionView.model_validate(client.get("/api/after-action").json()).scorecard
    story = json.loads(aa_rm.STORY_SCORECARD.read_text(encoding="utf-8"))
    ahead = {e["estimate_id"] for e in story["estimates"] if _utc(e["actual_utc"]) > _utc(DAY_29)}
    assert ahead and len(ahead) < len(story["estimates"])
    for row in card.estimates:
        if row.estimate_id in ahead:
            assert row.actual_utc is None and row.abs_error_h is None and row.p50_error_h is None
            assert row.in_p25_p75 is None and row.in_p10_p90 is None and row.analog_abs_error_h is None
        else:
            assert row.actual_utc is not None and row.actual_utc <= _utc(DAY_29)
    resolved = len(story["estimates"]) - len(ahead)
    assert card.resolved == resolved
    assert card.resolved_label == f"{resolved} of {len(story['estimates'])} resolved"
    assert card.metrics and all(m.n <= resolved for m in card.metrics)
    assert sum(m.n for m in card.metrics if m.metric.endswith("p50_abs_error_h_median")) == resolved


def test_regulator_draft_only_counts_outages_ended_by_then(client: TestClient) -> None:
    seek(client, EARLY)
    login(client, "ops_dm_01")
    assert client.get("/api/after-action").json()["sc_report"] is None
    seek(client, LATE)
    login(client, "ops_dm_01")
    draft = AfterActionView.model_validate(client.get("/api/after-action").json()).sc_report
    assert draft is not None
    full = aa_rm.sc.build()
    engine = aa_rm.regulator_draft(_utc(LATE))
    assert engine is not None
    assert draft == engine
    assert draft.filed is False
    assert draft.citation == full.citation
    assert all(c.restored_at <= _utc(LATE) for c in draft.counties)
    assert draft.system.customers_interrupted <= full.system.customers_interrupted
    assert draft.markdown.startswith("#") or draft.citation in draft.markdown


def test_tamper_demo_reports_the_altered_record_and_leaves_the_chain(client: TestClient, db_url: str) -> None:
    csrf = login(client, "audit_01")
    with psycopg.connect(db_url, autocommit=True) as conn:
        head = conn.execute("SELECT max(seq), count(*) FROM audit_event WHERE stream = 'global'").fetchone()
        before = audit.verify(conn)
    assert head is not None and head[1] > 0
    r = client.post("/api/audit/tamper-demo", json={"seq": 1}, headers=csrf)
    assert r.status_code == 200, r.text
    demo = TamperDemoResult.model_validate(r.json())
    assert demo.tampered_seq == 1
    assert demo.result.ok is False
    assert demo.result.first_bad_seq == demo.untrusted_from_seq == 1
    assert demo.problems[0].startswith("seq 1: payload does not match")
    default = TamperDemoResult.model_validate(
        client.post("/api/audit/tamper-demo", json={}, headers=csrf).json()
    )
    with psycopg.connect(db_url, autocommit=True) as conn:
        rows = [dict(x) for x in audit._rows(conn, audit.STREAM)]
        after = audit.verify(conn)
        assert (
            conn.execute("SELECT max(seq), count(*) FROM audit_event WHERE stream = 'global'").fetchone()
            == head
        )
    assert default.tampered_seq == aa_rm.default_tamper_seq(rows)
    assert default.result.first_bad_seq == default.tampered_seq
    assert after.ok is before.ok
    missing = client.post("/api/audit/tamper-demo", json={"seq": head[0] + 1000}, headers=csrf)
    assert missing.status_code == 404
    assert client.post("/api/audit/tamper-demo", json={"seq": 1}).status_code == 403


def test_tamper_demo_is_rate_limited_per_session(client: TestClient) -> None:
    app: Any = client.app
    app.state.tamper_demo_window_s = 60.0
    try:
        csrf = login(client, "wtr_comp_01")
        assert client.post("/api/audit/tamper-demo", json={"seq": 1}, headers=csrf).status_code == 200
        again = client.post("/api/audit/tamper-demo", json={"seq": 1}, headers=csrf)
        assert again.status_code == 429
        assert int(again.headers["Retry-After"]) >= 1
    finally:
        app.state.tamper_demo_window_s = 0.0


def _seed_integrations(db_url: str) -> dict[str, str]:
    token_id, sub_id = "itk" + secrets.token_hex(6), "whs_" + secrets.token_hex(8)
    now = datetime.now(UTC).replace(microsecond=0)
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO api_token (token_id, name, token_hash, scopes, created_by, created_at, expires_at)"
            " VALUES (%s, 'Night relay', %s, ARRAY['decisions:read','webhooks:manage'], 'admin_01', %s, %s)",
            (token_id, secrets.token_hex(32), now, now + timedelta(days=30)),
        )
        conn.execute(
            "INSERT INTO webhook_subscription (subscription_id, url, event_types, secret_ref, secret_hint,"
            " token_id, created_at)"
            " VALUES (%s, %s, ARRAY['DecisionApproved'], 'sealed:slot-1', 'q7Zk', %s, %s)",
            (sub_id, HOOK_URL, token_id, now),
        )
        event_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO event (event_id, type, schema_version, source_id, feed_mode, run_mode, event_time,"
            " received_at, known_at, scenario_known_at, dedup_key, classification, trust, payload)"
            " VALUES (%s, 'DecisionApproved', 1, 'sgw-platform', 'replay', 'replay', %s, %s, %s, %s, %s,"
            " 'C1', 'system', %s)",
            (event_id, now, now, now, now, f"beui3:{event_id}", Jsonb({"proposal_id": "PRP-BEUI3"})),
        )
        rows = [
            ("whd_" + secrets.token_hex(16), "delivered", 1, 200, None, now),
            ("whd_" + secrets.token_hex(16), "failed", 8, 500, f"POST {HOOK_URL} answered 500", None),
        ]
        for delivery_id, state, attempts, status, error, delivered in rows:
            other = event_id if state == "delivered" else _second_event(conn, now)
            conn.execute(
                "INSERT INTO webhook_delivery (delivery_id, subscription_id, event_id, state, attempts,"
                " last_status, last_error, delivered_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (delivery_id, sub_id, other, state, attempts, status, error, delivered),
            )
    return {"token_id": token_id, "subscription_id": sub_id}


def _second_event(conn: psycopg.Connection[Any], now: datetime) -> str:
    event_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO event (event_id, type, schema_version, source_id, feed_mode, run_mode, event_time,"
        " received_at, known_at, scenario_known_at, dedup_key, classification, trust, payload)"
        " VALUES (%s, 'DecisionApproved', 1, 'sgw-platform', 'replay', 'replay', %s, %s, %s, %s, %s,"
        " 'C1', 'system', %s)",
        (event_id, now, now, now, now, f"beui3:{event_id}", Jsonb({"proposal_id": "PRP-BEUI3-2"})),
    )
    return event_id


def test_admin_integrations_show_metadata_without_secrets(client: TestClient, db_url: str) -> None:
    ids = _seed_integrations(db_url)
    login(client, "admin_01")
    r = client.get("/api/admin/integrations")
    assert r.status_code == 200, r.text
    text = r.text
    doc = AdminIntegrations.model_validate(r.json())
    token = next(t for t in doc.tokens if t.token_id == ids["token_id"])
    assert token.name == "Night relay"
    sub = next(s for s in doc.subscriptions if s.subscription_id == ids["subscription_id"])
    assert sub.host == "hooks.tallowbranch-relay.test:8443"
    assert sub.state == "active"
    assert (sub.counts.delivered, sub.counts.pending, sub.counts.failed) == (1, 0, 1)
    assert sub.last_delivery_at is not None
    failed = next(d for d in doc.deliveries if d.status == "failed")
    assert failed.attempts == 8 and failed.event_type == "DecisionApproved"
    assert failed.last_error == "POST hooks.tallowbranch-relay.test:8443 answered 500"
    for secret in ("/sgw/inbound", "team=night", "sealed:slot-1", "token_hash", "secret_ref"):
        assert secret not in text


def test_admin_views_are_platform_admin_only(client: TestClient) -> None:
    login(client, "ops_dm_01")
    for path in ADMIN_READS:
        r = client.get(path)
        assert r.status_code == 403, path
        assert r.json()["error"]["code"] == "ADMIN_ONLY"


def test_system_link_only_while_grafana_answers(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    obs._cache.clear()
    monkeypatch.setattr(obs, "_probe", lambda url: False)
    login(client, "admin_01")
    down = SystemMetricsLink.model_validate(client.get("/api/admin/system").json())
    assert down.obs_profile_up is False and down.grafana_url is None
    assert "sgw obs up" in down.how_to_enable
    obs._cache.clear()
    monkeypatch.setattr(obs, "_probe", lambda url: True)
    up = SystemMetricsLink.model_validate(client.get("/api/admin/system").json())
    assert up.obs_profile_up is True and up.grafana_url == obs.DEFAULT_LINK
    assert up.api is not None and up.api.requests >= 2 and up.api.window >= 1
    obs._cache.clear()


def _seed_runs(db_url: str) -> dict[str, Any]:
    t0 = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
    runs = {
        "mine": (
            f"run-{secrets.token_hex(6)}",
            f"thr-{secrets.token_hex(6)}",
            "ops_dm_01",
            "copilot",
            "done",
        ),
        "other": (
            f"run-{secrets.token_hex(6)}",
            f"thr-{secrets.token_hex(6)}",
            "wtr_lead_01",
            "sitrep",
            "error",
        ),
    }
    calls = {
        "mine": [
            ("route_intent", "haiku", 120, 10, 30, 900),
            ("investigate", "sonnet", 2400, 310, 400, 41000),
        ],
        "other": [("sitrep", "sonnet", 800, 200, 0, 9000)],
    }
    with psycopg.connect(db_url, autocommit=True) as conn:
        for key, (run_id, thread_id, user, graph, status) in runs.items():
            conn.execute(
                "INSERT INTO agent_thread (thread_id, user_id, module, created_at)"
                " VALUES (%s, %s, 'ask', %s)",
                (thread_id, user, t0),
            )
            conn.execute(
                "INSERT INTO agent_run (run_id, thread_id, user_id, graph, graph_version, run_mode, status,"
                " started_at, ended_at) VALUES (%s, %s, %s, %s, %s, 'replay', %s, %s, %s)",
                (run_id, thread_id, user, graph, f"{graph}@1", status, t0, t0 + timedelta(seconds=12)),
            )
            for i, (node, model, tin, tout, cache_read, cost) in enumerate(calls[key]):
                conn.execute(
                    "INSERT INTO llm_call (call_id, ts, mode, billed, purpose, run_id, node, model,"
                    " input_tokens, cache_read_input_tokens, output_tokens, cost_usd_micros, latency_ms,"
                    " decision, request_hash)"
                    " VALUES (%s, %s, 'replay', false, 'demo', %s, %s, %s, %s, %s, %s, %s, %s, 'allow', %s)",
                    (
                        f"call-{secrets.token_hex(6)}",
                        t0 + timedelta(seconds=3 + 4 * i),
                        run_id,
                        node,
                        model,
                        tin,
                        cache_read,
                        tout,
                        cost,
                        700 + i,
                        secrets.token_hex(32),
                    ),
                )
        run_id, thread_id = runs["mine"][0], runs["mine"][1]
        lg_thread = f"{thread_id}:{run_id}"
        for i, node in enumerate(("load_context", "route", "investigate")):
            cp = f"1ef{i:05d}-0000-6000-8000-{secrets.token_hex(6)}"
            ts = (t0 + timedelta(seconds=1 + 4 * i)).isoformat()
            conn.execute(
                "INSERT INTO lg.checkpoints (thread_id, checkpoint_ns, checkpoint_id, checkpoint)"
                " VALUES (%s, '', %s, %s)",
                (lg_thread, cp, Jsonb({"ts": ts, "v": 4})),
            )
            conn.execute(
                "INSERT INTO lg.checkpoint_writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx,"
                " channel, type, blob, task_path) VALUES (%s, '', %s, %s, 0, %s, 'msgpack', '\\x00', %s)",
                (lg_thread, cp, f"task-{i}", f"branch:to:{node}", f"~__pregel_pull, {node}"),
            )
    return {"runs": runs, "calls": calls}


@pytest.fixture(scope="module")
def seeded_runs(db_url: str) -> dict[str, Any]:
    """The run rows once per module, so each runs test stands alone (pytest -k, xdist order)."""
    return _seed_runs(db_url)


def test_runs_list_own_runs_with_llm_call_totals(client: TestClient, seeded_runs: dict[str, Any]) -> None:
    seeded = seeded_runs
    mine_id = seeded["runs"]["mine"][0]
    other_id = seeded["runs"]["other"][0]
    login(client, "ops_dm_01")
    r = client.get("/api/runs")
    assert r.status_code == 200, r.text
    items = [AgentRunSummary.model_validate(x) for x in r.json()]
    assert {i.run_id for i in items} == {mine_id}
    run = items[0]
    calls = seeded["calls"]["mine"]
    assert run.llm_calls == 2 and run.billed_calls == 0
    assert run.tokens_in == sum(c[2] + c[4] for c in calls)
    assert run.tokens_out == sum(c[3] for c in calls)
    assert run.cost_usd_micros == sum(c[5] for c in calls)
    assert run.nodes == ["route_intent", "investigate"]
    assert run.models == ["haiku", "sonnet"]
    assert run.duration_ms == 12_000
    assert client.get(f"/api/runs/{other_id}").status_code == 404


def test_runs_every_run_for_platform_and_filters(client: TestClient, seeded_runs: dict[str, Any]) -> None:
    login(client, "admin_01")
    every = [AgentRunSummary.model_validate(x) for x in client.get("/api/runs").json()]
    assert {"ops_dm_01", "wtr_lead_01"} <= {r.user_id for r in every}
    errors = [AgentRunSummary.model_validate(x) for x in client.get("/api/runs?status=error").json()]
    assert errors and all(r.status == "error" for r in errors)
    sitreps = client.get("/api/runs?graph=sitrep&limit=1").json()
    assert len(sitreps) == 1 and sitreps[0]["graph"] == "sitrep"
    assert client.get("/api/runs?limit=0").status_code == 422
    assert client.get("/api/runs?status=exploded").status_code == 422


def test_run_detail_merges_graph_steps_and_llm_calls(client: TestClient, seeded_runs: dict[str, Any]) -> None:
    login(client, "ops_dm_01")
    run_id = seeded_runs["runs"]["mine"][0]
    r = client.get(f"/api/runs/{run_id}")
    assert r.status_code == 200, r.text
    detail = AgentRunDetail.model_validate(r.json())
    seq = [(s.kind, s.node) for s in detail.steps]
    assert seq == [
        ("graph_step", "load_context"),
        ("llm_call", "route_intent"),
        ("graph_step", "route"),
        ("llm_call", "investigate"),
        ("graph_step", "investigate"),
    ]
    assert [s.seq for s in detail.steps] == [1, 2, 3, 4, 5]
    llm = [s for s in detail.steps if s.kind == "llm_call"]
    assert [s.tokens_out for s in llm] == [10, 310]
    assert "prompt" not in r.text


def _fixture_latest(name: str, kind: str, key: str, at: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for line in (brief_rm.FIXTURES / "helene" / name).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("type") == kind and _utc(row["scenario_known_at"]) <= _utc(at):
            out[str(row["payload"][key])] = row["payload"]
    return out


def test_brief_numbers_come_from_their_sources(client: TestClient) -> None:
    seek(client, MIDSTORM)
    login(client, "exec_01")
    r = client.get("/api/brief")
    assert r.status_code == 200, r.text
    doc = ExecutiveBrief.model_validate(r.json())
    nums = {n.key: n for n in doc.numbers}
    assert list(nums) == ["customers_out", "critical_facilities", "water_zones_advisory", "crews_working"]
    status = replay_status(_utc(MIDSTORM))
    assert nums["customers_out"].actual == status.customers_out_now
    outages = _fixture_latest("oms.jsonl", "OutageEvent", "outage_id", MIDSTORM)
    facilities = {
        f for p in outages.values() if p["status"] != "restored" for f in p["critical_facility_ids"]
    }
    assert nums["critical_facilities"].actual == len(facilities)
    crews = _fixture_latest("fsm.jsonl", "CrewStatus", "crew_id", MIDSTORM)
    working = sum(1 for p in crews.values() if p["status"] in ("enroute", "onsite"))
    assert nums["crews_working"].actual == working
    assert sum(nums["crews_working"].breakdown.values()) == len(crews)
    register = BwaRegister.model_validate(client.get("/api/water/advisories").json())
    assert nums["water_zones_advisory"].actual == sum(1 for a in register.advisories if a.status == "issued")
    ops = next(f for f in doc.functions if f.function.value == "operations")
    assert f"{status.customers_out_now:,} customers out" in ops.sentence
    logistics = next(f for f in doc.functions if f.function.value == "logistics")
    assert logistics.sentence.startswith(f"{working} crews working")
    assert doc.caveat == brief_rm.CAVEAT
    assert "P80" not in r.text


def test_brief_open_t3_and_status_word_follow_the_queue(client: TestClient) -> None:
    seek(client, MIDSTORM)
    login(client, "exec_01")
    doc = ExecutiveBrief.model_validate(client.get("/api/brief").json())
    queue = [ProposalSummary.model_validate(x) for x in client.get("/api/proposals").json()]
    expected = sorted(
        (
            p
            for p in queue
            if p.tier.value == "T3" and p.state.value in ("proposed", "in_review", "escalated")
        ),
        key=lambda p: (p.effective_decide_by_utc, p.proposal_id),
    )
    assert [p.proposal_id for p in doc.open_t3] == [p.proposal_id for p in expected]
    word, basis = brief_rm.status_word(
        expected, replay_status(_utc(MIDSTORM)), doc.last_advisory, _utc(MIDSTORM)
    )
    assert (doc.status_word, doc.status_basis) == (word, basis)


def test_brief_advisory_and_forecast_are_known_at_discipline(client: TestClient, db_url: str) -> None:
    seek(client, EARLY)
    login(client, "ops_dm_01")
    early = ExecutiveBrief.model_validate(client.get("/api/brief").json())
    issued = [
        json.loads(line)
        for line in (brief_rm.FIXTURES / "helene" / "weather.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    known = [
        r
        for r in issued
        if r.get("type") == "WeatherForecastIssued" and _utc(r["scenario_known_at"]) <= _utc(EARLY)
    ]
    assert early.last_advisory is not None
    assert early.last_advisory.label == known[-1]["payload"]["advisory_label"]
    first, later = _utc("2024-09-26T03:00:00Z"), _utc("2024-09-27T03:00:00Z")
    with psycopg.connect(db_url, autocommit=True) as conn:
        for issued_at, fips, p50 in ((first, "45003", 1200), (first, "13245", 800), (later, "45003", 99999)):
            conn.execute(
                "INSERT INTO forecast (forecast_id, model_version, target, entity_id, region_id, domain,"
                " issued_at, known_at, valid_at, quantiles)"
                " VALUES (%s, 'm1', %s, %s, NULL, 'electric', %s, %s, %s, %s)",
                (
                    f"FC-BEUI3-{issued_at:%d%H}-{fips}",
                    brief_rm.FORECAST_TARGET,
                    fips,
                    issued_at,
                    issued_at,
                    issued_at + timedelta(hours=72),
                    Jsonb({"0500": p50, "0100": 1, "0900": 2 * p50}),
                ),
            )
    seek(client, EARLY)
    login(client, "ops_dm_01")
    doc = ExecutiveBrief.model_validate(client.get("/api/brief").json())
    customers = next(n for n in doc.numbers if n.key == "customers_out")
    assert customers.forecast == 2000
    assert customers.forecast_basis is not None and "25 Sep 23:00 ET (03:00Z)" in customers.forecast_basis


def _sitrep_run(db_url: str, user: str) -> tuple[str, str]:
    run_id, thread_id = f"run-{secrets.token_hex(6)}", f"thr-{secrets.token_hex(6)}"
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO agent_thread (thread_id, user_id, module, created_at)"
            " VALUES (%s, %s, 'brief', now())",
            (thread_id, user),
        )
        conn.execute(
            "INSERT INTO agent_run (run_id, thread_id, user_id, graph, graph_version, run_mode, status)"
            " VALUES (%s, %s, %s, 'sitrep', 'sitrep@1', 'replay', 'done')",
            (run_id, thread_id, user),
        )
    return run_id, thread_id


def _put_state(client: TestClient, thread: str, values: dict[str, Any]) -> None:
    import asyncio

    from sgw.api.routers.runs import GRAPHS

    runtime = client.app.state.agent_runtime  # type: ignore[attr-defined]
    graph = GRAPHS["sitrep"](runtime.checkpointer)
    asyncio.run(graph.aupdate_state({"configurable": {"thread_id": thread}}, values, as_node="sitrep_draft"))


def test_sitrep_drafts_are_listed_and_promoted_once_by_command(client: TestClient, db_url: str) -> None:
    from langgraph.checkpoint.memory import InMemorySaver

    from sgw.api.routers.runs import AgentRuntime

    app: Any = client.app
    app.state.agent_runtime = AgentRuntime(deps_factory=lambda _r: None, checkpointer=InMemorySaver())  # type: ignore[arg-type,return-value]
    text = "Customers out: [ev:status.out] across [ev:status.counties] counties."
    run_id, thread = _sitrep_run(db_url, "plan_etr_01")
    report = {
        "kind": "sitrep_draft",
        "tier": "T1",
        "promotion": "by a person",
        "path": "llm",
        "rendered": text,
        "slots": {"ev:status.out": "41,200", "ev:status.counties": "9"},
        "tainted": False,
        "as_of_utc": "2024-09-27T12:00:00+00:00",
    }
    _put_state(client, f"{thread}:{run_id}", {"report": report, "status": "draft_ready"})
    blocked_id, blocked_thread = _sitrep_run(db_url, "plan_etr_01")
    _put_state(client, f"{blocked_thread}:{blocked_id}", {"report": {"kind": "sitrep"}, "status": "blocked"})

    login(client, "ops_dm_01")
    assert client.get("/api/sitreps").json() == []
    login(client, "exec_01")
    items = {d.run_id: d for d in (SitrepDraft.model_validate(x) for x in client.get("/api/sitreps").json())}
    assert items[run_id].status == "draft" and items[run_id].text == text
    assert items[run_id].slots["ev:status.out"] == "41,200"
    assert items[run_id].tier == Tier.T1
    assert items[blocked_id].status == "blocked" and items[blocked_id].text is None

    csrf = login(client, "exec_01")
    assert client.post(f"/api/sitreps/{run_id}/promote", json={}, headers=csrf).status_code == 403
    csrf = login(client, "ic_01")
    assert client.post(f"/api/sitreps/{blocked_id}/promote", json={}, headers=csrf).status_code == 409
    assert client.post("/api/sitreps/run-nope/promote", json={}, headers=csrf).status_code == 404
    r = client.post(f"/api/sitreps/{run_id}/promote", json={"note": "for the 13:00 call"}, headers=csrf)
    assert r.status_code == 200, r.text
    done = SitrepDraft.model_validate(r.json())
    assert done.status == "promoted" and done.promoted_by == "ic_01" and done.audit_seq is not None
    assert done.text == text
    again = client.post(f"/api/sitreps/{run_id}/promote", json={}, headers=csrf)
    assert again.status_code == 409
    with psycopg.connect(db_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT kind, actor_id, payload FROM audit_event WHERE seq = %s AND stream = 'global'",
            (done.audit_seq,),
        ).fetchone()
        assert audit.verify(conn).ok
    assert row is not None and row[0] == "sitrep_promoted" and row[1] == "ic_01"
    assert row[2]["text_sha256"] == sitreps_rm.text_sha256(text)


def test_verify_rows_is_the_verifier_and_catches_truncation(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        rows = [dict(r) for r in audit.chain_rows(conn)]
        heads, segments = audit.trusted_heads(conn)
        full = audit.verify(conn)
    assert audit.verify_rows(rows, heads, segments) == full
    last = rows[-1]
    signed = {int(last["seq"]): audit.Head(int(last["seq"]), str(last["hash"]), "test", "test-key")}
    cut = audit.verify_rows(rows[:-1], signed, {})
    assert cut.ok is False
    assert cut.first_bad_seq == int(last["seq"])
    assert "truncated" in cut.problems[0]
    demo = aa_rm.tampered_copy(rows, int(rows[0]["seq"]))
    assert audit.verify_rows(demo, {}, {}).first_bad_seq == int(rows[0]["seq"])
    assert rows[0]["payload"] != demo[0]["payload"]


def test_after_action_verifies_the_chain_once_per_head(
    client: TestClient, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sgw.reports import after_action as reports_aa

    calls: list[int] = []
    real = reports_aa.audit.verify

    def counted(*args: Any, **kwargs: Any) -> audit.VerifyReport:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(reports_aa.audit, "verify", counted)
    app: Any = client.app
    app.state.after_action_cache_s = 60.0
    try:
        seek(client, "2024-09-30T06:00:00Z")
        login(client, "audit_01")
        first = client.get("/api/after-action")
        second = client.get("/api/after-action")
        assert first.status_code == second.status_code == 200
        assert len(calls) == 1
        with psycopg.connect(db_url, autocommit=True) as conn, conn.transaction():
            audit.append(
                conn,
                kind="beui3_cache_probe",
                actor_type="system",
                actor_id="system:test",
                subject="cache",
                payload={"probe": True},
                occurred_at=_utc("2024-09-30T05:00:00Z"),
            )
        third = AfterActionView.model_validate(client.get("/api/after-action").json())
        assert len(calls) == 2
        assert (
            third.chain.checked_to_seq
            == AfterActionView.model_validate(first.json()).chain.checked_to_seq + 1
        )
    finally:
        app.state.after_action_cache_s = 5.0


def test_clipped_and_normalised_urls_never_leave_the_admin_view(client: TestClient, db_url: str) -> None:
    ids = _seed_integrations(db_url)
    clipped = "attempt 8: POST HTTPS://Hooks.Tallowbranch-Relay.test:8443/sgw/inbou"
    reason = (
        "410 Gone from https://ops:hunter-pw@hooks.tallowbranch-relay.test:8443/sgw/inbound/?team=night&k=1"
    )
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE webhook_delivery SET last_error = %s WHERE subscription_id = %s AND state = 'failed'",
            (clipped, ids["subscription_id"]),
        )
        conn.execute(
            "UPDATE webhook_subscription SET active = false, disabled_at = now(), disabled_reason = %s"
            " WHERE subscription_id = %s",
            (reason, ids["subscription_id"]),
        )
    login(client, "admin_01")
    r = client.get("/api/admin/integrations")
    doc = AdminIntegrations.model_validate(r.json())
    sub = next(s for s in doc.subscriptions if s.subscription_id == ids["subscription_id"])
    assert sub.state == "disabled"
    assert sub.disabled_reason == "410 Gone from hooks.tallowbranch-relay.test:8443"
    failed = next(
        d for d in doc.deliveries if d.subscription_id == ids["subscription_id"] and d.status == "failed"
    )
    assert failed.last_error == "attempt 8: POST hooks.tallowbranch-relay.test:8443"
    for leak in ("/sgw/inbou", "team=night", "hunter-pw", "ops:"):
        assert leak not in r.text
    assert integrations_rm.scrub("see ftp://x:notaport/a") == "see x"


def _memory_runtime(client: TestClient) -> None:
    from langgraph.checkpoint.memory import InMemorySaver

    from sgw.api.routers.runs import AgentRuntime

    app: Any = client.app
    current = getattr(app.state, "agent_runtime", None)
    if current is None or not isinstance(current.checkpointer, InMemorySaver):
        app.state.agent_runtime = AgentRuntime(deps_factory=lambda _r: None, checkpointer=InMemorySaver())  # type: ignore[arg-type,return-value]


def _draft(text: str, tainted: bool) -> dict[str, Any]:
    return {
        "kind": "sitrep_draft",
        "tier": "T1",
        "promotion": "by a person",
        "path": "template",
        "rendered": text,
        "slots": {},
        "tainted": tainted,
        "as_of_utc": "2024-09-27T18:00:00+00:00",
    }


def test_tainted_sitrep_needs_a_recorded_note(client: TestClient, db_url: str) -> None:
    _memory_runtime(client)
    run_id, thread = _sitrep_run(db_url, "plan_etr_01")
    _put_state(
        client, f"{thread}:{run_id}", {"report": _draft("Field note quoted.", True), "status": "draft_ready"}
    )
    csrf = login(client, "ic_01")
    for body in ({}, {"note": "   "}):
        r = client.post(f"/api/sitreps/{run_id}/promote", json=body, headers=csrf)
        assert r.status_code == 409 and r.json()["error"]["code"] == "SITREP_TAINTED"
    r = client.post(
        f"/api/sitreps/{run_id}/promote", json={"note": "field note checked by phone"}, headers=csrf
    )
    assert r.status_code == 200, r.text
    seq = SitrepDraft.model_validate(r.json()).audit_seq
    with psycopg.connect(db_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT payload FROM audit_event WHERE stream = 'global' AND seq = %s", (seq,)
        ).fetchone()
    assert row is not None
    assert row[0]["tainted"] is True and row[0]["note"] == "field note checked by phone"


def test_promote_needs_csrf_and_drafters_see_only_their_own(client: TestClient, db_url: str) -> None:
    _memory_runtime(client)
    run_id, thread = _sitrep_run(db_url, "ops_dm_02")
    _put_state(
        client, f"{thread}:{run_id}", {"report": _draft("Feeder check done.", False), "status": "draft_ready"}
    )
    login(client, "ops_dm_02")
    own = [SitrepDraft.model_validate(x) for x in client.get("/api/sitreps").json()]
    assert [d.run_id for d in own] == [run_id]
    login(client, "ops_dm_01")
    assert run_id not in {x["run_id"] for x in client.get("/api/sitreps").json()}
    login(client, "ic_01")
    r = client.post(f"/api/sitreps/{run_id}/promote", json={})
    assert r.status_code == 403
    with psycopg.connect(db_url, autocommit=True) as conn:
        hits = conn.execute(
            "SELECT count(*) FROM audit_event WHERE kind = 'sitrep_promoted' AND subject = %s", (run_id,)
        ).fetchone()
    assert hits == (0,)


def test_brief_forecast_is_known_by_then_and_one_model_version(client: TestClient, db_url: str) -> None:
    at = "2024-09-28T06:00:00Z"
    issued, late_issue = _utc("2024-09-28T01:00:00Z"), _utc("2024-09-28T05:00:00Z")
    rows = (
        ("m1", issued, issued, "45003", 10),
        ("m1", issued, issued, "13245", 20),
        ("m0", issued, issued, "45003", 500),
        ("m1", late_issue, _utc("2024-09-28T07:00:00Z"), "45003", 7777),
    )
    with psycopg.connect(db_url, autocommit=True) as conn:
        for version, issued_at, known_at, fips, p50 in rows:
            conn.execute(
                "INSERT INTO forecast (forecast_id, model_version, target, entity_id, region_id, domain,"
                " issued_at, known_at, valid_at, quantiles)"
                " VALUES (%s, %s, %s, %s, NULL, 'electric', %s, %s, %s, %s)",
                (
                    f"FC-BEUI3-L6-{version}-{issued_at:%d%H}-{fips}",
                    version,
                    brief_rm.FORECAST_TARGET,
                    fips,
                    issued_at,
                    known_at,
                    issued_at + timedelta(hours=72),
                    Jsonb({"0500": p50}),
                ),
            )
    seek(client, at)
    login(client, "exec_01")
    raw = client.get("/api/brief")
    doc = ExecutiveBrief.model_validate(raw.json())
    customers = next(n for n in doc.numbers if n.key == "customers_out")
    assert customers.forecast == 30
    assert customers.provenance.model_id == "m1"
    assert customers.provenance.source == "Outage reports by county; outage forecast"
    assert str(COUNTY_HOURLY.relative_to(REPO_ROOT)) not in raw.text
    assert ".jsonl" not in raw.text and "/api/" not in raw.text


def test_brief_water_proposals_follow_the_scenario_clock(db_url: str) -> None:
    from sgw.api.readmodels import water as water_rm

    zone = "WZ-PS17-CEDARFALL"
    with psycopg.connect(db_url, autocommit=True) as conn:
        source = conn.execute("SELECT proposal_id FROM proposal ORDER BY created_at LIMIT 1").fetchone()
        assert source is not None
        conn.execute(
            "INSERT INTO proposal (proposal_id, decision_case_id, incident_id, action_type, params, targets,"
            " risk_band, tier, required_functions, state, action_hash, policy_version, initiator_kind,"
            " proposed_by, region_id, domain)"
            " SELECT 'PRP-BEUI3-BWN', decision_case_id, incident_id, 'boil_water_notice', '{}'::jsonb,"
            " ARRAY[%s], risk_band, 'T3', '{water_operations,compliance}', 'proposed',"
            " action_hash, policy_version, 'system_rule', 'system:rule:bwa_pre_landfall', region_id, 'water'"
            " FROM proposal WHERE proposal_id = %s",
            (zone, source[0]),
        )
        with conn.transaction():
            audit.append(
                conn,
                kind="proposal_created",
                actor_type="system",
                actor_id="system:rule:bwa_pre_landfall",
                subject="PRP-BEUI3-BWN",
                payload={"proposal_version": 1},
                occurred_at=_utc("2024-09-27T12:00:00Z"),
            )
        try:
            zones = water_rm.zone_ids()
            before = brief_rm.bwa_proposals(conn, zones, _utc("2024-09-27T11:00:00Z"))
            after = brief_rm.bwa_proposals(conn, zones, _utc("2024-09-27T13:00:00Z"))
        finally:
            conn.execute("DELETE FROM proposal WHERE proposal_id = 'PRP-BEUI3-BWN'")
    assert set(before) == set(after) == set(zones)
    assert before[zone] is None or before[zone].proposal_id != "PRP-BEUI3-BWN"
    assert after[zone] is not None and after[zone].proposal_id == "PRP-BEUI3-BWN"
