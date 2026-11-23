"""Over HTTP with the real app lifespan on a scratch database seeded like `sgw seed` (K18 users with a
password, the Helene decision cases): water zones, the BWA register and rules, anomalies, policies, readiness
and the admin views. Every value check is traced to the engine or file it comes from."""

from __future__ import annotations

import json
import secrets
import statistics
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient

from sgw.agent.graphs import water as graph
from sgw.api.app import app_routes, create_app
from sgw.api.readmodels import anomalies as anomalies_rm
from sgw.api.readmodels import readiness as readiness_rm
from sgw.api.readmodels import water as water_rm
from sgw.api.settings import ApiSettings
from sgw.api.users import seed_users
from sgw.approval import testkit as tk
from sgw.common import numbers as numbers_mod
from sgw.contracts.api_models import (
    AiConfig,
    AnomalyItem,
    BwaRegister,
    BwaRules,
    Me,
    PolicyParam,
    ReadinessItem,
    UserApprovalRights,
    WaterZone,
    contract_routes,
    missing_routes,
)
from sgw.contracts.vocab import NumberKind

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
PASSWORD = "beui2b-" + secrets.token_hex(12)
READS = (
    "/api/water/zones",
    "/api/water/advisories",
    "/api/water/rules",
    "/api/anomalies",
    "/api/policies",
    "/api/readiness",
    "/api/admin/users",
    "/api/admin/approval-rights",
    "/api/admin/ai-config",
)
ADMIN_READS = READS[-3:]
BEFORE_N = "2024-09-26T08:00:00Z"
AFTER_N1 = "2024-09-26T16:00:00Z"
AFTER_LOSS = "2024-09-27T20:00:00Z"
DAY_TWO = "2024-09-28T00:00:00Z"


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    from sgw.approval.seed import run_seed

    with tk.scratch_database("sgw_beui2b_t") as url:
        run_seed(url, use_default_ledger=False)
        seed_users(url, PASSWORD)
        yield url


@pytest.fixture(scope="module")
def client(db_url: str) -> Iterator[TestClient]:
    settings = ApiSettings(
        database_url=db_url,
        demo_mode=True,
        cookie_secure=False,
        login_ip_burst=1000,
        login_user_burst=1000,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def login(c: TestClient, user_id: str) -> None:
    r = c.post("/api/auth/login", json={"user_id": user_id, "password": PASSWORD})
    assert r.status_code == 200, r.text


def seek(c: TestClient, at: str) -> None:
    login(c, "ic_01")
    csrf = {"X-CSRF-Token": c.cookies["sgw_csrf"]}
    assert c.post("/api/scenario", json={"action": "pause"}, headers=csrf).status_code == 200
    r = c.post("/api/scenario", json={"action": "seek", "scenario_time": at}, headers=csrf)
    assert r.status_code == 200, r.text


def get(c: TestClient, path: str, user: str, at: str | None = None) -> Any:
    if at is not None:
        seek(c, at)
    login(c, user)
    return c.get(path)


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def test_routes_are_mounted_and_in_the_contract() -> None:
    app = create_app(ApiSettings(database_url="postgresql://unused/unused", demo_mode=True))
    served = app_routes(app)
    assert {("GET", p) for p in READS} <= served
    assert {("GET", p) for p in READS} <= contract_routes()
    k3 = ("/api/water", "/api/anomalies", "/api/policies", "/api/readiness", "/api/admin/users")
    assert missing_routes(served, prefixes=k3) == []
    for path in ("/api/llm/usage", "/api/control/capabilities"):
        assert ("GET", path) in served
    assert ("POST", "/api/runs/{run_id}/resume") in served


def test_every_read_needs_a_session(client: TestClient) -> None:
    client.cookies.clear()
    for path in READS:
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json()["error"]["code"]


def test_zones_read_the_scada_fixture_at_the_scenario_time(client: TestClient) -> None:
    r = get(client, "/api/water/zones", "ops_dm_01", AFTER_LOSS)
    assert r.status_code == 200
    zones = {z.zone_id: z for z in (WaterZone.model_validate(x) for x in r.json())}
    assert set(zones) == set(water_rm.zone_ids())
    ps17 = zones["WZ-PS17-CEDARFALL"]
    hospital = water_rm.series()["PT-HSP-TALLOWBRANCH:service_pressure"]
    assert ps17.pressure_psi_x10 == round(hospital.at_or_before(_utc(AFTER_LOSS).timestamp()) * 10)  # type: ignore[operator]
    assert ps17.floor_psi_x10 == round(float(numbers_mod.value("sc_pressure_floor_psi")) * 10)
    assert ps17.critical_facility_ids == ["HSP-AIK-TALLOWBRANCH"]
    assert ps17.on_backup_power is True
    assert ps17.pressure_psi_x10 < ps17.floor_psi_x10
    assert "rule_id=rule.sc_service_pressure_normal" in r.headers["x-sgw-provenance"]
    assert "as_of=2024-09-27T20:00:00Z" in r.headers["x-sgw-provenance"]
    again = client.get("/api/water/zones", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


def _engine_breach_ppm(advisory: str) -> int:
    table = water_rm.member_table()
    members = table["advisories"][advisory]["members"]
    residual = graph.generator_residual_p(float(numbers_mod.value("policy_water_continuity_horizon_h")))
    lag = float(table["lead_min"]["generator.hookup_lead_min"])
    return round(graph.breach_p_at(members, lag, residual) * 1_000_000)


def test_register_shows_only_issued_advisories_and_traces_to_the_twin(client: TestClient) -> None:
    early = BwaRegister.model_validate(get(client, "/api/water/advisories", "wtr_lead_01", BEFORE_N).json())
    pre = early.advisories[0]
    assert pre.kind == "pre_landfall" and pre.assessments == [] and pre.status == "not_due"
    r = get(client, "/api/water/advisories", "wtr_lead_01", AFTER_N1)
    reg = BwaRegister.model_validate(r.json())
    row = reg.advisories[0]
    assert [a.advisory for a in row.assessments] == ["N", "N+1"]
    assert [a.breach_p_ppm for a in row.assessments] == [_engine_breach_ppm("N"), _engine_breach_ppm("N+1")]
    p_loss = statistics.fmean(
        float(m["p_loss_final"]) for m in water_rm.member_table()["advisories"]["N+1"]["members"]
    )
    assert row.assessments[1].power_loss_p_ppm == round(p_loss * 1_000_000)
    assert row.policy_value_ppm == round(float(numbers_mod.value("policy_pre_landfall_breach_p")) * 1_000_000)
    assert row.assessments[1].at_or_above_policy is (row.assessments[1].breach_p_ppm >= row.policy_value_ppm)
    assert row.status == "due" and row.due_utc == graph.LANDFALL_UTC
    assert row.clause_ids == ["SC-A2", "SC-P1"] and row.classification.value == "C2"
    assert row.provenance.model_id == "water_twin.zone_drain_critical_node"
    assert row.sensitivity[-1].breach_p_ppm == row.assessments[1].breach_p_ppm


def test_register_pressure_loss_row_after_the_floor_is_breached(client: TestClient) -> None:
    reg = BwaRegister.model_validate(get(client, "/api/water/advisories", "wtr_comp_01", AFTER_LOSS).json())
    loss = next(a for a in reg.advisories if a.kind == "pressure_loss")
    floor = float(numbers_mod.value("sc_pressure_floor_psi"))
    hospital = water_rm.series()["PT-HSP-TALLOWBRANCH:service_pressure"]
    first = next(t for t, v in zip(hospital.t, hospital.value, strict=True) if float(v) < floor)
    assert loss.due_utc == datetime.fromtimestamp(float(first), tz=UTC)
    assert loss.clause_ids == ["SC-A1", "SC-P1"] and loss.status == "due"


def test_register_notices_are_read_by_every_reader_and_c2_forecasts_only_by_water(client: TestClient) -> None:
    """DR Blocker 2: the duty manager got 403 and the page read it as "no notice due". The notice status
    is shown to every signed-in reader; the C2 zone forecasts behind it stay with the water domain."""
    water = BwaRegister.model_validate(get(client, "/api/water/advisories", "wtr_lead_01", AFTER_N1).json())
    other = BwaRegister.model_validate(get(client, "/api/water/advisories", "ops_dm_01", AFTER_N1).json())
    assert not water.forecasts_withheld and other.forecasts_withheld
    assert [(a.advisory_id, a.status, a.due_utc) for a in other.advisories] == [
        (a.advisory_id, a.status, a.due_utc) for a in water.advisories
    ]
    assert any(a.assessments for a in water.advisories)
    assert all(not a.assessments and not a.sensitivity for a in other.advisories)


def test_register_status_follows_the_latest_bwa_proposal(client: TestClient, db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        source = conn.execute("SELECT proposal_id FROM proposal ORDER BY created_at LIMIT 1").fetchone()
        assert source is not None
        conn.execute(
            "INSERT INTO proposal (proposal_id, decision_case_id, incident_id, action_type, params, targets,"
            " risk_band, tier, required_functions, state, action_hash, policy_version, initiator_kind,"
            " proposed_by, region_id, domain)"
            " SELECT 'PRP-BEUI2B-BWN', decision_case_id, incident_id, 'boil_water_notice', '{}'::jsonb,"
            " ARRAY['WZ-PS17-CEDARFALL'], risk_band, 'T3', '{water_operations,compliance}', 'proposed',"
            " action_hash, policy_version, 'system_rule', 'system:rule:bwa_pre_landfall', region_id, 'water'"
            " FROM proposal WHERE proposal_id = %s",
            (source[0],),
        )
    try:
        reg = BwaRegister.model_validate(get(client, "/api/water/advisories", "wtr_lead_01", AFTER_N1).json())
        row = reg.advisories[0]
        assert row.status == "proposed" and row.proposal_id == "PRP-BEUI2B-BWN"
    finally:
        with psycopg.connect(db_url, autocommit=True) as conn:
            conn.execute("DELETE FROM proposal WHERE proposal_id = 'PRP-BEUI2B-BWN'")


def test_rules_are_the_wp24_rule_book(client: TestClient) -> None:
    r = get(client, "/api/water/rules", "plan_etr_01")
    assert r.status_code == 200
    rules = BwaRules.model_validate(r.json())
    raw = yaml.safe_load((water_rm.REPO / water_rm.RULES_SOURCE).read_text(encoding="utf-8"))
    assert [c.clause_id for c in rules.clauses] == list(raw["clauses"])
    assert len(rules.clauses) == 15
    sc_a2 = next(c for c in rules.clauses if c.clause_id == "SC-A2")
    assert sc_a2.citation == raw["clauses"]["SC-A2"]["citation"] and sc_a2.sop is None
    assert next(c for c in rules.clauses if c.clause_id == "SC-P1").sop.section == "5.1"  # type: ignore[union-attr]


def test_anomalies_are_the_detector_alarms_known_by_the_scenario_time(client: TestClient) -> None:
    assert get(client, "/api/anomalies", "wtr_lead_01", AFTER_N1).json() == []
    r = get(client, "/api/anomalies", "wtr_lead_01", DAY_TWO)
    items = [AnomalyItem.model_validate(x) for x in r.json()]
    alarms = json.loads(anomalies_rm.REPORT_FILE.read_text(encoding="utf-8"))["results"]["helene_dev"][
        "alarms"
    ]
    known = [a for a in alarms if _utc(a["detected_utc"]) <= _utc(DAY_TWO)]
    assert len(items) == len(known) == 4
    assert [i.detected_at for i in items] == sorted((i.detected_at for i in items), reverse=True)
    newest = max(known, key=lambda a: a["detected_utc"])
    assert items[0].entity_id == newest["devices"][0] and items[0].anomaly_class == newest["kind"]
    assert items[0].score_ppm == round(newest["score"] * 1_000_000)
    assert len({i.score_ppm for i in items}) > 1 and all(0 < i.score_ppm <= 1_000_000 for i in items)
    assert "model_id=anomaly.a7_a8" in r.headers["x-sgw-provenance"]


def test_policies_are_every_k10_policy_parameter(client: TestClient) -> None:
    r = get(client, "/api/policies", "exec_01")
    items = {p.key: p for p in (PolicyParam.model_validate(x) for x in r.json())}
    expected = {k for k, e in numbers_mod.numbers().items() if e.kind is NumberKind.POLICY}
    assert set(items) == expected
    assert items["policy_pre_landfall_breach_p"].value == numbers_mod.value("policy_pre_landfall_breach_p")
    assert all(p.chip == "Assumed SGW policy" for p in items.values())


def test_readiness_items_carry_the_wp22_clocks(client: TestClient) -> None:
    r = get(client, "/api/readiness", "log_01")
    items = [ReadinessItem.model_validate(x) for x in r.json()]
    cases = {c["case"]["decision_case_id"]: c["case"] for c in readiness_rm.cases()["cases"]}
    assert {i.item_id for i in items} == set(cases)
    load_test = next(i for i in items if i.item_id == "DC-RDY-GEN-PS52-LOADTEST")
    assert load_test.due_utc == _utc(cases["DC-RDY-GEN-PS52-LOADTEST"]["effective_decide_by_utc"])
    assert load_test.status == "gap" and load_test.owner_function.value == "water_operations"
    assert "readiness_cases.json" in r.headers["x-sgw-provenance"]


def test_admin_views_are_platform_admin_only(client: TestClient) -> None:
    for path in ADMIN_READS:
        r = get(client, path, "ic_01")
        assert r.status_code == 403 and r.json()["error"]["code"] == "ADMIN_ONLY", path


def test_admin_users_and_approval_rights(client: TestClient) -> None:
    users = [Me.model_validate(x) for x in get(client, "/api/admin/users", "admin_01").json()]
    seeded = yaml.safe_load((water_rm.REPO / "data" / "seed" / "users.yaml").read_text(encoding="utf-8"))
    assert sorted(u.user_id for u in users) == sorted(u["user_id"] for u in seeded["users"])
    assert all(u.step_up_valid_until is None and u.demo_mode for u in users)
    rights = {
        r.user_id: r
        for r in (
            UserApprovalRights.model_validate(x)
            for x in get(client, "/api/admin/approval-rights", "admin_01").json()
        )
    }
    comp = {(a.action_type.value, a.role) for a in rights["wtr_comp_01"].may_approve}
    assert ("boil_water_notice", "approver") in comp
    assert rights["plan_etr_01"].can_approve is False and rights["plan_etr_01"].may_approve == []
    ic = {(a.action_type.value, a.role) for a in rights["ic_01"].may_approve}
    assert ("cross_domain_priority", "approver") in ic and rights["ic_01"].break_glass_eligible
    ops = {(a.action_type.value, a.role) for a in rights["ops_dm_01"].may_approve}
    assert ("set_event_type", "escalation_approver") in ops


def test_admin_ai_config_has_no_prompts_or_keys(client: TestClient) -> None:
    r = get(client, "/api/admin/ai-config", "admin_01")
    cfg = AiConfig.model_validate(r.json())
    raw = yaml.safe_load(
        (water_rm.REPO / "src" / "sgw" / "agent" / "llm_nodes.yaml").read_text(encoding="utf-8")
    )
    assert [n.node for n in cfg.nodes] == [n["node"] for n in raw["nodes"]]
    by = {n.node: n for n in cfg.nodes}
    assert by["investigate"].allowed_tools == [
        "get_decision_case",
        "get_water_status",
        "get_forecast",
        "search_procedures",
    ]
    assert by["narrate"].allowed_tools == [] and by["narrate"].model.value == raw["nodes"][0]["model"]
    body = r.text.lower()
    assert "sk-ant" not in body and 'prompt"' not in body and "output_schema" not in body
