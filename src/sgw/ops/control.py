"""Control plane service: kill switch K0-K4 with a two-function restore, degraded modes M0-M4 from signals,
and the reconciler that applies them. Transport-free: functions take a psycopg connection (autocommit, idle)
and return K3 models.

Every change runs in one transaction under the audit lock: the `control_state` row, the signal rows, the
audit record (WP-09b chain) and the K2 event (WP-07 outbox). After commit the outbox is drained into the
ledger and the audit head is checkpointed (signed), so a kill or a restore is notarised at once.

Reading the control row fails closed: if it cannot be read the platform behaves as K1 (SEC-72).
"""

from __future__ import annotations

import logging
import secrets
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sgw.api.audit_log import AUDIT_LOCK_KEY
from sgw.approval import audit
from sgw.contracts.api_models import ControlState
from sgw.contracts.base import Contract
from sgw.contracts.events import EVENT_MODELS, EnvelopeBase, KillSwitchChanged, ModeChanged
from sgw.contracts.vocab import (
    ApprovalFunction,
    Classification,
    DegradedMode,
    FeedMode,
    KillLevel,
    RunMode,
    Trust,
)
from sgw.ops import levels
from sgw.ops.errors import OpsConflict, OpsError, OpsForbidden, from_db_error
from sgw.ops.levels import Capability
from sgw.ops.signals import Reading, SignalState, evaluate, fault_flags

log = logging.getLogger("sgw.ops.control")
ORIGIN = "ops"
SOURCE_ID = "sgw-platform"
NAMESPACE = uuid.UUID("5a1f0c2e-28a0-4c6b-9d3e-7f0b5e2c28a0")
RECONCILER = "system:ops-reconciler"
UNREADABLE = "system:control-unreadable"
WEATHER_SOURCES = ("nws-alerts", "nhc-advisory-synthetic")


class LedgerSink(Protocol):
    def enqueue(self, conn: psycopg.Connection[Any], events: Sequence[EnvelopeBase]) -> int: ...

    def drain(self, conn: psycopg.Connection[Any]) -> None: ...


class ChainReport(Protocol):
    ok: bool
    first_bad_seq: int | None
    problems: list[str]


Notary = Callable[[psycopg.Connection[Any]], None]
ChainCheck = Callable[[psycopg.Connection[Any]], ChainReport]


def wall_clock() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Actor:
    user_id: str
    function: ApprovalFunction
    roles: tuple[str, ...]
    on_shift: bool
    may_trigger: bool = False


@dataclass(frozen=True)
class Signer:
    session_hash: str | None
    stepped_up: bool


@dataclass(frozen=True)
class ControlView:
    kill_level: KillLevel
    degraded_mode: DegradedMode
    run_mode: RunMode
    updated_by: tuple[str, ...]
    updated_at: datetime
    readable: bool = True

    def state(self) -> ControlState:
        return ControlState(
            kill_level=self.kill_level,
            degraded_mode=self.degraded_mode,
            run_mode=self.run_mode,
            updated_by=list(self.updated_by),
            updated_at=self.updated_at,
        )


@dataclass(frozen=True)
class KillOutcome:
    state: ControlState
    status: str
    restore_id: str | None = None
    awaiting_function: ApprovalFunction | None = None
    voided_approvals: tuple[str, ...] = ()
    voided_tokens: tuple[str, ...] = ()
    cancelled_runs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReconcileReport:
    before: DegradedMode
    after: DegradedMode
    active: tuple[str, ...]
    raised: tuple[str, ...]
    cleared: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.before is not self.after or bool(self.raised or self.cleared)


def read_control(conn: psycopg.Connection[Any], now: datetime | None = None) -> ControlView:
    """The control row. Missing or unreadable reads as K1 (fail closed, SEC-72); migration 5000 creates the
    row and the database refuses to delete it."""
    try:
        row = conn.execute(
            "SELECT kill_level, degraded_mode, run_mode, updated_by::text[], updated_at"
            " FROM control_state WHERE id = 1"
        ).fetchone()
    except psycopg.Error:
        log.warning("control_state unreadable; behaving as K1", exc_info=True)
        return ControlView(
            KillLevel.K1, DegradedMode.M2, RunMode.REPLAY, (UNREADABLE,), now or wall_clock(), readable=False
        )
    if row is None:
        return ControlView(
            KillLevel.K1, DegradedMode.M0, RunMode.REPLAY, (UNREADABLE,), now or wall_clock(), readable=False
        )
    return ControlView(
        KillLevel(row[0]), DegradedMode(row[1]), RunMode(row[2]), tuple(row[3] or ()), row[4].astimezone(UTC)
    )


def load_actor(conn: psycopg.Connection[Any], user_id: str) -> Actor:
    row = conn.execute(
        "SELECT u.user_id, u.function, u.roles::text[], u.on_shift,"
        " u.roles && ARRAY(SELECT role FROM ops_kill_role) FROM app_user u WHERE u.user_id = %s",
        (user_id,),
    ).fetchone()
    if row is None:
        raise OpsForbidden(f"unknown user {user_id}", code="UNKNOWN_USER")
    return Actor(str(row[0]), ApprovalFunction(row[1]), tuple(row[2] or ()), bool(row[3]), bool(row[4]))


def load_signals(conn: psycopg.Connection[Any]) -> dict[str, SignalState]:
    rows = conn.execute(
        "SELECT signal, active, source, detail, fail_streak, ok_streak FROM ops_signal WHERE signal <> %s",
        (levels.MANUAL_SIGNAL,),
    ).fetchall()
    return {
        str(r[0]): SignalState(str(r[0]), bool(r[1]), r[2], str(r[3]), int(r[4]), int(r[5]))
        for r in rows
        if str(r[0]) in levels.RULES_BY_SIGNAL
    }


def manual_floor(conn: psycopg.Connection[Any]) -> DegradedMode:
    row = conn.execute(
        "SELECT floor_mode FROM ops_signal WHERE signal = %s AND active", (levels.MANUAL_SIGNAL,)
    ).fetchone()
    return DegradedMode(row[0]) if row else DegradedMode.M0


def floor_for(
    kill: KillLevel, signals: Mapping[str, SignalState], manual: DegradedMode = DegradedMode.M0
) -> DegradedMode:
    ranks = [levels.mode_rank(levels.KILL_MODE_FLOOR[kill]), levels.mode_rank(manual)]
    ranks += [levels.mode_rank(s.rule.floor) for s in signals.values() if s.active]
    return levels.mode_of_rank(max(ranks))


def capability_map(view: ControlView, signals: Mapping[str, SignalState]) -> dict[Capability, bool]:
    removed: frozenset[Capability] = frozenset()
    for state in signals.values():
        if state.active:
            removed |= state.rule.removes
    return levels.capabilities(view.kill_level, view.degraded_mode, removed)


def weather_reading(conn: psycopg.Connection[Any]) -> Reading | None:
    rows = conn.execute(
        "SELECT source_id, stale, ingest_lag_s, freshness_limit_s FROM feed_health WHERE source_id = ANY(%s)",
        (list(WEATHER_SOURCES),),
    ).fetchall()
    if not rows:
        return None
    stale = [f"{r[0]} lag {r[2]} s > 2 x {r[3]} s" for r in rows if r[1]]
    return Reading("weather_stale", bool(stale), "; ".join(stale) or "weather fresh")


def _envelope(payload: Contract, *, at: datetime, key: str, run_mode: RunMode) -> EnvelopeBase:
    type_name = type(payload).__name__
    dedup = f"{ORIGIN}:{type_name}:{key}"
    return EVENT_MODELS[type_name].model_validate(
        {
            "type": type_name,
            "event_id": uuid.uuid5(NAMESPACE, dedup),
            "source_id": SOURCE_ID,
            "feed_mode": FeedMode.SYNTHETIC,
            "run_mode": run_mode,
            "event_time": at,
            "received_at": at,
            "known_at": at,
            "scenario_known_at": at,
            "dedup_key": dedup,
            "classification": Classification.C1,
            "trust": Trust.SYSTEM,
            "region_id": None,
            "domain": None,
            "payload": payload,
        }
    )


@dataclass
class ControlService:
    clock: Callable[[], datetime] = wall_clock
    scenario_clock: Callable[[], datetime] | None = None
    ledger: LedgerSink | None = None
    notary: Notary | None = None
    chain_check: ChainCheck | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    feed_probe: bool = False

    def _scenario_at(self) -> dict[str, str]:
        """Stop levels run on the wall clock; the scenario time beside it lets feeds place the change in the
        exercise timeline."""
        if self.scenario_clock is None:
            return {}
        return {"scenario_at": self.scenario_clock().astimezone(UTC).isoformat().replace("+00:00", "Z")}

    # ---- reads -----------------------------------------------------------------------------------------

    def state(self, conn: psycopg.Connection[Any]) -> ControlState:
        return read_control(conn, self.clock()).state()

    def capabilities(self, conn: psycopg.Connection[Any]) -> dict[Capability, bool]:
        view = read_control(conn, self.clock())
        try:
            signals = load_signals(conn)
        except psycopg.Error:
            signals = {}
        return capability_map(view, signals)

    def pending_restore(self, conn: psycopg.Connection[Any]) -> dict[str, Any] | None:
        with conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                "SELECT restore_id, from_level, to_level, requested_by, requested_function, requested_at,"
                " expires_at FROM ops_kill_restore WHERE state = 'pending' AND expires_at > now()"
            ).fetchone()
        return dict(row) if row else None

    # ---- kill switch -----------------------------------------------------------------------------------

    def set_kill(
        self,
        conn: psycopg.Connection[Any],
        *,
        user_id: str,
        level: KillLevel,
        reason: str,
        session_hash: str | None = None,
        stepped_up: bool = False,
    ) -> KillOutcome:
        """Raise the kill level (one listed role), or sign a restore to a lower level (two functions, each
        with a live stepped-up session, checked here under the lock and again by the database)."""
        signer = Signer(session_hash, stepped_up)
        try:
            with conn.transaction():
                outcome = self._set_kill(
                    conn, user_id=user_id, level=level, reason=reason.strip(), signer=signer
                )
        except OpsError:
            raise
        except psycopg.Error as error:
            raise from_db_error(error) from error
        self._after_commit(conn)
        return outcome

    def _lock(self, conn: psycopg.Connection[Any]) -> ControlView:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_LOCK_KEY,))
        conn.execute("SELECT 1 FROM control_state WHERE id = 1 FOR UPDATE")
        return read_control(conn, self.clock())

    def _set_kill(
        self, conn: psycopg.Connection[Any], *, user_id: str, level: KillLevel, reason: str, signer: Signer
    ) -> KillOutcome:
        actor = load_actor(conn, user_id)
        view = self._lock(conn)
        now = self.clock()
        current = view.kill_level
        if levels.kill_rank(level) > levels.kill_rank(current):
            return self._trigger(conn, actor, view, level, reason, now)
        if level is current:
            raise OpsConflict(f"the kill level is already {current.value}", code="KILL_LEVEL_UNCHANGED")
        if not signer.stepped_up or not signer.session_hash:
            raise OpsForbidden("re-enter your password to sign a restore", code="STEP_UP_REQUIRED")
        return self._restore(conn, actor, view, level, reason, now, signer.session_hash)

    def _trigger(
        self,
        conn: psycopg.Connection[Any],
        actor: Actor,
        view: ControlView,
        level: KillLevel,
        reason: str,
        now: datetime,
    ) -> KillOutcome:
        if not actor.may_trigger:
            raise OpsForbidden(
                "the kill switch is triggered by the Incident Commander, a Duty Manager, the Water Incident"
                " Lead"
                " or an Executive",
                code="KILL_TRIGGER_DENIED",
            )
        row = conn.execute(
            "SELECT ops_kill_trigger(%s, %s, %s, %s)", (actor.user_id, level.value, reason, now)
        ).fetchone()
        assert row is not None
        result: dict[str, Any] = row[0]
        mode = DegradedMode(result["mode_to"])
        voided_approvals = [str(x) for x in result["voided_approvals"]]
        voided_tokens = [str(x) for x in result["voided_tokens"]]
        cancelled_runs = [str(x) for x in result["cancelled_agent_runs"]]
        cancelled_restores = [str(x) for x in result["cancelled_restores"]]
        record = audit.append(
            conn,
            kind="kill_switch_triggered",
            actor_type="user",
            actor_id=actor.user_id,
            subject=f"control:kill:{level.value}",
            payload={
                "from": view.kill_level.value,
                "to": level.value,
                "reason": reason,
                "function": actor.function.value,
                "roles": list(actor.roles),
                "degraded_mode": {"from": view.degraded_mode.value, "to": mode.value},
                "voided_approvals": voided_approvals,
                "voided_tokens": voided_tokens,
                "cancelled_agent_runs": cancelled_runs,
                "cancelled_restores": cancelled_restores,
                **self._scenario_at(),
            },
            occurred_at=now,
        )
        events: list[Contract] = [
            KillSwitchChanged(kill_level=level, changed_by=[actor.user_id], reason=reason)
        ]
        if mode is not view.degraded_mode:
            events.append(ModeChanged(run_mode=view.run_mode, degraded_mode=mode, changed_by=actor.user_id))
        self._enqueue(conn, events, now, f"audit-{record.seq}", view.run_mode)
        return KillOutcome(
            state=ControlView(level, mode, view.run_mode, (actor.user_id,), now).state(),
            status="triggered",
            voided_approvals=tuple(voided_approvals),
            voided_tokens=tuple(voided_tokens),
            cancelled_runs=tuple(cancelled_runs),
        )

    def _restore(
        self,
        conn: psycopg.Connection[Any],
        actor: Actor,
        view: ControlView,
        level: KillLevel,
        reason: str,
        now: datetime,
        session_hash: str,
    ) -> KillOutcome:
        if actor.function not in levels.RESTORE_FUNCTIONS:
            raise OpsForbidden(
                "a restore is signed by the command and the compliance function, one person each",
                code="RESTORE_FUNCTION_REQUIRED",
            )
        for (expired,) in conn.execute("SELECT ops_restore_expire()").fetchall():
            audit.append(
                conn,
                kind="kill_restore_expired",
                actor_type="system",
                actor_id="system:ops-control",
                subject=f"control:restore:{expired}",
                payload={"restore_id": str(expired), "ttl_s": levels.RESTORE_TTL_S},
                occurred_at=now,
            )
        pending = conn.execute(
            "SELECT restore_id, to_level, requested_by, requested_function FROM ops_kill_restore"
            " WHERE state = 'pending'"
        ).fetchone()
        if pending is None:
            return self._request_restore(conn, actor, view, level, reason, now, session_hash)
        restore_id, to_level, requested_by, requested_function = (
            str(pending[0]),
            KillLevel(pending[1]),
            str(pending[2]),
            ApprovalFunction(pending[3]),
        )
        if to_level is not level:
            raise OpsConflict(
                f"restore {restore_id} to {to_level.value} is pending; sign it or let it expire",
                code="RESTORE_TARGET_MISMATCH",
                details={"restore_id": restore_id, "to_level": to_level.value},
            )
        if requested_by == actor.user_id:
            raise OpsConflict(
                f"restore {restore_id} already carries your signature; it needs the other function",
                code="RESTORE_AWAITS_SECOND_FUNCTION",
                details={"restore_id": restore_id},
            )
        if requested_function is actor.function:
            raise OpsForbidden(
                f"restore {restore_id} was signed by {requested_function.value}; the second signature must"
                " come from the other function",
                code="RESTORE_SAME_FUNCTION",
                details={"restore_id": restore_id},
            )
        return self._complete_restore(
            conn, actor, view, restore_id, requested_by, requested_function, level, reason, now, session_hash
        )

    def _check_chain(self, conn: psycopg.Connection[Any]) -> dict[str, Any]:
        if self.chain_check is None:
            raise OpsConflict(
                "the audit chain cannot be verified here, so the platform stays stopped",
                code="AUDIT_CHAIN_UNVERIFIED",
            )
        report = self.chain_check(conn)
        if not report.ok:
            raise OpsConflict(
                f"the audit chain fails verification at seq {report.first_bad_seq}; restore refused",
                code="AUDIT_CHAIN_UNVERIFIED",
                details={"first_bad_seq": report.first_bad_seq, "problems": list(report.problems[:3])},
            )
        return {"audit_chain_verified": True}

    def _request_restore(
        self,
        conn: psycopg.Connection[Any],
        actor: Actor,
        view: ControlView,
        level: KillLevel,
        reason: str,
        now: datetime,
        session_hash: str,
    ) -> KillOutcome:
        checks = self._check_chain(conn)
        restore_id = f"RST-{secrets.token_hex(6).upper()}"
        checklist = {
            "attested_by_signers": list(levels.RESTORE_CHECKLIST),
            "automatic": checks,
        }
        conn.execute(
            "SELECT ops_restore_request(%s, %s, %s, %s, %s, %s)",
            (actor.user_id, session_hash, restore_id, level.value, reason, Jsonb(checklist)),
        )
        awaiting = next(f for f in levels.RESTORE_FUNCTIONS if f is not actor.function)
        audit.append(
            conn,
            kind="kill_restore_requested",
            actor_type="user",
            actor_id=actor.user_id,
            subject=f"control:restore:{restore_id}",
            payload={
                "restore_id": restore_id,
                "from": view.kill_level.value,
                "to": level.value,
                "reason": reason,
                "function": actor.function.value,
                "awaiting_function": awaiting.value,
                "checklist": checklist,
                "expires_in_s": levels.RESTORE_TTL_S,
                **self._scenario_at(),
            },
            occurred_at=now,
        )
        return KillOutcome(
            state=view.state(), status="restore_pending", restore_id=restore_id, awaiting_function=awaiting
        )

    def _complete_restore(
        self,
        conn: psycopg.Connection[Any],
        actor: Actor,
        view: ControlView,
        restore_id: str,
        requested_by: str,
        requested_function: ApprovalFunction,
        level: KillLevel,
        reason: str,
        now: datetime,
        session_hash: str,
    ) -> KillOutcome:
        checks = self._check_chain(conn)
        row = conn.execute(
            "SELECT ops_restore_complete(%s, %s, %s, %s)", (actor.user_id, session_hash, restore_id, now)
        ).fetchone()
        assert row is not None
        mode = DegradedMode(row[0]["mode_to"])
        signers = [requested_by, actor.user_id]
        record = audit.append(
            conn,
            kind="kill_switch_restored",
            actor_type="user",
            actor_id=actor.user_id,
            subject=f"control:kill:{level.value}",
            payload={
                "restore_id": restore_id,
                "from": view.kill_level.value,
                "to": level.value,
                "signed_by": [
                    {"user_id": requested_by, "function": requested_function.value},
                    {"user_id": actor.user_id, "function": actor.function.value},
                ],
                "reason": reason,
                "checks": checks,
                "degraded_mode": {"from": view.degraded_mode.value, "to": mode.value},
                **self._scenario_at(),
            },
            occurred_at=now,
        )
        events: list[Contract] = [KillSwitchChanged(kill_level=level, changed_by=signers, reason=reason)]
        if mode is not view.degraded_mode:
            events.append(ModeChanged(run_mode=view.run_mode, degraded_mode=mode, changed_by=actor.user_id))
        self._enqueue(conn, events, now, f"audit-{record.seq}", view.run_mode)
        return KillOutcome(
            state=ControlView(level, mode, view.run_mode, tuple(signers), now).state(),
            status="restored",
            restore_id=restore_id,
        )

    # ---- degraded modes --------------------------------------------------------------------------------

    def set_mode(
        self, conn: psycopg.Connection[Any], *, user_id: str, mode: DegradedMode, reason: str
    ) -> ControlState:
        """Manual floor. Anyone who may pull the kill switch (or the platform admin) may raise it; only the
        command function may lower it, and never below what the kill level and active signals require."""
        try:
            with conn.transaction():
                state = self._set_mode(conn, user_id=user_id, mode=mode, reason=reason.strip())
        except OpsError:
            raise
        except psycopg.Error as error:
            raise from_db_error(error) from error
        self._after_commit(conn)
        return state

    def _set_mode(
        self, conn: psycopg.Connection[Any], *, user_id: str, mode: DegradedMode, reason: str
    ) -> ControlState:
        actor = load_actor(conn, user_id)
        view = self._lock(conn)
        now = self.clock()
        previous_manual = manual_floor(conn)
        lowering = levels.mode_rank(mode) < levels.mode_rank(previous_manual)
        if lowering and actor.function not in levels.MODE_LOWER_FUNCTIONS:
            raise OpsForbidden(
                "only the command function lowers a manual degraded mode", code="MODE_LOWER_DENIED"
            )
        if not lowering and not (
            actor.may_trigger
            or levels.MODE_RAISE_ROLES.intersection(actor.roles)
            or actor.function in levels.MODE_LOWER_FUNCTIONS
        ):
            raise OpsForbidden("this role cannot change the degraded mode", code="MODE_CHANGE_DENIED")
        signals = load_signals(conn)
        floor = floor_for(view.kill_level, signals)
        if levels.mode_rank(mode) < levels.mode_rank(floor):
            blockers = sorted(
                s.signal for s in signals.values() if s.active and s.rule.floor is not DegradedMode.M0
            )
            if levels.mode_rank(levels.KILL_MODE_FLOOR[view.kill_level]) > levels.mode_rank(mode):
                blockers.append(f"kill:{view.kill_level.value}")
            raise OpsConflict(
                f"{mode.value} is below the floor {floor.value} set by {', '.join(blockers)};"
                " clear the cause first",
                code="MODE_BELOW_FLOOR",
                details={"floor": floor.value, "blocked_by": blockers},
            )
        self._upsert_manual(conn, mode, reason, actor.user_id, now)
        target = floor_for(view.kill_level, signals, mode)
        conn.execute("SELECT ops_set_mode(%s, %s, %s)", (actor.user_id, target.value, now))
        record = audit.append(
            conn,
            kind="degraded_mode_set",
            actor_type="user",
            actor_id=actor.user_id,
            subject=f"control:mode:{target.value}",
            payload={
                "requested": mode.value,
                "manual_floor": {"from": previous_manual.value, "to": mode.value},
                "degraded_mode": {"from": view.degraded_mode.value, "to": target.value},
                "reason": reason,
                "function": actor.function.value,
                "active_signals": sorted(s.signal for s in signals.values() if s.active),
                **self._scenario_at(),
            },
            occurred_at=now,
        )
        if target is not view.degraded_mode:
            self._enqueue(
                conn,
                [ModeChanged(run_mode=view.run_mode, degraded_mode=target, changed_by=actor.user_id)],
                now,
                f"audit-{record.seq}",
                view.run_mode,
            )
        return ControlView(view.kill_level, target, view.run_mode, (actor.user_id,), now).state()

    def _upsert_manual(
        self, conn: psycopg.Connection[Any], mode: DegradedMode, reason: str, user_id: str, now: datetime
    ) -> None:
        conn.execute(
            "INSERT INTO ops_signal (signal, active, floor_mode, blocks_execution, source, detail, since,"
            " updated_at, updated_by) VALUES (%s, %s, %s, false, 'manual', %s, %s, %s, %s)"
            " ON CONFLICT (signal) DO UPDATE SET active = EXCLUDED.active, floor_mode = EXCLUDED.floor_mode,"
            " detail = EXCLUDED.detail, since = EXCLUDED.since, updated_at = EXCLUDED.updated_at,"
            " updated_by = EXCLUDED.updated_by",
            (levels.MANUAL_SIGNAL, mode is not DegradedMode.M0, mode.value, reason, now, now, user_id),
        )

    def reconcile(self, conn: psycopg.Connection[Any], readings: Sequence[Reading] = ()) -> ReconcileReport:
        """Apply `FAULT_*` flags and probe readings: update signal rows, then move the mode to the floor they
        set (up or down, never below the kill level's or the manual floor). Audits every transition."""
        try:
            with conn.transaction():
                report = self._reconcile(conn, list(readings))
        except psycopg.Error as error:
            raise from_db_error(error) from error
        if report.changed:
            self._after_commit(conn)
        return report

    def _reconcile(self, conn: psycopg.Connection[Any], readings: list[Reading]) -> ReconcileReport:
        view = self._lock(conn)
        now = self.clock()
        if self.feed_probe:
            weather = weather_reading(conn)
            if weather is not None:
                readings.append(weather)
        previous = load_signals(conn)
        current = evaluate(previous, fault_flags(self.env), readings)
        raised: list[str] = []
        cleared: list[str] = []
        for name, state in current.items():
            before = previous.get(name)
            if before == state:
                continue
            was_active = bool(before and before.active)
            since = now if state.active and not was_active else None
            conn.execute(
                "INSERT INTO ops_signal (signal, active, floor_mode, blocks_execution, source, detail,"
                " fail_streak, ok_streak, since, updated_at, updated_by)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (signal) DO UPDATE SET active = EXCLUDED.active,"
                " floor_mode = EXCLUDED.floor_mode,"
                " blocks_execution = EXCLUDED.blocks_execution, source = EXCLUDED.source,"
                " detail = EXCLUDED.detail, fail_streak = EXCLUDED.fail_streak,"
                " ok_streak = EXCLUDED.ok_streak,"
                " since = coalesce(EXCLUDED.since, CASE WHEN EXCLUDED.active THEN ops_signal.since END),"
                " updated_at = EXCLUDED.updated_at, updated_by = EXCLUDED.updated_by",
                (
                    name,
                    state.active,
                    state.rule.floor.value,
                    state.rule.blocks_execution,
                    state.source,
                    state.detail,
                    state.fail_streak,
                    state.ok_streak,
                    since,
                    now,
                    RECONCILER,
                ),
            )
            if state.active != was_active:
                (raised if state.active else cleared).append(name)
                rule = state.rule
                audit.append(
                    conn,
                    kind="ops_signal_raised" if state.active else "ops_signal_cleared",
                    actor_type="system",
                    actor_id=RECONCILER,
                    subject=f"control:signal:{name}",
                    payload={
                        "signal": name,
                        "source": state.source,
                        "detail": state.detail,
                        "floor": rule.floor.value,
                        "blocks_execution": rule.blocks_execution,
                        "rule": rule.entry if state.active else rule.exit,
                    },
                    occurred_at=now,
                )
        target = floor_for(view.kill_level, current, manual_floor(conn))
        active = tuple(sorted(n for n, s in current.items() if s.active))
        if target is not view.degraded_mode:
            conn.execute("SELECT ops_set_mode(%s, %s, %s)", (RECONCILER, target.value, now))
            record = audit.append(
                conn,
                kind="degraded_mode_changed",
                actor_type="system",
                actor_id=RECONCILER,
                subject=f"control:mode:{target.value}",
                payload={
                    "from": view.degraded_mode.value,
                    "to": target.value,
                    "active_signals": list(active),
                    "raised": raised,
                    "cleared": cleared,
                    "kill_level": view.kill_level.value,
                },
                occurred_at=now,
            )
            self._enqueue(
                conn,
                [ModeChanged(run_mode=view.run_mode, degraded_mode=target, changed_by=RECONCILER)],
                now,
                f"audit-{record.seq}",
                view.run_mode,
            )
        return ReconcileReport(view.degraded_mode, target, active, tuple(raised), tuple(cleared))

    # ---- plumbing --------------------------------------------------------------------------------------

    def _enqueue(
        self,
        conn: psycopg.Connection[Any],
        payloads: list[Contract],
        at: datetime,
        key: str,
        run_mode: RunMode,
    ) -> None:
        if self.ledger is None:
            return
        events = [_envelope(p, at=at, key=f"{key}:{i}", run_mode=run_mode) for i, p in enumerate(payloads)]
        self.ledger.enqueue(conn, events)

    def _after_commit(self, conn: psycopg.Connection[Any]) -> None:
        if self.ledger is not None:
            try:
                self.ledger.drain(conn)
            except Exception:
                log.warning("ledger drain after a control change failed; the relay retries", exc_info=True)
        if self.notary is not None:
            try:
                self.notary(conn)
            except Exception:
                log.warning(
                    "audit checkpoint after a control change failed; the periodic run signs", exc_info=True
                )
