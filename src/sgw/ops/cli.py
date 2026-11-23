"""Ops CLI: control state, capabilities and the degraded-mode reconciler. Run it as
`uv run python -m sgw.ops.cli <command>` until `sgw ops` is registered (`src/sgw/cli/commands/ops.py` with
`from sgw.ops.cli import app`).

    status [--database sgw]            kill level, degraded mode, active signals, capabilities (JSON)
    reconcile [--database sgw]         apply FAULT_* flags and configured probes once
    watch [--database sgw] [--every 5] reconcile until stopped (the API process does this on its own)
    rules                              the mode ladder and the signal table (entry, behaviour, exit)
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import psycopg
import typer

from sgw.ingest.db import database_url
from sgw.ops import levels
from sgw.ops.control import load_signals, read_control
from sgw.ops.reconciler import DEFAULT_INTERVAL_S, reconcile_once
from sgw.ops.wiring import build_service

app = typer.Typer(help="Control plane: kill switch, degraded modes, FAULT_* drills.", no_args_is_help=True)
DATABASE = typer.Option("sgw", "--database", "-d", help="Target database.")


def _connect(database: str) -> psycopg.Connection[Any]:
    return psycopg.connect(database_url(database), autocommit=True, application_name="sgw-ops")


@app.command()
def status(database: str = DATABASE) -> None:
    """Print the control state, active signals and capabilities."""
    with _connect(database) as conn:
        view = read_control(conn)
        signals = load_signals(conn)
        caps = build_service().capabilities(conn)
    typer.echo(
        json.dumps(
            {
                "kill_level": view.kill_level.value,
                "degraded_mode": view.degraded_mode.value,
                "updated_by": list(view.updated_by),
                "active_signals": sorted(n for n, s in signals.items() if s.active),
                "capabilities": {c.value: ok for c, ok in caps.items()},
            },
            indent=2,
        )
    )


@app.command()
def reconcile(database: str = DATABASE) -> None:
    """Apply FAULT_* flags and probes once; prints the mode before and after."""
    with _connect(database) as conn:
        report = reconcile_once(conn, build_service())
    typer.echo(
        f"{report.before.value} -> {report.after.value}; active: {', '.join(report.active) or 'none'};"
        f" raised: {', '.join(report.raised) or 'none'}; cleared: {', '.join(report.cleared) or 'none'}"
    )


@app.command()
def watch(
    database: str = DATABASE,
    every: float = typer.Option(DEFAULT_INTERVAL_S, "--every", help="Seconds between reconciles."),
    count: int = typer.Option(0, "--count", help="Stop after this many rounds (0: run until stopped)."),
) -> None:
    """Reconcile in a loop."""
    service = build_service()
    rounds = 0
    with _connect(database) as conn:
        while count == 0 or rounds < count:
            report = reconcile_once(conn, service)
            if report.changed:
                typer.echo(
                    f"{report.before.value} -> {report.after.value} ({', '.join(report.active) or 'none'})"
                )
            rounds += 1
            if count == 0 or rounds < count:
                time.sleep(max(0.5, every))


@app.command()
def rules() -> None:
    """Print the mode ladder and the signal table."""
    typer.echo(
        json.dumps(
            {
                "modes": [
                    {"mode": m.mode.value, "name": m.name, "available": m.available, "disabled": m.disabled}
                    for m in levels.MODE_LADDER
                ],
                "signals": [
                    {
                        "signal": r.signal,
                        "flag": r.fault_flag,
                        "floor": r.floor.value,
                        "blocks_execution": r.blocks_execution,
                        "entry": r.entry,
                        "behaviour": r.behaviour,
                        "exit": r.exit,
                    }
                    for r in levels.SIGNAL_RULES
                ],
                "kill_levels": {
                    k.value: sorted(c.value for c in levels.KILL_REMOVES[k]) for k in levels.KILL_REMOVES
                },
                "fault_flags_set": sorted(
                    r.fault_flag for r in levels.SIGNAL_RULES if os.environ.get(r.fault_flag)
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    app()
