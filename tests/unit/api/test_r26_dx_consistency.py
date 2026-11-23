"""DX through the real app: screens that report the same fact give the same answer.

- Forecast "Decisions affected" and Decisions list the same open decisions with the same Timing.
- Water zones name the station's own standby generator and its reported state, so a station with a generator
  is not reported as having no backup power.
- System health reads freshness at the replay clock: feed health and the freshness checks use one rule and
  never measure against data the scenario has not reached yet."""

from __future__ import annotations

import json
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from sgw.api.app import create_app
from sgw.api.settings import ApiSettings
from sgw.api.users import seed_users
from sgw.approval import testkit as tk
from sgw.approval.severity import QUEUE_OPEN_STATES
from sgw.contracts.api_models import (
    CrewItem,
    DqCheckOut,
    FeedHealthItem,
    PlanDiff,
    ProposalCard,
    WaterZone,
)
from sgw.models.clocks.ps17 import CASE_POWER, ps17_specs
from sgw.models.clocks.service import compute_queue
from sgw.models.clocks.store import save_queue

PASSWORD = "r26dx-" + secrets.token_hex(12)
CREWS_PROPOSAL = "PRP-CREW-AIK-0926A"
POWER_PROPOSAL = "PRP-R26DX-PS17-POWER"
AT_N1 = "2024-09-26T15:05:00Z"
N_ISSUED = datetime(2024, 9, 26, 9, 0, tzinfo=UTC)
N1_ISSUED = datetime(2024, 9, 26, 15, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[3]
NETWORK = json.loads((ROOT / "data" / "fixtures" / "helene" / "network.json").read_text("utf-8"))
INPUTS = json.loads(
    (Path(__file__).parents[1] / "models" / "clocks" / "data" / "wp06_helene_ps17_members.json").read_text(
        "utf-8"
    )
)
NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: consistency reads need Postgres
    from sgw.approval.seed import run_seed
    from sgw.models.outage.publisher import publish_tick
    from sgw.pipeline.replay import replay_scenario

    with tk.scratch_database("sgw_r26dx_t") as url:
        run_seed(url, use_default_ledger=False)
        seed_users(url, PASSWORD)
        with psycopg.connect(url, autocommit=True) as conn:
            replay_scenario(conn, "helene", env={})
            for issued in (N_ISSUED, N1_ISSUED):
                publish_tick(conn, issued)
            save_queue(conn, compute_queue(ps17_specs(INPUTS["advisories"]["N+1"], INPUTS)))
            columns = [
                r[0]
                for r in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'proposal'"
                    " AND column_name NOT IN ('proposal_id', 'decision_case_id', 'created_at')"
                    " AND is_generated = 'NEVER' ORDER BY ordinal_position"
                ).fetchall()
            ]
            listed = ", ".join(columns)
            conn.execute(
                f"INSERT INTO proposal (proposal_id, decision_case_id, created_at, {listed})"  # noqa: S608
                f" SELECT %s, %s, created_at + interval '1 minute', {listed} FROM proposal"
                " WHERE proposal_id = %s",
                (POWER_PROPOSAL, CASE_POWER, CREWS_PROPOSAL),
            )
        yield url


@pytest.fixture(scope="module")
def client(db_url: str) -> Iterator[TestClient]:
    settings = ApiSettings(
        database_url=db_url, demo_mode=True, cookie_secure=False, login_ip_burst=1000, login_user_burst=1000
    )
    with TestClient(create_app(settings)) as c:
        csrf = login(c, "ic_01")
        assert c.post("/api/scenario", json={"action": "pause"}, headers=csrf).status_code == 200
        r = c.post("/api/scenario", json={"action": "seek", "scenario_time": AT_N1}, headers=csrf)
        assert r.status_code == 200, r.text
        yield c


def login(c: TestClient, user_id: str) -> dict[str, str]:
    r = c.post("/api/auth/login", json={"user_id": user_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": c.cookies["sgw_csrf"]}


def card(c: TestClient, proposal_id: str) -> ProposalCard:
    r = c.get(f"/api/proposals/{proposal_id}")
    assert r.status_code == 200, r.text
    return ProposalCard.model_validate(r.json())


def test_plan_diff_names_the_open_decisions_with_the_timing_decisions_shows(client: TestClient) -> None:
    diff = PlanDiff.model_validate(client.get("/api/forecasts/outages/plan-diff").json())
    assert (diff.from_advisory, diff.to_advisory) == ("N", "N+1")
    open_by_case = {
        p["decision_case_id"]: p["proposal_id"]
        for p in client.get("/api/proposals").json()
        if p["state"] in QUEUE_OPEN_STATES
    }
    for action in diff.actions:
        expected = next((open_by_case[c] for c in action.decision_case_ids if c in open_by_case), None)
        assert action.proposal_id == expected, action.action_id
        assert action.timing is not None, action.action_id
        if action.proposal_id is not None:
            assert action.timing == card(client, action.proposal_id).case.timing
    affected = {a.proposal_id for a in diff.actions if a.proposal_id is not None}
    assert affected == {POWER_PROPOSAL}
    assert affected <= set(open_by_case.values())


def test_a_station_with_its_own_generator_is_not_without_backup(client: TestClient) -> None:
    body = client.get("/api/water/zones").json()
    zones = {z.pump_station_id: z for z in map(WaterZone.model_validate, body)}
    stations = NETWORK["named"]["pump_stations"]
    assert set(zones) == set(stations)
    for station_id, station in stations.items():
        assert zones[station_id].onsite_generator_id == station["onsite_generator"], station_id
    deerwater = zones["PS-52"]
    assert deerwater.onsite_generator_id == "GEN-PS52-DEERWATER"
    assert deerwater.generator_state is None
    assert deerwater.on_backup_power is False
    assert zones["PS-17"].onsite_generator_id is None


def test_feed_health_and_freshness_checks_agree_at_the_replay_clock(client: TestClient) -> None:
    now = datetime.fromisoformat(AT_N1.replace("Z", "+00:00"))
    window = (now - datetime(2024, 9, 23, 12, tzinfo=UTC)).total_seconds()
    feeds = [FeedHealthItem.model_validate(f) for f in client.get("/api/feeds/health").json()]
    checks = {
        c.name: c
        for c in map(DqCheckOut.model_validate, client.get("/api/dq/checks").json())
        if c.name.startswith("freshness.")
    }
    assert feeds and set(checks) == {f"freshness.{f.source_id}" for f in feeds}
    for f in feeds:
        check = checks[f"freshness.{f.source_id}"]
        assert f.stale is (not check.passed), f.source_id
        assert f.product_age_s is None or 0 <= f.product_age_s <= window, f.source_id
        assert check.checked_at == now
    by_id = {f.source_id: f for f in feeds}
    assert by_id["scada-water"].product_age_s == 300
    assert by_id["scada-water"].measured_by == "age" and by_id["fsm-crews"].measured_by == "delay"
    assert by_id["oms"].product_age_s == 300 and by_id["oms"].status == "on_time"
    assert not any(f.stale for f in feeds)
    late = next(c for c in client.get("/api/dq/checks").json() if c["name"] == "ingest.late_arrivals")
    assert late["passed"] is True


def test_crews_name_the_county_they_report_from(client: TestClient) -> None:
    crews = [CrewItem.model_validate(c) for c in client.get("/api/crews").json()]
    assert len(crews) == 18
    assert {c.region_id for c in crews} == {"SC-45003", "GA-13245"}
