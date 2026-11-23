"""SEC-73 (STM 9.1, PLAN section 2 tier table): one person cannot restore the kill switch. The restore needs
two people from two functions, `command` and `compliance`; the first signature only opens a pending restore,
and the database refuses a lower kill level without a completed restore in the same transaction. The trigger,
both signatures and the restore are records in the signed audit chain."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from sgw.approval import audit
from sgw.contracts.vocab import KillLevel
from sgw.ops import testkit as tk
from sgw.ops.control import read_control
from sgw.ops.errors import OpsConflict, OpsForbidden

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
RESTORE = {"kill_level": "K0", "reason": "cause contained, chain verified, smoke suite green"}
Conn = psycopg.Connection[Any]


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with tk.ops_database() as url:
        yield url


@pytest.fixture
def conn(db_url: str) -> Iterator[Conn]:
    tk.reset_control(db_url)
    with psycopg.connect(db_url, autocommit=True) as c:
        yield c


@pytest.mark.parametrize("user", ["ic_01", "wtr_comp_01"])
def test_one_person_from_a_restore_function_only_opens_a_pending_restore(conn: Conn, user: str) -> None:
    svc = tk.service()
    svc.set_kill(conn, user_id="ops_dm_01", level=KillLevel.K2, reason="confirmed injection")
    out = svc.set_kill(conn, user_id=user, level=KillLevel.K0, reason=RESTORE["reason"])
    assert out.status == "restore_pending"
    with pytest.raises(OpsConflict):
        svc.set_kill(conn, user_id=user, level=KillLevel.K0, reason=RESTORE["reason"])
    assert read_control(conn).kill_level is KillLevel.K2


@pytest.mark.parametrize("user", ["ops_dm_01", "exec_01", "wtr_lead_01", "admin_01", "audit_01"])
def test_trigger_roles_and_others_cannot_restore(conn: Conn, user: str) -> None:
    svc = tk.service()
    svc.set_kill(conn, user_id="ic_01", level=KillLevel.K1, reason="approval anomaly")
    with pytest.raises(OpsForbidden):
        svc.set_kill(conn, user_id=user, level=KillLevel.K0, reason=RESTORE["reason"])
    assert read_control(conn).kill_level is KillLevel.K1


def test_two_people_of_the_same_function_cannot_restore(conn: Conn) -> None:
    conn.execute(
        "INSERT INTO app_user (user_id, display_name, persona, function, functions, can_approve)"
        " VALUES ('ic_02', 'Incident Commander (relief)', 'P1', 'command', '{command}', true)"
        " ON CONFLICT DO NOTHING"
    )
    svc = tk.service()
    svc.set_kill(conn, user_id="exec_01", level=KillLevel.K1, reason="approval anomaly")
    svc.set_kill(conn, user_id="ic_01", level=KillLevel.K0, reason=RESTORE["reason"])
    with pytest.raises(OpsForbidden) as same:
        svc.set_kill(conn, user_id="ic_02", level=KillLevel.K0, reason=RESTORE["reason"])
    tk.expect_error(same.value, "RESTORE_SAME_FUNCTION")
    assert read_control(conn).kill_level is KillLevel.K1


def test_the_database_alone_refuses_a_one_person_restore(conn: Conn) -> None:
    tk.service().set_kill(conn, user_id="ic_01", level=KillLevel.K2, reason="confirmed injection")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute("SET LOCAL ROLE sgw_app")
        conn.execute("UPDATE control_state SET kill_level = 'K0', degraded_mode = 'M2' WHERE id = 1")
    assert read_control(conn).kill_level is KillLevel.K2


def test_restore_over_http_needs_both_functions_and_is_audited(db_url: str, conn: Conn) -> None:
    notary = tk.Notary()
    svc = tk.service(notary=notary)
    seq0 = tk.audit_head(conn)
    with tk.client_for(db_url, svc) as client:
        pulled = client.post(
            "/api/control/kill",
            json={"kill_level": "K2", "reason": "model misbehaviour"},
            headers=tk.h("wtr_lead_01"),
        )
        assert pulled.status_code == 200
        alone = client.post("/api/control/kill", json=RESTORE, headers=tk.h("wtr_comp_01", step_up=True))
        assert alone.status_code == 202 and alone.json()["kill_level"] == "K2"
        again = client.post("/api/control/kill", json=RESTORE, headers=tk.h("wtr_comp_01", step_up=True))
        assert again.status_code == 409 and again.json()["error"]["code"] == "RESTORE_AWAITS_SECOND_FUNCTION"
        assert client.get("/api/control/kill", headers=tk.h("audit_01")).json()["kill_level"] == "K2"
        both = client.post("/api/control/kill", json=RESTORE, headers=tk.h("ic_01", step_up=True))
        assert both.status_code == 200 and both.json()["kill_level"] == "K0"
    kinds = tk.audit_kinds(conn, seq0)
    assert kinds == ["kill_switch_triggered", "kill_restore_requested", "kill_switch_restored"]
    signed = conn.execute(
        "SELECT payload->'signed_by' FROM audit_event WHERE kind = 'kill_switch_restored' AND seq > %s",
        (seq0,),
    ).fetchone()
    assert signed is not None
    assert {(s["user_id"], s["function"]) for s in signed[0]} == {
        ("wtr_comp_01", "compliance"),
        ("ic_01", "command"),
    }
    assert audit.verify(conn, keyring=notary.keyring).ok
    assert notary.signed[-1] == tk.audit_head(conn)


def test_the_control_row_cannot_be_deleted_or_truncated(conn: Conn) -> None:
    for statement in ("DELETE FROM control_state", "TRUNCATE control_state"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SET LOCAL ROLE sgw_app")
            conn.execute(statement)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)
    assert conn.execute("SELECT count(*) FROM control_state").fetchone() == (1,)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE control_state SET kill_level = 'K0'",
        "UPDATE control_state SET degraded_mode = 'M0'",
        "UPDATE ops_kill_restore SET state = 'completed', cosigned_by = 'wtr_comp_01'",
        "INSERT INTO ops_kill_restore (restore_id, from_level, to_level, reason, checklist, requested_by,"
        " requested_function, requested_at, expires_at) VALUES ('RST-00000000BEEF', 'K2', 'K0',"
        " 'one person, plain SQL', '{}', 'ic_01', 'command', now(), now() + interval '5 minutes')",
        "UPDATE ops_voided_token SET reason = 'forgotten'",
        "DELETE FROM ops_voided_token",
        "INSERT INTO ops_kill_role (role) VALUES ('platform_admin')",
    ],
)
def test_app_role_cannot_lower_the_level_or_forge_a_restore_with_plain_sql(
    conn: Conn, statement: str
) -> None:
    tk.service().set_kill(conn, user_id="ic_01", level=KillLevel.K2, reason="confirmed injection")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute("SET LOCAL ROLE sgw_app")
        conn.execute(statement)
    assert read_control(conn).kill_level is KillLevel.K2


def test_restore_functions_need_a_live_stepped_up_session_per_signer(conn: Conn) -> None:
    svc = tk.service()
    svc.auto_session = False
    svc.set_kill(conn, user_id="ic_01", level=KillLevel.K2, reason="confirmed injection")
    with pytest.raises(OpsForbidden) as plain:
        svc.set_kill(conn, user_id="ic_01", level=KillLevel.K0, reason=RESTORE["reason"])
    tk.expect_error(plain.value, "STEP_UP_REQUIRED")
    not_stepped = tk.stepped_session(conn, "ic_01", step_up=False)
    with pytest.raises(OpsForbidden) as db_refused:
        svc.set_kill(
            conn,
            user_id="ic_01",
            level=KillLevel.K0,
            reason=RESTORE["reason"],
            session_hash=not_stepped,
            stepped_up=True,
        )
    tk.expect_error(db_refused.value, "REFUSED_BY_DATABASE")
    other_user = tk.stepped_session(conn, "wtr_comp_01")
    with pytest.raises(OpsForbidden):
        svc.set_kill(
            conn,
            user_id="ic_01",
            level=KillLevel.K0,
            reason=RESTORE["reason"],
            session_hash=other_user,
            stepped_up=True,
        )
    first = svc.set_kill(
        conn,
        user_id="ic_01",
        level=KillLevel.K0,
        reason=RESTORE["reason"],
        session_hash=tk.stepped_session(conn, "ic_01"),
        stepped_up=True,
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute("SET LOCAL ROLE sgw_app")
        conn.execute(
            "SELECT ops_restore_complete('wtr_comp_01', %s, %s, now())", ("0" * 64, first.restore_id)
        )
    assert read_control(conn).kill_level is KillLevel.K2
    with conn.transaction():
        conn.execute("SET LOCAL ROLE sgw_app")
        conn.execute(
            "SELECT ops_restore_complete('wtr_comp_01', %s, %s, now())",
            (tk.stepped_session(conn, "wtr_comp_01"), first.restore_id),
        )
    assert read_control(conn).kill_level is KillLevel.K0


def test_trigger_function_checks_kill_authority_in_the_database(conn: Conn) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute("SET LOCAL ROLE sgw_app")
        conn.execute("SELECT ops_kill_trigger('ml_01', 'K1', 'not my call', now())")
    assert read_control(conn).kill_level is KillLevel.K0
