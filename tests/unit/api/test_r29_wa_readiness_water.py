"""WA over HTTP with the real app lifespan on a seeded scratch database: the owner of a pre-season
readiness check records its result (audited, at the pre-season review, refused for anyone else),
`getMyPermissions` names the checks a person may record, and the boil-water register lists every zone's
notice with its stage and clean sample count (`SGW_ZONE_RULES`)."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from sgw.agent.tools.reads import DbReads
from sgw.api.app import create_app
from sgw.api.readmodels import readiness as readiness_rm
from sgw.api.readmodels import water as water_rm
from sgw.api.settings import ApiSettings
from sgw.api.users import seed_users
from sgw.approval import audit
from sgw.approval import testkit as tk
from sgw.contracts.api_models import BwaRegister, Permissions, ReadinessItem
from sgw.contracts.vocab import ApprovalFunction, ProposalState
from sgw.models.clocks import zone_cases
from sgw.rules import zones

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
PASSWORD = "r29wa-" + secrets.token_hex(12)
LOAD_TEST = "DC-RDY-GEN-PS52-LOADTEST"
LAUREL = "WZ-PS23-LAURELSPUR"
CEDAR = "WZ-PS17-CEDARFALL"
COPPER = "WZ-PS38-COPPERLEAF"
DEER = "WZ-PS52-DEERWATER"
RULE_ZONES = (LAUREL, COPPER, DEER)


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: routes need Postgres
    from sgw.approval.seed import run_seed

    with tk.scratch_database("sgw_r29wa_t") as url:
        run_seed(url, use_default_ledger=False)
        seed_users(url, PASSWORD)
        yield url


@pytest.fixture(scope="module")
def client(db_url: str) -> Iterator[TestClient]:
    settings = ApiSettings(
        database_url=db_url, demo_mode=True, cookie_secure=False, login_ip_burst=1000, login_user_burst=1000
    )
    with TestClient(create_app(settings)) as c:
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


def record(c: TestClient, user_id: str, item_id: str, body: dict[str, Any]) -> Any:
    csrf = login(c, user_id)
    return c.post(f"/api/readiness/{item_id}", json=body, headers=csrf)


def listed(c: TestClient) -> dict[str, ReadinessItem]:
    login(c, "plan_etr_01")
    items = (ReadinessItem.model_validate(x) for x in c.get("/api/readiness").json())
    return {i.item_id: i for i in items}


def results(db_url: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        return conn.execute(
            "SELECT item_id, status, recorded_by FROM readiness_result ORDER BY result_id"
        ).fetchall()


@pytest.fixture
def clean_results(db_url: str) -> Iterator[None]:
    yield
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("DELETE FROM readiness_result")


# ---- readiness write ---------------------------------------------------------------------------------------


@pytest.mark.usefixtures("clean_results")
def test_the_owner_records_a_check_ready_at_the_pre_season_review(client: TestClient, db_url: str) -> None:
    before = listed(client)
    assert before[LOAD_TEST].status == "gap" and before[LOAD_TEST].result is None
    r = record(
        client,
        "wtr_lead_01",
        LOAD_TEST,
        {
            "status": "ready",
            "note": "Load test passed at 100% for 2 h",
            "evidence_url": "https://eam.example/wo/52",
        },
    )
    assert r.status_code == 200, r.text
    item = ReadinessItem.model_validate(r.json())
    review = readiness_rm.review_time()
    assert item.status == "ready" and item.result is not None
    assert item.result.status == "ready" and item.result.recorded_by == "wtr_lead_01"
    assert item.result.reviewed_at_utc == review == item.evaluated_at_utc
    assert item.result.evidence_url == "https://eam.example/wo/52"
    now = listed(client)
    assert now[LOAD_TEST].status == "ready"
    assert (
        sum(i.status == "ready" for i in now.values())
        == sum(i.status == "ready" for i in before.values()) + 1
    )
    with psycopg.connect(db_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT actor_id, subject, occurred_at, payload FROM audit_event"
            " WHERE kind = 'readiness_recorded' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[0] == "wtr_lead_01" and row[1] == f"readiness:{LOAD_TEST}" and row[2] == review
        assert (
            row[3]["status"] == "ready"
            and row[3]["from"] == "gap"
            and row[3]["function"] == "water_operations"
        )
        assert audit.verify(conn).first_bad_seq is None


@pytest.mark.usefixtures("clean_results")
def test_not_ready_is_a_gap_and_waived_is_its_own_status_and_the_latest_result_wins(
    client: TestClient,
) -> None:
    r = record(client, "wtr_lead_01", LOAD_TEST, {"status": "waived", "note": "Generator replaced in June"})
    assert (
        r.status_code == 200 and r.json()["status"] == "waived" and r.json()["result"]["evidence_url"] is None
    )
    r = record(client, "wtr_lead_01", LOAD_TEST, {"status": "not_ready", "note": "Transfer switch failed"})
    assert r.status_code == 200 and r.json()["status"] == "gap"
    assert r.json()["result"]["note"] == "Transfer switch failed"


@pytest.mark.usefixtures("clean_results")
@pytest.mark.parametrize(
    ("user_id", "code"), [("log_01", "READINESS_NOT_OWNER"), ("ic_01", "READINESS_NOT_OWNER")]
)
def test_anyone_but_the_owner_function_is_refused(
    client: TestClient, db_url: str, user_id: str, code: str
) -> None:
    r = record(client, user_id, LOAD_TEST, {"status": "ready", "note": "Looks fine to me"})
    assert r.status_code == 403 and r.json()["error"]["code"] == code
    assert results(db_url) == []


def test_a_read_only_role_is_refused(client: TestClient, db_url: str) -> None:
    r = record(client, "audit_01", LOAD_TEST, {"status": "ready", "note": "Looks fine to me"})
    assert r.status_code == 403
    assert results(db_url) == []


@pytest.mark.parametrize(
    "body",
    [
        {"status": "ready", "note": "ok"},
        {"status": "done", "note": "Load test passed"},
        {"status": "ready", "note": "Load test passed", "evidence_url": "javascript:alert(1)"},
        {"status": "ready", "note": "x" * 301},
    ],
)
def test_invalid_results_are_rejected(client: TestClient, db_url: str, body: dict[str, Any]) -> None:
    assert record(client, "wtr_lead_01", LOAD_TEST, body).status_code == 422
    assert results(db_url) == []


def test_an_unknown_check_is_404(client: TestClient) -> None:
    r = record(client, "wtr_lead_01", "DC-RDY-NOPE", {"status": "ready", "note": "Load test passed"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "READINESS_NOT_FOUND"


@pytest.mark.parametrize(
    ("user_id", "function"),
    [
        ("wtr_lead_01", ApprovalFunction.WATER_OPERATIONS),
        ("log_01", ApprovalFunction.LOGISTICS),
        ("ops_dm_01", ApprovalFunction.OPERATIONS),
        ("ic_01", None),
        ("audit_01", None),
    ],
)
def test_permissions_name_the_checks_the_person_owns(
    client: TestClient, user_id: str, function: ApprovalFunction | None
) -> None:
    login(client, user_id)
    perms = Permissions.model_validate(client.get("/api/me/permissions").json())
    owned = sorted(i.item_id for i in readiness_rm.readiness() if i.owner_function is function)
    assert sorted(perms.readiness_record) == owned
    assert (len(owned) > 0) == (function is not None)


@pytest.mark.usefixtures("clean_results")
def test_the_copilot_reads_the_recorded_result(client: TestClient, db_url: str) -> None:
    assert record(client, "wtr_lead_01", LOAD_TEST, {"status": "ready", "note": "Passed"}).status_code == 200
    items = asyncio.run(DbReads(db_url).readiness())
    assert next(i for i in items if i.item_id == LOAD_TEST).status == "ready"


# ---- boil-water register: every zone's notice ------------------------------------------------------------


def notice(state: ProposalState, pid: str = "PRP-N", case: str = "DC-N") -> water_rm.BwaProposal:
    return water_rm.BwaProposal(pid, case, state)


def known_issue(zone_id: str) -> datetime:
    return next(h.known_at for h in zones.bwa_issues(zones.world()) if h.target_ids == (zone_id,))


def test_without_the_zone_rules_only_cedarfall_is_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(zone_cases.FLAG_ENV, raising=False)
    reg = water_rm.register(_utc("2024-10-02T00:00:00Z"), {})
    assert {a.zone_id for a in reg.advisories} == {CEDAR}


def test_zone_rule_notices_appear_once_the_pressure_loss_is_known(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(zone_cases.FLAG_ENV, "1")
    for zone_id in RULE_ZONES:
        at = known_issue(zone_id)
        just_before = water_rm.register(datetime.fromtimestamp(at.timestamp() - 60, UTC), {})
        assert zone_id not in {a.zone_id for a in just_before.advisories}
        row = next(a for a in water_rm.register(at, {}).advisories if a.zone_id == zone_id)
        hit = next(h for h in zones.bwa_issues(zones.world()) if h.target_ids == (zone_id,))
        assert row.kind == "pressure_loss" and row.status == "due" and row.stage == "due"
        assert row.advisory_id == f"BWA-{zone_id}-PRESSURELOSS" and row.decision_case_id == hit.case_id
        assert row.clause_ids == [hit.params["clause"], hit.params["floor_clause"]]
        assert row.due_utc == at and row.samples_needed == 2


def test_clean_samples_count_the_lims_results_reported_by_now() -> None:
    w = zones.world()
    for zone_id in (CEDAR, *RULE_ZONES):
        clean = sorted(s.known_utc for s in w.samples if s.zone_id == zone_id and s.absent)
        assert len(clean) == 2
        assert water_rm.clean_samples(zone_id, datetime.fromtimestamp(clean[0].timestamp() - 1, UTC)) == 0
        assert water_rm.clean_samples(zone_id, clean[0]) == 1
        assert water_rm.clean_samples(zone_id, clean[1]) == 2


def test_the_stage_follows_the_notice_the_samples_and_the_lift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(zone_cases.FLAG_ENV, "1")
    w = zones.world()
    first, second = sorted(s.known_utc for s in w.samples if s.zone_id == LAUREL and s.absent)

    def row(at: datetime, n: ProposalState | None, lift: ProposalState | None) -> Any:
        reg = water_rm.register(
            at,
            {LAUREL: notice(n) if n else None},
            {LAUREL: notice(lift, "PRP-L", "DC-L") if lift else None},
        )
        return next(a for a in reg.advisories if a.zone_id == LAUREL)

    at = known_issue(LAUREL)
    assert (row(at, ProposalState.PROPOSED, None).status, row(at, ProposalState.PROPOSED, None).stage) == (
        "proposed",
        "due",
    )
    assert row(at, ProposalState.APPROVED, None).stage == "issued"
    issued = row(first, ProposalState.APPROVED, None)
    assert (issued.stage, issued.clean_samples) == ("samples", 1)
    waiting = row(second, ProposalState.APPROVED, ProposalState.PROPOSED)
    assert (waiting.stage, waiting.clean_samples, waiting.lift_proposal_id) == ("lift_decision", 2, "PRP-L")
    assert waiting.lift_decision_case_id == "DC-L"
    lifted = row(second, ProposalState.APPROVED, ProposalState.APPROVED)
    assert (lifted.stage, lifted.status) == ("lifted", "lifted")
    expired = row(second, ProposalState.APPROVED, ProposalState.EXPIRED)
    assert expired.stage == "samples"


def test_the_route_lists_every_zone_with_its_lift(
    client: TestClient, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(zone_cases.FLAG_ENV, "1")
    with psycopg.connect(db_url, autocommit=True) as conn:
        source = conn.execute("SELECT proposal_id FROM proposal ORDER BY created_at LIMIT 1").fetchone()
        assert source is not None
        for pid, action, state in (
            ("PRP-R29WA-BWN", "boil_water_notice", "proposed"),
            ("PRP-R29WA-LIFT", "lift_boil_water_notice", "proposed"),
        ):
            conn.execute(
                "INSERT INTO proposal (proposal_id, decision_case_id, incident_id, action_type, params,"
                " targets, risk_band, tier, required_functions, state, action_hash, policy_version,"
                " initiator_kind, proposed_by, region_id, domain)"
                " SELECT %s, decision_case_id, incident_id, %s, '{}'::jsonb, ARRAY[%s], risk_band, 'T3',"
                " '{water_operations,compliance}', %s, action_hash, policy_version, 'system_rule',"
                " 'system:rule:bwa_pressure_loss', region_id, 'water' FROM proposal WHERE proposal_id = %s",
                (pid, action, LAUREL, state, source[0]),
            )
    try:
        seek(client, "2024-10-02T00:00:00Z")
        login(client, "ops_dm_01")
        reg = BwaRegister.model_validate(client.get("/api/water/advisories").json())
        by_zone = {a.zone_id: a for a in reg.advisories if a.kind == "pressure_loss"}
        assert set(by_zone) == {CEDAR, *RULE_ZONES}
        laurel = by_zone[LAUREL]
        assert (laurel.status, laurel.proposal_id, laurel.stage) == (
            "proposed",
            "PRP-R29WA-BWN",
            "lift_decision",
        )
        assert (laurel.lift_proposal_id, laurel.clean_samples, laurel.samples_needed) == (
            "PRP-R29WA-LIFT",
            2,
            2,
        )
        assert reg.forecasts_withheld and by_zone[DEER].stage == "due"
    finally:
        with psycopg.connect(db_url, autocommit=True) as conn:
            conn.execute("DELETE FROM proposal WHERE proposal_id LIKE 'PRP-R29WA-%'")
