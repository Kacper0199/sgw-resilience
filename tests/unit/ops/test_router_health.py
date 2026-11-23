"""Ops routes over HTTP on a seeded database: K3 coverage, Health reads (freshness, runs, DQ, lineage, model
cards, LLM usage), and the control routes' status codes and headers."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from sgw.api.app import app_routes, create_app
from sgw.api.settings import ApiSettings
from sgw.contracts.api_models import contract_routes, missing_routes
from sgw.contracts.vocab import KillLevel
from sgw.ops import testkit as tk

Conn = psycopg.Connection[Any]
H = tk.h


def _kill(client: TestClient, level: str, user: str, *, step_up: bool = False, reason: str = "drill") -> Any:
    return client.post(
        "/api/control/kill", json={"kill_level": level, "reason": reason}, headers=H(user, step_up=step_up)
    )


def _mode(client: TestClient, mode: str, user: str) -> Any:
    return client.post("/api/control/mode", json={"degraded_mode": mode, "reason": "drill"}, headers=H(user))


@pytest.fixture
def client(db_url: str, conn: Conn) -> Iterator[TestClient]:
    with tk.client_for(db_url, tk.service()) as c:
        yield c


def test_every_k3_health_and_control_route_is_served_and_nothing_else() -> None:
    app = create_app(ApiSettings(database_url="postgresql://unused/unused", demo_mode=True))
    served = app_routes(app)
    prefixes = ("/api/feeds", "/api/pipeline", "/api/dq", "/api/models", "/api/control")
    assert missing_routes(served, prefixes=prefixes) == []
    assert not {r for r in served - contract_routes() if r[1].startswith(prefixes + ("/api/llm",))}


def test_reads_need_a_session(client: TestClient) -> None:
    for path in ("/api/feeds/health", "/api/pipeline/runs", "/api/control/kill", "/api/llm/usage"):
        assert client.get(path).status_code == 401


def test_pipeline_run_lineage_and_dq_end_to_end(
    client: TestClient, conn: Conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SGW_SCENARIO", "helene_micro")
    assert client.post("/api/pipeline/assets/observations/run", headers=H("audit_01")).status_code == 403
    assert client.post("/api/pipeline/assets/no.such/run", headers=H("ml_01")).status_code == 404
    run = client.post("/api/pipeline/assets/observations/run", headers=H("ml_01"))
    assert run.status_code == 202, run.text
    body = run.json()
    assert body["asset"] == "observations" and body["status"] in {"success", "partial"}
    runs = client.get("/api/pipeline/runs", headers=H("audit_01")).json()
    assert {"ingest.feeds", "observations"} <= {r["asset"] for r in runs}
    assert (
        client.get("/api/pipeline/runs?asset=observations&limit=1", headers=H("audit_01")).json()[0]["run_id"]
        == body["run_id"]
    )
    assets = {a["name"]: a for a in client.get("/api/pipeline/assets", headers=H("audit_01")).json()}
    assert assets["observations"]["upstream"] == ["ingest.feeds"]
    assert "observations" in assets["ingest.feeds"]["downstream"]
    assert assets["observations"]["freshness_limit_s"] == 900
    assert assets["observations"]["last_run"]["run_id"] == body["run_id"]
    assert assets["ingest.feeds"]["last_run"]["dq"]["checks"] >= 1
    checks = client.get("/api/dq/checks", headers=H("audit_01")).json()
    assert checks and {"check_id", "asset", "severity", "passed", "observed"} <= set(checks[0])
    failed = client.get("/api/dq/checks?failed=true", headers=H("audit_01")).json()
    assert all(not c["passed"] for c in failed)
    feeds = client.get("/api/feeds/health", headers=H("audit_01")).json()
    assert feeds and all(
        set(f)
        == {
            "source_id",
            "display_name",
            "feed_mode",
            "ingest_lag_s",
            "product_age_s",
            "freshness_limit_s",
            "stale",
            "measured_by",
            "status",
        }
        for f in feeds
    )
    assert [f["stale"] for f in feeds] == sorted((f["stale"] for f in feeds), reverse=True)


def test_feed_without_recorded_lag_is_stale_never_current(client: TestClient, conn: Conn) -> None:
    conn.execute(
        "INSERT INTO adapter_health (source_id, feed_mode, freshness_limit_s)"
        " VALUES ('lims', 'replay', 86400)"
        " ON CONFLICT (source_id) DO UPDATE SET ingest_lag_s = NULL"
    )
    feeds = {f["source_id"]: f for f in client.get("/api/feeds/health", headers=H("exec_01")).json()}
    assert feeds["lims"]["stale"] is True


def test_model_cards_and_evaluation(client: TestClient, conn: Conn) -> None:
    conn.execute(
        "INSERT INTO model_version (model_id, name, version, data_hash, metrics, eval_report, alias)"
        " VALUES ('outage-lgbm@1.0', 'outage-lgbm', '1.0', 'sha256:abc', '{\"loso.helene.mae\": 1.0}',"
        " 'evals/reports/outage_loso.json', 'serving') ON CONFLICT DO NOTHING"
    )
    cards = client.get("/api/models", headers=H("ml_01")).json()
    assert {
        "name": "outage-lgbm",
        "version": "1.0",
        "alias": "serving",
        "data_hash": "sha256:abc",
        "eval_report": "evals/reports/outage_loso.json",
    } in cards
    ev = client.get("/api/models/outage-lgbm/evaluation", headers=H("ml_01"))
    assert ev.status_code == 200
    report = ev.json()["eval_report"]
    assert report["path"] == "evals/reports/outage_loso.json" and report["metrics"]
    assert all({"metric", "value"} <= set(m) for m in report["metrics"])
    assert client.get("/api/models/unknown/evaluation", headers=H("ml_01")).status_code == 404
    assert client.get("/api/models/..%2F..%2Fetc/evaluation", headers=H("ml_01")).status_code == 404


def test_evaluation_never_reads_outside_the_reports_folder(client: TestClient, conn: Conn) -> None:
    conn.execute(
        "INSERT INTO model_version (model_id, name, version, data_hash, eval_report, alias)"
        " VALUES ('sly@1', 'sly', '1', 'x', '../../../../etc/passwd', 'serving') ON CONFLICT DO NOTHING"
    )
    body = client.get("/api/models/sly/evaluation", headers=H("ml_01")).json()
    assert body["eval_report"]["path"] is None and body["eval_report"]["metrics"] == []


def _llm_call(conn: Conn, i: int, **kw: Any) -> None:
    row = {
        "call_id": f"call-ops-{i}",
        "ts": datetime(2026, 11, 20, 1, 0, tzinfo=UTC) + timedelta(minutes=i),
        "mode": "replay",
        "billed": False,
        "purpose": "demo",
        "node": "sitrep.draft",
        "model": "claude-haiku",
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_usd_micros": 0,
        "latency_ms": 100 * (i + 1),
        "request_hash": hashlib.sha256(f"r{i}".encode()).hexdigest(),
        "decision": "allow",
        **kw,
    }
    cols = ", ".join(row)
    conn.execute(
        f"INSERT INTO llm_call ({cols}) VALUES ({', '.join(['%s'] * len(row))})",  # noqa: S608
        tuple(row.values()),
    )


def test_llm_usage_groups_costs_and_counts(client: TestClient, conn: Conn) -> None:
    conn.execute("DELETE FROM llm_call WHERE call_id LIKE 'call-ops-%'")
    _llm_call(conn, 0)
    _llm_call(conn, 1)
    _llm_call(conn, 2, mode="live", billed=True, purpose="dev", cost_usd_micros=1_250, run_id="RUN-KESTREL-1")
    _llm_call(conn, 3, mode="live", billed=False, purpose="dev", decision="deny", run_id="RUN-KESTREL-1")
    usage = client.get("/api/llm/usage?group_by=purpose,mode", headers=H("admin_01")).json()
    assert usage["group_by"] == ["purpose", "mode"]
    rows = {(r["purpose"], r["mode"]): r for r in usage["rows"]}
    assert rows[("demo", "replay")]["calls"] == 2 and rows[("demo", "replay")]["replay_calls"] == 2
    assert rows[("dev", "live")]["billed_calls"] == 1 and rows[("dev", "live")]["denied_calls"] == 1
    assert rows[("dev", "live")]["cost_usd"] == 0.00125
    assert usage["total"]["calls"] == 4 and usage["total"]["input_tokens"] == 400
    assert usage["total"]["latency_p95_ms"] == 400
    one_run = client.get("/api/llm/usage?run_id=RUN-KESTREL-1", headers=H("admin_01")).json()
    assert one_run["total"]["calls"] == 2
    hostile = client.get("/api/llm/usage?group_by=purpose;drop table llm_call", headers=H("admin_01"))
    assert hostile.status_code == 200 and hostile.json()["group_by"] == ["purpose"]


def test_control_routes_codes_and_restore_header(client: TestClient) -> None:
    assert client.get("/api/control/kill", headers=H("audit_01")).json()["kill_level"] == "K0"
    denied = _kill(client, "K1", "ml_01")
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "KILL_TRIGGER_DENIED"
    pulled = _kill(client, "K2", "exec_01")
    assert pulled.status_code == 200 and pulled.json()["degraded_mode"] == "M2"
    restore = {"kill_level": "K0", "reason": "drill over, cause none"}
    no_step_up = client.post("/api/control/kill", json=restore, headers=H("ic_01"))
    assert no_step_up.status_code == 403 and no_step_up.json()["error"]["code"] == "STEP_UP_REQUIRED"
    first = client.post("/api/control/kill", json=restore, headers=H("ic_01", step_up=True))
    assert first.status_code == 202 and first.json()["kill_level"] == "K2"
    header = first.headers["X-SGW-Restore"]
    assert header.startswith("pending; id=RST-") and "awaiting=compliance" in header
    assert "pending" in client.get("/api/control/kill", headers=H("audit_01")).headers["X-SGW-Restore"]
    caps = client.get("/api/control/capabilities", headers=H("audit_01")).json()
    assert caps["pending_restore"]["requested_function"] == "command"
    assert caps["capabilities"]["llm_calls"] is False
    done = client.post("/api/control/kill", json=restore, headers=H("wtr_comp_01", step_up=True))
    assert done.status_code == 200 and done.json()["kill_level"] == KillLevel.K0.value
    assert sorted(done.json()["updated_by"]) == ["ic_01", "wtr_comp_01"]
    assert client.get("/api/control/mode", headers=H("audit_01")).json()["degraded_mode"] == "M0"


def test_mode_route(client: TestClient) -> None:
    up = _mode(client, "M1", "ops_dm_01")
    assert up.status_code == 200 and up.json()["degraded_mode"] == "M1"
    down = _mode(client, "M0", "ops_dm_01")
    assert down.status_code == 403
    bad = _mode(client, "M9", "ic_01")
    assert bad.status_code == 422


def test_llm_usage_and_run_errors_only_for_platform_command_executive(client: TestClient, conn: Conn) -> None:
    assert client.get("/api/llm/usage", headers=H("ops_dm_01")).status_code == 403
    assert client.get("/api/llm/usage", headers=H("ml_01")).status_code == 403
    for user in ("admin_01", "ic_01", "exec_01"):
        assert client.get("/api/llm/usage", headers=H(user)).status_code == 200
    conn.execute(
        "INSERT INTO pipeline_run (run_id, asset, status, started_at, error, code_version)"
        " VALUES ('ops.err.000001', 'observations', 'failed', now(), 'psycopg: password authentication', 'x')"
        " ON CONFLICT DO NOTHING"
    )
    by_audit = {r["run_id"]: r for r in client.get("/api/pipeline/runs", headers=H("audit_01")).json()}
    assert by_audit["ops.err.000001"]["error"] == "withheld"
    by_admin = {r["run_id"]: r for r in client.get("/api/pipeline/runs", headers=H("admin_01")).json()}
    assert by_admin["ops.err.000001"]["error"] == "psycopg: password authentication"


def test_adapters_get_only_feed_fault_flags() -> None:
    from sgw.api.routers.ops import adapter_env

    env = {
        "FAULT_FEED_GAP": "oms",
        "SGW_DATABASE_URL": "postgresql://x",
        "ANTHROPIC_API_KEY": "k",
        "PATH": "/b",
    }
    assert adapter_env(env) == {"FAULT_FEED_GAP": "oms"}
