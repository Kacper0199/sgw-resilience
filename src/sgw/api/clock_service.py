"""Scenario clock persistence and commands: `control_state.scenario_clock`, audit record, ledger event."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from sgw.api import audit_log, ledger
from sgw.api.clock import (
    ClockCommandError,
    ClockState,
    ClockView,
    ScenarioClock,
    apply_command,
    scenario_def,
)
from sgw.api.errors import Unprocessable
from sgw.api.sessions import AuthUser
from sgw.contracts.api_models import ScenarioCommand, ScenarioState
from sgw.contracts.events import ClockBreached, ScenarioClockChanged
from sgw.contracts.vocab import RunMode


def view_from_control(snap: ledger.ControlSnapshot, default_scenario: str, clock: ScenarioClock) -> ClockView:
    raw = snap.scenario_clock or {}
    if raw:
        state = ClockState.from_json(raw)
    else:
        state = ClockState.initial(scenario_def(default_scenario), clock.wall.now())
    return ClockView(state, snap.scenario_mode, snap.run_mode)


async def load(conn: AsyncConnection[Any], clock: ScenarioClock, default_scenario: str) -> None:
    """Make sure the control row exists and holds a clock; install it in the process clock."""
    await ledger.ensure_control_row(conn)
    snap = await ledger.read_control(conn)
    assert snap is not None
    view = view_from_control(snap, default_scenario, clock)
    if not snap.scenario_clock:
        await conn.execute(
            "UPDATE control_state SET scenario_clock = %s WHERE id = 1 AND scenario_clock = '{}'::jsonb",
            (Jsonb(view.state.to_json()),),
        )
    clock.set_view(view)


def sync_from_control(snap: ledger.ControlSnapshot, clock: ScenarioClock, default_scenario: str) -> None:
    if snap.scenario_clock:
        clock.set_view(view_from_control(snap, default_scenario, clock))


async def command(
    conn: AsyncConnection[Any], clock: ScenarioClock, cmd: ScenarioCommand, actor: AuthUser
) -> ScenarioState:
    await conn.execute("SELECT pg_advisory_xact_lock(%s)", (audit_log.AUDIT_LOCK_KEY,))
    await conn.execute("SELECT 1 FROM control_state WHERE id = 1 FOR UPDATE")
    snap = await ledger.read_control(conn)
    if snap is None:
        raise Unprocessable("control_state is missing; restart the API", code="CONTROL_STATE_MISSING")
    view = view_from_control(snap, clock.definition.name, clock)
    sdef = scenario_def(view.state.scenario)
    wall_now = clock.wall.now()
    try:
        moved = apply_command(view.state, cmd, wall_now, sdef)
    except ClockCommandError as exc:
        raise Unprocessable(str(exc), code="SCENARIO_COMMAND_INVALID") from exc
    await conn.execute(
        "UPDATE control_state SET scenario_clock = %s WHERE id = 1", (Jsonb(moved.state.to_json()),)
    )
    scenario_time = moved.state.scenario_now(wall_now, sdef)
    payload = ScenarioClockChanged(
        scenario_time_utc=scenario_time,
        speed=moved.state.effective_speed(wall_now, sdef),  # type: ignore[arg-type]
        bookmark=moved.bookmark,
    ).model_dump(mode="json")
    seq = await ledger.append_platform_event(
        conn,
        type_name="ScenarioClockChanged",
        payload=payload,
        scenario_time=scenario_time,
        wall_now=wall_now,
        run_mode=view.run_mode,
    )
    await audit_log.append(
        conn,
        kind="scenario_clock_changed",
        actor_type="user",
        actor_id=actor.user_id,
        subject=f"scenario:{moved.state.scenario}",
        payload={"command": cmd.model_dump(mode="json"), "result": payload, "ledger_seq": seq},
        occurred_at=wall_now,
    )
    await emit_clock_breaches(conn, scenario_now=scenario_time, wall_now=wall_now, run_mode=view.run_mode)
    clock.set_view(ClockView(moved.state, view.mode, view.run_mode))
    return clock.snapshot()


async def switch_scenario(
    conn: AsyncConnection[Any], clock: ScenarioClock, scenario: str, at: datetime, actor: AuthUser
) -> ScenarioState:
    """Make `scenario` the active one, paused at `at` (R34 B2 scenario packs): the stored clock, a ledger
    event and an audit record, like a clock command."""
    await conn.execute("SELECT pg_advisory_xact_lock(%s)", (audit_log.AUDIT_LOCK_KEY,))
    await conn.execute("SELECT 1 FROM control_state WHERE id = 1 FOR UPDATE")
    snap = await ledger.read_control(conn)
    if snap is None:
        raise Unprocessable("control_state is missing; restart the API", code="CONTROL_STATE_MISSING")
    sdef = scenario_def(scenario)
    wall_now = clock.wall.now()
    view = view_from_control(snap, clock.definition.name, clock)
    state = ClockState(scenario, wall_now, sdef.clamp(at), 0, view.state.play_speed)
    await conn.execute("UPDATE control_state SET scenario_clock = %s WHERE id = 1", (Jsonb(state.to_json()),))
    payload = ScenarioClockChanged(
        scenario_time_utc=state.anchor_scenario, speed=0, bookmark=None
    ).model_dump(mode="json")
    seq = await ledger.append_platform_event(
        conn,
        type_name="ScenarioClockChanged",
        payload=payload,
        scenario_time=state.anchor_scenario,
        wall_now=wall_now,
        run_mode=view.run_mode,
    )
    await audit_log.append(
        conn,
        kind="scenario_clock_changed",
        actor_type="user",
        actor_id=actor.user_id,
        subject=f"scenario:{scenario}",
        payload={
            "command": {"action": "load_scenario", "scenario": scenario},
            "result": payload,
            "ledger_seq": seq,
        },
        occurred_at=wall_now,
    )
    clock.set_view(ClockView(state, view.mode, view.run_mode))
    return clock.snapshot()


_BREACHED = """
SELECT dc.decision_case_id, dc.effective_decide_by_utc, dc.clock_kind,
       (SELECT p.proposal_id FROM proposal p
         WHERE p.decision_case_id = dc.decision_case_id AND p.state IN ('proposed', 'in_review', 'escalated')
         ORDER BY p.created_at DESC, p.proposal_id LIMIT 1) AS proposal_id
FROM decision_case dc
WHERE dc.effective_decide_by_utc <= %s
  AND NOT EXISTS (SELECT 1 FROM proposal p
                   WHERE p.decision_case_id = dc.decision_case_id AND p.state IN ('approved', 'executed'))
ORDER BY dc.effective_decide_by_utc, dc.decision_case_id
"""


def breach_key(decision_case_id: str, decide_by: datetime) -> str:
    return f"{ledger.PLATFORM_SOURCE}:ClockBreached:{decision_case_id}:{decide_by.isoformat()}"


async def emit_clock_breaches(
    conn: AsyncConnection[Any], *, scenario_now: datetime, wall_now: datetime, run_mode: RunMode
) -> list[int]:
    """K2 `ClockBreached` once per decision case and effective decide-by that the scenario clock has passed
    with no approved or executed proposal (idempotent through the ledger dedup key); the WP-37 webhook
    pipeline delivers it to `clocks:read` subscribers."""
    cur = await conn.execute(_BREACHED, (scenario_now,))
    seqs: list[int] = []
    for case_id, decide_by, clock_kind, proposal_id in await cur.fetchall():
        key = breach_key(case_id, decide_by)
        seen = await conn.execute("SELECT 1 FROM event WHERE dedup_key = %s", (key,))
        if await seen.fetchone():
            continue
        payload = ClockBreached(
            decision_case_id=case_id,
            proposal_id=proposal_id,
            effective_decide_by_utc=decide_by,
            breached_at_utc=decide_by,
            clock_kind=clock_kind,
        ).model_dump(mode="json")
        seqs.append(
            await ledger.append_platform_event(
                conn,
                type_name="ClockBreached",
                payload=payload,
                scenario_time=scenario_now,
                wall_now=wall_now,
                run_mode=run_mode,
                dedup_key=key,
            )
        )
    return seqs
