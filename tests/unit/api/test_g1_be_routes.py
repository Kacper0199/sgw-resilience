"""G1-BE routes over HTTP with the real app, real sessions and a seeded scratch database: the evidence of a
decision card resolved in its run's bundle, the audit ledger of one proposal, the Ask thread's runs list and
feedback, the one evaluation shape and the deployed migrations."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from sgw.agent.nodes.run_store import PostgresRunStore
from sgw.agent.render.evidence import EvidenceBundle, EvidenceItem
from sgw.api.app import create_app
from sgw.api.routers.runs import GRAPHS, AgentRuntime
from sgw.api.settings import ApiSettings
from sgw.api.users import seed_users
from sgw.approval import testkit as tk
from sgw.approval.ledger import MemorySink
from sgw.approval.policy import ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.contracts import golden
from sgw.contracts.api_models import EvidenceRecord, ThreadRun
from sgw.contracts.vocab import Classification, InitiatorKind, Trust

ROOT = Path(__file__).resolve().parents[3]
PASSWORD = "g1-be-scratch-only"  # noqa: S105
NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
AS_OF = datetime(2024, 9, 26, 9, 0, tzinfo=UTC)
WATER = "water_continuity"


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    from sgw.approval.seed import run_seed

    with tk.scratch_database("sgw_g1be_t") as url:
        run_seed(url, use_default_ledger=False)
        seed_users(url, PASSWORD)
        with psycopg.connect(url, autocommit=True) as conn:
            tk.add_asset(conn, tk.CLEAR_YARD, in_hazard_zone=False)
        yield url


@pytest.fixture(scope="module")
def client(db_url: str) -> Iterator[TestClient]:
    settings = ApiSettings(
        database_url=db_url, demo_mode=True, cookie_secure=False, login_ip_burst=1000, login_user_burst=1000
    )
    app = create_app(settings)
    with TestClient(app) as c:
        app.state.agent_runtime = AgentRuntime(
            deps_factory=lambda _r: None,
            store=PostgresRunStore(app.state.sgw.pool),
            checkpointer=InMemorySaver(),
        )  # type: ignore[arg-type,return-value]
        yield c


def login(c: TestClient, user_id: str) -> dict[str, str]:
    r = c.post("/api/auth/login", json={"user_id": user_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": c.cookies["sgw_csrf"]}


def _run(db_url: str, user: str, graph: str, module: str = "ask") -> tuple[str, str]:
    run_id, thread_id = f"run-{secrets.token_hex(6)}", f"thr-{secrets.token_hex(6)}"
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO agent_thread (thread_id, user_id, module, created_at) VALUES (%s, %s, %s, now())",
            (thread_id, user, module),
        )
        conn.execute(
            "INSERT INTO agent_run (run_id, thread_id, user_id, graph, graph_version, run_mode, status)"
            " VALUES (%s, %s, %s, %s, %s, 'replay', 'done')",
            (run_id, thread_id, user, graph, f"{graph}@1"),
        )
    return run_id, thread_id


def _put(client: TestClient, graph: str, thread: str, values: dict[str, Any], node: str) -> None:
    runtime = client.app.state.agent_runtime  # type: ignore[attr-defined]
    g = GRAPHS[graph](runtime.checkpointer)
    asyncio.run(g.aupdate_state({"configurable": {"thread_id": thread}}, values, as_node=node))


def _item(n: int, cls: Classification, label: str) -> EvidenceItem:
    return EvidenceItem(
        id=f"E{n}",
        kind="decision_clock",
        label=label,
        label_classification=cls,
        as_of=AS_OF,
        model_version="clocks@1",
        citation=f"clock:DC-D2-CREWS-AIK:{n}",
        classification=cls,
        trust=Trust.SYSTEM,
    )


def test_new_routes_are_mounted(client: TestClient) -> None:
    from sgw.api.app import app_routes
    from sgw.contracts.api_models import missing_routes

    served = app_routes(client.app)  # type: ignore[arg-type]
    for path in (
        "/api/proposals/{proposal_id}/evidence",
        "/api/threads/{thread_id}/runs",
        "/api/threads/{thread_id}/runs/{run_id}/feedback",
    ):
        assert any(p == path for _, p in served), path
    assert missing_routes(served, prefixes=("/api/threads", "/api/proposals")) == []


def test_card_evidence_resolves_in_the_bundle_of_its_run(client: TestClient, db_url: str) -> None:
    run_id, thread = _run(db_url, "ops_dm_01", WATER, module="decisions")
    bundle = EvidenceBundle(
        run_id=run_id,
        items=[
            _item(1, Classification.C1, "PS-17 decide-by at advisory N"),
            _item(2, Classification.C2, "Zone forecast"),
        ],
    )
    _put(client, WATER, f"{thread}:{run_id}", {"bundle": bundle.model_dump(mode="json")}, "fuse")
    svc = ApprovalService(ReferencePolicy(), scenario_clock=lambda: AS_OF, ledger=MemorySink())
    request = tk.staging_request()
    request = request.model_copy(update={"evidence_ids": ["E2", "E1", "E9"]})
    with psycopg.connect(db_url, autocommit=True) as conn:
        card = svc.create(
            conn, proposed_by="ops_dm_01", request=request, initiator_kind=InitiatorKind.AGENT, run_id=run_id
        ).value
    login(client, "ops_dm_01")
    rows = [
        EvidenceRecord.model_validate(r)
        for r in client.get(f"/api/proposals/{card.proposal_id}/evidence").json()
    ]
    assert [r.id for r in rows] == card.evidence_ids
    by_id = {r.id: r for r in rows}
    assert (
        by_id["E1"].title == "PS-17 decide-by at advisory N"
        and by_id["E1"].source == "clock:DC-D2-CREWS-AIK:1"
    )
    assert by_id["E1"].as_of_utc == AS_OF and by_id["E1"].run_id == run_id and by_id["E1"].graph == WATER
    assert by_id["E2"].title == "Zone forecast" and not by_id["E2"].withheld
    assert by_id["E9"].recorded is False and by_id["E9"].title is None
    login(client, "wtr_comp_01")
    water_only = {r["id"]: r for r in client.get(f"/api/proposals/{card.proposal_id}/evidence").json()}
    assert water_only["E2"]["withheld"] is True and water_only["E2"]["title"] is None
    assert water_only["E1"]["title"] == "PS-17 decide-by at advisory N"
    seeded = client.get(f"/api/proposals/{golden.PROPOSAL_CREWS}/evidence")
    assert seeded.status_code == 200 and seeded.json() == []
    missing = client.get("/api/proposals/PRP-NOPE/evidence")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "PROPOSAL_NOT_FOUND"


def test_audit_subject_filter_returns_one_proposals_ledger(client: TestClient) -> None:
    login(client, "audit_01")
    rows = client.get("/api/audit", params={"subject": golden.PROPOSAL_CREWS}).json()
    assert rows and {r["subject"] for r in rows} == {golden.PROPOSAL_CREWS}
    assert rows[0]["kind"] == "proposal_created" and rows[0]["actor_type"] == "user"
    assert client.get("/api/audit", params={"subject": "PRP-NOPE"}).json() == []


def _copilot_values(question: str, reason: str | None, path: str) -> dict[str, Any]:
    citation = {
        "n": 1,
        "source": "CH-1",
        "doc_id": "SOP-ETR-04",
        "version": "3",
        "citation_id": "SOP-ETR-04 rev 3",
        "section": "4.2",
        "pages": "p. 6",
        "cited_text": "Revise a published global ETR within one hour.",
        "unverified": False,
    }
    return {
        "question": question,
        "answer": {
            "path": path,
            "rendered": 'Within one hour.\n\nSources:\n[1] SOP-ETR-04 rev 3, 4.2, p. 6: "..."',
            "citations": [citation] if path != "not_in_documents" else [],
            "evidence_ids": [],
            "tool_calls": [{"tool": "search_procedures", "args": {"query": "revise ETR"}, "status": "ok"}],
            "reason": reason,
        },
    }


def test_thread_runs_messages_and_feedback(client: TestClient, db_url: str) -> None:
    run_id, thread = _run(db_url, "ic_01", "copilot")
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO document (doc_id, title, source, licence, classification, trust)"
            " VALUES ('SOP-ETR-04', 'Estimated restoration time updates', 'synthetic', 'CC0', 'C1',"
            " 'verified_internal') ON CONFLICT DO NOTHING"
        )
        conn.execute(
            "UPDATE agent_run SET started_at = now() - interval '1 minute' WHERE run_id = %s", (run_id,)
        )
    second, _ = run_id, thread
    _put(
        client,
        "copilot",
        f"{thread}:{run_id}",
        _copilot_values("When to revise a global ETR?", None, "llm"),
        "respond",
    )
    other = f"run-{secrets.token_hex(6)}"
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO agent_run (run_id, thread_id, user_id, graph, graph_version, run_mode, status)"
            " VALUES (%s, %s, 'ic_01', 'copilot', 'copilot@1', 'replay', 'done')",
            (other, thread),
        )
    _put(
        client,
        "copilot",
        f"{thread}:{other}",
        _copilot_values("Gateway down?", "gateway_unreachable", "m2"),
        "respond",
    )
    csrf = login(client, "ic_01")
    msgs = client.get(f"/api/threads/{thread}/messages").json()
    answer = next(m for m in msgs if m["run_id"] == second and m["role"] == "assistant")
    assert answer["path"] == "llm" and answer["reason"] is None
    assert answer["citations"][0]["title"] == "Estimated restoration time updates"
    assert answer["citations"][0]["citation_id"] == "SOP-ETR-04 rev 3"
    assert answer["tool_calls"] == [
        {"tool": "search_procedures", "args": {"query": "revise ETR"}, "status": "ok"}
    ]
    down = next(m for m in msgs if m["run_id"] == other and m["role"] == "assistant")
    assert down["path"] == "m2" and down["reason"] == "llm_unavailable"
    r = client.post(
        f"/api/threads/{thread}/runs/{second}/feedback",
        json={"rating": "down", "note": "too vague"},
        headers=csrf,
    )
    assert r.status_code == 204, r.text
    r = client.post(f"/api/threads/{thread}/runs/{second}/feedback", json={"rating": "up"}, headers=csrf)
    assert r.status_code == 204
    runs = [ThreadRun.model_validate(x) for x in client.get(f"/api/threads/{thread}/runs").json()]
    assert [x.run_id for x in runs] == [other, second]
    assert runs[1].question == "When to revise a global ETR?" and runs[1].feedback == "up"
    assert runs[0].reason == "llm_unavailable" and runs[0].feedback is None
    assert runs[1].tool_calls[0].tool == "search_procedures" and runs[1].status == "done"
    with psycopg.connect(db_url, autocommit=True) as conn:
        assert conn.execute(
            "SELECT rating, note FROM agent_run_feedback WHERE run_id = %s", (second,)
        ).fetchone() == ("up", None)
    bad = client.post(f"/api/threads/{thread}/runs/{second}/feedback", json={"rating": "meh"}, headers=csrf)
    assert bad.status_code == 422
    csrf = login(client, "ops_dm_01")
    assert client.get(f"/api/threads/{thread}/runs").status_code == 404
    hidden = client.post(f"/api/threads/{thread}/runs/{second}/feedback", json={"rating": "up"}, headers=csrf)
    assert hidden.status_code == 404


def test_one_evaluation_shape_for_reports_and_registered_models(client: TestClient, db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO model_version (model_id, name, version, data_hash, metrics, eval_report, alias)"
            " VALUES ('a2-excl-helene@1.0', 'a2-excl-helene', '1.0', 'x', '{}',"
            " 'evals/reports/outage_loso_v3.json', 'serving') ON CONFLICT DO NOTHING"
        )
    login(client, "ml_01")
    v3 = json.loads((ROOT / "evals/reports/outage_loso_v3.json").read_text(encoding="utf-8"))
    named = client.get("/api/models/outage_loso_v3/evaluation").json()
    model = client.get("/api/models/a2-excl-helene/evaluation").json()
    for body in (named, model):
        assert body["report_name"] == "outage_loso_v3" and body["metrics"] == v3["metrics"]
        assert body["provenance"]["source"] == "evals/reports/outage_loso_v3.json"
        assert isinstance(body["caveats"], list)
    assert model["name"] == "a2-excl-helene" and model["serving"]["alias"] == "serving"
    assert model["card"] is not None and "alphas" in model["card"]
    metrics = {
        m["metric"].rsplit(".", 2)[-2] + "." + m["metric"].rsplit(".", 1)[-1] for m in model["metrics"]
    }
    assert {"S5.pooled_forecast_over_observed", "M1.median_county_mae_ratio_vs_b3"} <= metrics


def test_outage_publisher_registers_the_v3_report() -> None:
    from sgw.models.outage import publisher

    assert publisher.EVAL_REPORT == "evals/reports/outage_loso_v3.json"
    assert (ROOT / publisher.EVAL_REPORT).is_file()
