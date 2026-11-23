"""Control service against a migrated, seeded database: who may trigger, the restore protocol, mode floors,
the reconciler, audit records and K2 events, and the database rules that hold without the service."""

from __future__ import annotations

import contextlib
from typing import Any

import psycopg
import pytest

from sgw.approval import audit
from sgw.contracts.vocab import DegradedMode, KillLevel
from sgw.ops import testkit as tk
from sgw.ops.control import ControlService, read_control
from sgw.ops.errors import OpsConflict, OpsForbidden
from sgw.ops.levels import Capability
from sgw.ops.signals import Reading

Conn = psycopg.Connection[Any]


@pytest.mark.parametrize("user", ["ic_01", "ops_dm_01", "ops_dm_02", "wtr_lead_01", "exec_01"])
def test_listed_roles_trigger_alone(conn: Conn, user: str) -> None:
    out = tk.service().set_kill(conn, user_id=user, level=KillLevel.K1, reason="suspicious proposal")
    assert out.status == "triggered" and out.state.kill_level is KillLevel.K1
    assert out.state.updated_by == [user]


@pytest.mark.parametrize("user", ["log_01", "wtr_comp_01", "audit_01", "admin_01", "ml_01", "plan_etr_01"])
def test_other_roles_cannot_trigger(conn: Conn, user: str) -> None:
    with pytest.raises(OpsForbidden) as denied:
        tk.service().set_kill(conn, user_id=user, level=KillLevel.K1, reason="suspicious proposal")
    tk.expect_error(denied.value, "KILL_TRIGGER_DENIED")
    assert read_control(conn).kill_level is KillLevel.K0


def test_same_level_again_is_a_conflict(conn: Conn) -> None:
    svc = tk.service()
    svc.set_kill(conn, user_id="ic_01", level=KillLevel.K1, reason="first pull")
    with pytest.raises(OpsConflict) as again:
        svc.set_kill(conn, user_id="exec_01", level=KillLevel.K1, reason="second pull")
    tk.expect_error(again.value, "KILL_LEVEL_UNCHANGED")


def test_raising_further_needs_no_restore(conn: Conn) -> None:
    svc = tk.service()
    svc.set_kill(conn, user_id="ops_dm_01", level=KillLevel.K1, reason="approval anomaly")
    out = svc.set_kill(conn, user_id="wtr_lead_01", level=KillLevel.K3, reason="compromise suspected")
    assert out.state.kill_level is KillLevel.K3 and out.state.degraded_mode is DegradedMode.M3


def test_trigger_and_restore_are_audited_signed_and_published(conn: Conn) -> None:
    notary = tk.Notary()
    svc = tk.service(notary=notary)
    seq0, led0 = tk.audit_head(conn), tk.ledger_head(conn)
    svc.set_kill(conn, user_id="ic_01", level=KillLevel.K2, reason="confirmed injection in an SOP chunk")
    pending = svc.set_kill(
        conn, user_id="wtr_comp_01", level=KillLevel.K0, reason="cause contained, keys rotated"
    )
    assert pending.status == "restore_pending" and pending.state.kill_level is KillLevel.K2
    done = svc.set_kill(conn, user_id="ic_01", level=KillLevel.K0, reason="cause contained, keys rotated")
    assert done.status == "restored" and done.state.kill_level is KillLevel.K0
    assert done.state.degraded_mode is DegradedMode.M0
    assert sorted(done.state.updated_by) == ["ic_01", "wtr_comp_01"]
    assert tk.audit_kinds(conn, seq0) == [
        "kill_switch_triggered",
        "kill_restore_requested",
        "kill_switch_restored",
    ]
    restored = conn.execute(
        "SELECT payload FROM audit_event WHERE kind = 'kill_switch_restored' AND seq > %s", (seq0,)
    ).fetchone()
    assert restored is not None
    assert {s["function"] for s in restored[0]["signed_by"]} == {"command", "compliance"}
    report = audit.verify(conn, keyring=notary.keyring)
    assert report.ok, report.problems
    assert notary.signed and notary.signed[-1] == tk.audit_head(conn)
    assert tk.ledger_types(conn, led0) == [
        "KillSwitchChanged",
        "ModeChanged",
        "KillSwitchChanged",
        "ModeChanged",
    ]


def test_restore_rules(conn: Conn) -> None:
    svc = tk.service()
    svc.set_kill(conn, user_id="exec_01", level=KillLevel.K1, reason="approval anomaly seen")
    with pytest.raises(OpsForbidden) as wrong_fn:
        svc.set_kill(conn, user_id="ops_dm_01", level=KillLevel.K0, reason="looks fine to me now")
    tk.expect_error(wrong_fn.value, "RESTORE_FUNCTION_REQUIRED")
    first = svc.set_kill(conn, user_id="ic_01", level=KillLevel.K0, reason="cause contained, chain ok")
    assert first.awaiting_function is not None and first.awaiting_function.value == "compliance"
    with pytest.raises(OpsConflict) as twice:
        svc.set_kill(conn, user_id="ic_01", level=KillLevel.K0, reason="cause contained, chain ok")
    tk.expect_error(twice.value, "RESTORE_AWAITS_SECOND_FUNCTION")
    assert read_control(conn).kill_level is KillLevel.K1


def test_restore_to_a_different_level_than_pending_is_refused(conn: Conn) -> None:
    svc = tk.service()
    svc.set_kill(conn, user_id="ic_01", level=KillLevel.K2, reason="model misbehaviour")
    svc.set_kill(conn, user_id="ic_01", level=KillLevel.K1, reason="LLM fixed, keep actions frozen")
    with pytest.raises(OpsConflict) as mismatch:
        svc.set_kill(conn, user_id="wtr_comp_01", level=KillLevel.K0, reason="everything is fine again")
    tk.expect_error(mismatch.value, "RESTORE_TARGET_MISMATCH")
    out = svc.set_kill(
        conn, user_id="wtr_comp_01", level=KillLevel.K1, reason="LLM fixed, keep actions frozen"
    )
    assert out.state.kill_level is KillLevel.K1 and out.state.degraded_mode is DegradedMode.M0


def test_a_new_trigger_cancels_a_pending_restore(conn: Conn) -> None:
    svc = tk.service()
    svc.set_kill(conn, user_id="ic_01", level=KillLevel.K1, reason="approval anomaly")
    first = svc.set_kill(conn, user_id="ic_01", level=KillLevel.K0, reason="anomaly explained")
    svc.set_kill(conn, user_id="exec_01", level=KillLevel.K2, reason="new evidence of injection")
    state = conn.execute(
        "SELECT state FROM ops_kill_restore WHERE restore_id = %s", (first.restore_id,)
    ).fetchone()
    assert state is not None and state[0] == "cancelled"
    assert svc.pending_restore(conn) is None


def test_restore_refused_while_the_audit_chain_fails(conn: Conn) -> None:
    class Broken:
        ok = False
        first_bad_seq = 7
        problems = ["seq 7: hash does not recompute"]

    svc = tk.service()
    svc.set_kill(conn, user_id="ic_01", level=KillLevel.K1, reason="audit anomaly")
    svc.chain_check = lambda _c: Broken()
    with pytest.raises(OpsConflict) as refused:
        svc.set_kill(conn, user_id="ic_01", level=KillLevel.K0, reason="anomaly explained")
    tk.expect_error(refused.value, "AUDIT_CHAIN_UNVERIFIED")
    assert refused.value.details["first_bad_seq"] == 7
    assert ControlService(chain_check=None).pending_restore(conn) is None


def test_expired_restore_cannot_be_completed(conn: Conn, db_url: str) -> None:
    svc = tk.service()
    svc.set_kill(conn, user_id="ic_01", level=KillLevel.K1, reason="approval anomaly")
    first = svc.set_kill(conn, user_id="ic_01", level=KillLevel.K0, reason="anomaly explained")
    with psycopg.connect(db_url, autocommit=True) as admin:
        admin.execute("ALTER TABLE ops_kill_restore DISABLE TRIGGER ops_kill_restore_enforce_write")
        admin.execute(
            "UPDATE ops_kill_restore SET requested_at = requested_at - interval '1 hour',"
            " expires_at = now() - interval '1 second' WHERE restore_id = %s",
            (first.restore_id,),
        )
        admin.execute("ALTER TABLE ops_kill_restore ENABLE TRIGGER ops_kill_restore_enforce_write")
    out = svc.set_kill(conn, user_id="wtr_comp_01", level=KillLevel.K0, reason="anomaly explained")
    assert out.status == "restore_pending" and out.restore_id != first.restore_id
    expired = conn.execute(
        "SELECT payload->>'restore_id' FROM audit_event WHERE kind = 'kill_restore_expired'"
    ).fetchall()
    assert (first.restore_id,) in expired
    assert read_control(conn).kill_level is KillLevel.K1


def test_database_refuses_lowering_without_a_completed_restore(conn: Conn) -> None:
    tk.service().set_kill(conn, user_id="ic_01", level=KillLevel.K2, reason="injection confirmed")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE control_state SET kill_level = 'K0', degraded_mode = 'M2' WHERE id = 1")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE control_state SET degraded_mode = 'M0' WHERE id = 1")
    assert read_control(conn).kill_level is KillLevel.K2


def test_database_refuses_a_one_person_or_one_function_restore(conn: Conn) -> None:
    svc = tk.service()
    svc.set_kill(conn, user_id="ic_01", level=KillLevel.K1, reason="approval anomaly")
    first = svc.set_kill(conn, user_id="ic_01", level=KillLevel.K0, reason="anomaly explained")
    conn.execute(
        "INSERT INTO app_user (user_id, display_name, persona, function, functions, can_approve)"
        " VALUES ('ic_02', 'Incident Commander (relief)', 'P1', 'command', '{command}', true)"
        " ON CONFLICT DO NOTHING"
    )
    for cosigner in ("ic_01", "ic_02", "ops_dm_01"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "UPDATE ops_kill_restore SET state = 'completed', cosigned_by = %s WHERE restore_id = %s",
                (cosigner, first.restore_id),
            )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "INSERT INTO ops_kill_restore (restore_id, from_level, to_level, reason, checklist, requested_by,"
            " requested_function, requested_at, expires_at, state, cosigned_by)"
            " VALUES ('RST-00000000ABCD', 'K1', 'K0', 'forged in one go', '{}', 'ic_01', 'command', now(),"
            " now() + interval '5 minutes', 'completed', 'wtr_comp_01')"
        )


def test_app_role_cannot_grant_itself_kill_authority(conn: Conn) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute("SET LOCAL ROLE sgw_app")
        conn.execute("INSERT INTO ops_kill_role (role) VALUES ('platform_admin')")


def test_manual_mode_rules(conn: Conn) -> None:
    svc = tk.service()
    with pytest.raises(OpsForbidden) as denied:
        svc.set_mode(conn, user_id="audit_01", mode=DegradedMode.M1, reason="drill")
    tk.expect_error(denied.value, "MODE_CHANGE_DENIED")
    raised = svc.set_mode(conn, user_id="admin_01", mode=DegradedMode.M2, reason="provider incident notice")
    assert raised.degraded_mode is DegradedMode.M2
    with pytest.raises(OpsForbidden) as lower:
        svc.set_mode(conn, user_id="ops_dm_01", mode=DegradedMode.M0, reason="seems fine")
    tk.expect_error(lower.value, "MODE_LOWER_DENIED")
    back = svc.set_mode(conn, user_id="ic_01", mode=DegradedMode.M0, reason="provider confirmed recovery")
    assert back.degraded_mode is DegradedMode.M0
    assert tk.audit_kinds(conn)[-2:] == ["degraded_mode_set", "degraded_mode_set"]


def test_manual_mode_cannot_go_below_kill_or_signal_floor(conn: Conn) -> None:
    svc = tk.service({"FAULT_OPA_DOWN": "1"})
    svc.reconcile(conn)
    with pytest.raises(OpsConflict) as floor:
        svc.set_mode(conn, user_id="ic_01", mode=DegradedMode.M0, reason="ignore the outage")
    tk.expect_error(floor.value, "MODE_BELOW_FLOOR")
    assert floor.value.details["blocked_by"] == ["opa_down"]
    svc.env = {}
    svc.reconcile(conn)
    svc.set_kill(conn, user_id="ic_01", level=KillLevel.K2, reason="model misbehaviour")
    with pytest.raises(OpsConflict) as kill_floor:
        svc.set_mode(conn, user_id="ic_01", mode=DegradedMode.M1, reason="try reduced AI")
    assert kill_floor.value.details["blocked_by"] == ["kill:K2"]


def test_reconcile_follows_flags_and_probes_and_audits_transitions(conn: Conn) -> None:
    svc = tk.service({"FAULT_LLM_DOWN": "1"})
    seq0 = tk.audit_head(conn)
    first = svc.reconcile(conn)
    assert first.after is DegradedMode.M2 and first.raised == ("llm_down",)
    assert svc.reconcile(conn).changed is False
    svc.env = {}
    down = [Reading("llm_down", True, "breaker open"), Reading("llm_degraded", True, "breaker open")]
    up = [Reading("llm_down", False, "closed"), Reading("llm_degraded", False, "closed")]
    assert svc.reconcile(conn, down).after is DegradedMode.M2
    assert svc.reconcile(conn, down).active == ("llm_degraded", "llm_down")
    for _ in range(2):
        assert svc.reconcile(conn, up).after is DegradedMode.M2
    last = svc.reconcile(conn, up)
    assert last.after is DegradedMode.M0 and set(last.cleared) == {"llm_down", "llm_degraded"}
    kinds = tk.audit_kinds(conn, seq0)
    assert kinds.count("degraded_mode_changed") == 2
    assert kinds.count("ops_signal_raised") == 2 and kinds.count("ops_signal_cleared") == 2


def test_weather_probe_reads_feed_health(conn: Conn) -> None:
    conn.execute(
        "INSERT INTO adapter_health (source_id, feed_mode, ingest_lag_s, freshness_limit_s)"
        " VALUES ('nws-alerts', 'replay', 4000, 900)"
        " ON CONFLICT (source_id) DO UPDATE SET ingest_lag_s = 4000"
    )
    svc = tk.service()
    svc.feed_probe = True
    out = svc.reconcile(conn)
    assert out.active == ("weather_stale",) and out.after is DegradedMode.M0
    assert not svc.capabilities(conn)[Capability.CREW_INTO_HAZARD_PROPOSALS]
    conn.execute("UPDATE adapter_health SET ingest_lag_s = 60 WHERE source_id = 'nws-alerts'")
    assert svc.reconcile(conn).cleared == ("weather_stale",)


def test_unreadable_control_behaves_as_k1(conn: Conn) -> None:
    conn.execute("BEGIN")
    with contextlib.suppress(psycopg.errors.DivisionByZero):
        conn.execute("SELECT 1/0")
    view = read_control(conn)
    conn.execute("ROLLBACK")
    assert view.kill_level is KillLevel.K1 and not view.readable
    assert view.state().updated_by == ["system:control-unreadable"]


def test_missing_control_row_reads_as_k1_and_freezes_execution(conn: Conn, db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as admin:
        admin.execute("SET session_replication_role = replica")
        admin.execute("DELETE FROM control_state")
    try:
        view = read_control(conn)
        assert view.kill_level is KillLevel.K1 and not view.readable
        assert conn.execute("SELECT ops_current_kill()").fetchone() == (1,)
        assert not tk.service().capabilities(conn)[Capability.APPROVE_AND_EXECUTE]
    finally:
        with psycopg.connect(db_url, autocommit=True) as admin:
            admin.execute("INSERT INTO control_state (id) VALUES (1) ON CONFLICT DO NOTHING")


def test_database_errors_reach_the_client_as_generic_messages(conn: Conn) -> None:
    svc = tk.service()
    svc.set_kill(conn, user_id="ic_01", level=KillLevel.K1, reason="approval anomaly")
    with pytest.raises(OpsForbidden) as refused:
        svc.set_kill(
            conn,
            user_id="ic_01",
            level=KillLevel.K0,
            reason="anomaly explained",
            session_hash="0" * 64,
            stepped_up=True,
        )
    assert refused.value.code == "REFUSED_BY_DATABASE"
    assert "session" not in refused.value.message and "ic_01" not in refused.value.message
