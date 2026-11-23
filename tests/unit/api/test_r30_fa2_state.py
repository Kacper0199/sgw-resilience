"""Through the real app on a seeded scratch database: one row per decision case and action in every
queue view (Decisions, Notifications, Briefing), a closed decision's severity read from the observed water
state, and the Briefing's water count following the boil-water register (a signed lift ends the notice)."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from sgw.api.app import create_app
from sgw.api.readmodels import brief as brief_rm
from sgw.api.readmodels import water as water_rm
from sgw.api.settings import ApiSettings
from sgw.api.users import seed_users
from sgw.approval import testkit as tk
from sgw.contracts.api_models import ExecutiveBrief, NotificationFeed, ProposalSummary
from sgw.contracts.vocab import ProposalState, UiSeverity
from sgw.models.clocks import zone_cases

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
PASSWORD = "r30fa2-" + secrets.token_hex(12)
CREWS_CASE = "DC-D2-CREWS-AIK"
SEEDED_CREWS = "PRP-CREW-AIK-0926A"
NEWER_CREWS = "PRP-R30FA2-CREWS-NEWER"
WITHDRAWN_CREWS = "PRP-R30FA2-CREWS-WITHDRAWN"
CEDAR_NOTICE = "PRP-R30FA2-CEDAR-NOTICE"
COPPER_NOTICE = "PRP-R30FA2-COPPER-NOTICE"
TANKER = "PRP-R30FA2-TANKER"
CEDAR = "WZ-PS17-CEDARFALL"
COPPER = "WZ-PS38-COPPERLEAF"
LAUREL = "WZ-PS23-LAURELSPUR"
HOSPITAL = "HSP-AIK-TALLOWBRANCH"
AT_N1 = "2024-09-26T15:05:00Z"
MORNING_AFTER = "2024-09-27T12:00:00Z"


def _copy(conn: psycopg.Connection[Any], new_id: str, minutes: int, **changes: Any) -> None:
    """A copy of the seeded crew proposal created `minutes` later, with `changes` applied to the copy."""
    columns = [
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'proposal'"
            " AND column_name NOT IN ('proposal_id', 'created_at')"
            " AND is_generated = 'NEVER' ORDER BY ordinal_position"
        ).fetchall()
    ]
    state = changes.pop("state", None)
    cast = {"required_functions": "::sgw_approval_function[]", "params": "::jsonb"}
    picked = ", ".join(f"%({c})s{cast.get(c, '')}" if c in changes else c for c in columns)
    values = {c: Jsonb(v) if c == "params" else v for c, v in changes.items()}
    conn.execute(
        f"INSERT INTO proposal (proposal_id, created_at, {', '.join(columns)})"  # noqa: S608
        f" SELECT %(new_id)s, created_at + make_interval(mins => %(minutes)s), {picked}"
        " FROM proposal WHERE proposal_id = %(source)s",
        {**values, "new_id": new_id, "minutes": minutes, "source": SEEDED_CREWS},
    )
    if state is not None:
        conn.execute("UPDATE proposal SET state = %s WHERE proposal_id = %s", (state, new_id))


def _case(conn: psycopg.Connection[Any], case_id: str) -> None:
    columns = [
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'decision_case'"
            " AND column_name <> 'decision_case_id' AND is_generated = 'NEVER' ORDER BY ordinal_position"
        ).fetchall()
    ]
    listed = ", ".join(columns)
    conn.execute(
        f"INSERT INTO decision_case (decision_case_id, {listed})"  # noqa: S608
        f" SELECT %s, {listed} FROM decision_case WHERE decision_case_id = %s",
        (case_id, CREWS_CASE),
    )


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: queue reads need Postgres
    from sgw.approval.seed import run_seed

    with tk.scratch_database("sgw_r30fa2_t") as url:
        run_seed(url, use_default_ledger=False)
        seed_users(url, PASSWORD)
        with psycopg.connect(url, autocommit=True) as conn:
            _copy(conn, NEWER_CREWS, 1)
            _copy(conn, WITHDRAWN_CREWS, 5, state="withdrawn")
            _case(conn, f"DC-{CEDAR_NOTICE}")
            _copy(
                conn,
                CEDAR_NOTICE,
                2,
                decision_case_id=f"DC-{CEDAR_NOTICE}",
                action_type="boil_water_notice",
                state="expired",
                required_functions=["water_operations", "compliance"],
                targets=[CEDAR],
            )
            _case(conn, f"DC-{COPPER_NOTICE}")
            _copy(
                conn,
                COPPER_NOTICE,
                3,
                decision_case_id=f"DC-{COPPER_NOTICE}",
                action_type="boil_water_notice",
                state="expired",
                required_functions=["water_operations", "compliance"],
                targets=[COPPER],
            )
            _case(conn, f"DC-{TANKER}")
            _copy(
                conn,
                TANKER,
                4,
                decision_case_id=f"DC-{TANKER}",
                action_type="field_resource_order",
                state="expired",
                tier="T2",
                required_functions=["logistics"],
                targets=["WTK-CORDGRASS-2"],
                params={"destination_id": HOSPITAL, "resource_kind": "potable_water_tanker"},
            )
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


def queue(c: TestClient) -> list[ProposalSummary]:
    return [ProposalSummary.model_validate(x) for x in c.get("/api/proposals").json()]


# ---- one row per decision case and action -----------------------------------------------------------------


def test_the_queue_lists_only_the_latest_proposal_of_a_case_a_withdrawn_one_hides_nothing(
    client: TestClient,
) -> None:
    seek(client, AT_N1)
    login(client, "log_01")
    crews = {p.proposal_id for p in queue(client) if p.action_type == "preposition_crews"}
    assert crews == {NEWER_CREWS, WITHDRAWN_CREWS}
    assert client.get(f"/api/proposals/{SEEDED_CREWS}").status_code == 200


def test_notifications_wait_once_per_case(client: TestClient) -> None:
    seek(client, AT_N1)
    login(client, "log_01")
    feed = NotificationFeed.model_validate(client.get("/api/notifications").json())
    waiting = [
        i for i in feed.items if i.kind == "decision_waiting" and "Pre-position crews" in (i.detail or "")
    ]
    assert [i.href for i in waiting] == [f"/decisions/{NEWER_CREWS}"]
    assert len({(i.title, i.detail) for i in feed.items}) == len(feed.items)


def test_the_briefing_lists_a_case_once(client: TestClient) -> None:
    seek(client, AT_N1)
    login(client, "ic_01")
    doc = ExecutiveBrief.model_validate(client.get("/api/brief").json())
    assert [p.proposal_id for p in doc.open_t3 if p.action_type == "preposition_crews"] == [NEWER_CREWS]


# ---- severity of a closed decision follows the observed water state ---------------------------------------


def test_a_closed_decision_on_a_zone_below_the_floor_stays_severe(client: TestClient) -> None:
    seek(client, MORNING_AFTER)
    login(client, "wtr_lead_01")
    by_id = {p.proposal_id: p for p in queue(client)}
    pressure = {r.zone.zone_id: r.zone for r in water_rm.zone_readings(datetime(2024, 9, 27, 12, tzinfo=UTC))}
    assert pressure[CEDAR].pressure_psi_x10 < pressure[CEDAR].floor_psi_x10
    assert pressure[COPPER].pressure_psi_x10 >= pressure[COPPER].floor_psi_x10
    assert by_id[CEDAR_NOTICE].severity is UiSeverity.SEVERE
    assert by_id[TANKER].severity is UiSeverity.SEVERE
    assert by_id[COPPER_NOTICE].severity is UiSeverity.NORMAL


def test_the_same_closed_decision_is_normal_once_the_pressure_is_back(client: TestClient) -> None:
    seek(client, "2024-09-30T12:00:00Z")
    login(client, "wtr_lead_01")
    by_id = {p.proposal_id: p for p in queue(client)}
    assert by_id[CEDAR_NOTICE].severity is UiSeverity.NORMAL
    assert by_id[TANKER].severity is UiSeverity.NORMAL


# ---- the Briefing's water count reads the register with its lifts ----------------------------------------


def test_a_signed_lift_ends_the_notice_in_the_briefing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(zone_cases.FLAG_ENV, "1")
    at = datetime(2024, 9, 30, 12, tzinfo=UTC)
    notices = {LAUREL: water_rm.BwaProposal("PRP-N", "DC-N", ProposalState.APPROVED)}
    lifts = {LAUREL: water_rm.BwaProposal("PRP-L", "DC-L", ProposalState.APPROVED)}

    def found(conn: object, zone_ids: list[str], when: datetime, action: str = water_rm.NOTICE_ACTION) -> Any:
        chosen = lifts if action == water_rm.LIFT_ACTION else notices
        return {z: chosen.get(z) for z in zone_ids}

    monkeypatch.setattr(brief_rm, "bwa_proposals", found)
    issued, _, _ = brief_rm.water_counts(None, at)  # type: ignore[arg-type]
    register = water_rm.register(at, found(None, water_rm.zone_ids(), at), lifts)
    under = {a.zone_id for a in register.advisories if a.status == "issued"}
    assert LAUREL not in under
    assert issued == len(under)
