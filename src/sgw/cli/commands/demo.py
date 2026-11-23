"""`sgw demo`: PS-17 story bookmarks (build, list, goto) and the demo smoke."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from sgw.cli.support import DB_NAME, CliError, guard, load_credentials, load_demo_env

app = typer.Typer(
    name="demo", help="Demo bookmarks of the PS-17 story and the demo smoke.", no_args_is_help=True
)

BUILD_DB = "sgw_demo_build"


@app.command("list")
@guard
def list_bookmarks() -> None:
    """The bookmarks, in story order, and whether each one is built."""
    from sgw.demo.bookmarks import BOOKMARKS
    from sgw.demo.runner import built

    state = built(load_credentials().admin_dsn())
    for b in BOOKMARKS:
        typer.echo(f"{b.id:<14} {'built  ' if state[b.id] else 'missing'} {b.scenario_time}  {b.title}")


@app.command()
@guard
def goto(
    bookmark_id: Annotated[
        str, typer.Argument(metavar="BOOKMARK", help="before-n, at-n, at-n1, signed, ...")
    ],
    database: Annotated[str, typer.Option("--database", "-d", help="Database to replace.")] = DB_NAME,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    jobs: Annotated[
        bool,
        typer.Option(
            "--jobs/--no-jobs",
            help="Run the scenario jobs at the moment's time, as the API's Load moment does (default on).",
        ),
    ] = True,
) -> None:
    """Replace a database with a bookmark's state (a template copy, seconds), then run the scenario jobs at
    the moment's time (advisory queue, zone rules, exercise injects, with the stack's flags: on unless
    SGW_ZONE_RULES / SGW_SCENARIO_INJECTS say 0), so the state equals a Load moment; a running API follows."""
    import psycopg

    from sgw.cli.commands.stack import retire_anchors
    from sgw.demo import snapshots
    from sgw.demo.bookmarks import bookmark

    try:
        bm = bookmark(bookmark_id)
    except KeyError as error:
        raise CliError(str(error.args[0])) from None
    try:
        snapshots.check_target(database)
    except snapshots.TargetRefused as error:
        raise CliError(str(error)) from None
    if not yes:
        typer.confirm(f"Replace database '{database}' with bookmark {bm.id}?", abort=True)
    try:
        report = snapshots.goto(load_credentials().admin_dsn(), bm, database, retire=retire_anchors)
    except (LookupError, psycopg.Error) as error:
        raise CliError(f"goto {bm.id} failed: {error}") from None
    typer.echo(f"{database} is now at bookmark {bm.id} ({bm.title}), {report.seconds:.2f} s")
    if jobs:
        typer.echo(_moment_jobs(load_credentials().admin_dsn(), database, bm.scenario_time))
    for path in report.retired:
        typer.echo(f"audit anchors retired: {path}")
    after = f"; next: {bm.run_graph} at {bm.run_at}" if bm.run_graph else "; next: the decisions rules raised"
    typer.echo(f"scenario clock {bm.scenario_time}{after}")


def _moment_jobs(admin_dsn: str, database: str, scenario_time: str) -> str:
    from datetime import datetime

    import psycopg
    from psycopg.conninfo import make_conninfo

    from sgw.api import scenario_jobs
    from sgw.models.clocks import zone_cases

    for flag in (zone_cases.FLAG_ENV, zone_cases.INJECTS_FLAG_ENV):
        os.environ.setdefault(flag, "1")
    at = datetime.fromisoformat(scenario_time.replace("Z", "+00:00"))
    try:
        sync = scenario_jobs.after_load(make_conninfo(admin_dsn, dbname=database), at)
    except psycopg.Error as error:
        return f"scenario jobs not run here ({type(error).__name__}); a running API runs them within seconds"
    return f"scenario jobs at {scenario_time}: advisory {sync.advisory or 'none'}"


@app.command()
@guard
def build(
    database: Annotated[str, typer.Option("--database", "-d", help="Build database (not sgw).")] = BUILD_DB,
    no_capture: Annotated[
        bool, typer.Option("--no-capture", help="Do not rewrite data/fixtures/eventlog/.")
    ] = False,
) -> None:
    """Seed a build database with the stack's demo passwords, drive the story on a private host API and
    replay gateway, and store each bookmark as a template database (and each key run as a K19 event log)."""
    from sgw.api.users import demo_password_for
    from sgw.approval.demo_seed import seed_demo
    from sgw.demo import eventlog, runner

    env = load_demo_env()
    shared = os.environ.get("DEMO_PASSWORD")
    if not env and not shared:
        raise CliError("run `uv run sgw bootstrap` (var/demo.env) or set DEMO_PASSWORD first")

    def password_for(user_id: str) -> str:
        value = demo_password_for(user_id, env) or shared
        if not value:
            raise CliError(f"no demo password for {user_id}")
        return value

    def seed(dsn: str) -> None:
        seed_demo(dsn, shared, env=env)

    try:
        report = runner.build(database, password_for, seed, None if no_capture else eventlog.eventlog_dir())
    except (RuntimeError, ValueError) as error:
        raise CliError(f"demo build failed: {error}") from None
    for step in report.steps:
        typer.echo(
            f"{'PASS' if step.ok else 'FAIL'}  {step.n:>2} {step.name} ({step.seconds:.1f} s) {step.detail}"
        )
    for bm_id, seconds in report.snapshot_seconds.items():
        typer.echo(
            f"bookmark {bm_id:<14} snapshot {seconds:.2f} s  eventlog {report.eventlogs.get(bm_id, '-')}"
        )
    typer.echo(
        f"replay hits {report.replay.hits}, misses {report.replay.misses}; seed {report.seed_seconds} s,"
        f" total {report.seconds} s"
    )
    if not report.ok:
        raise CliError("demo build incomplete: see the failing step above")


@app.command()
@guard
def smoke(
    out: Annotated[Path, typer.Option("--out", help="JSON report.")] = Path("out/demo-smoke.json"),
    playback: Annotated[bool, typer.Option(help="Also check K19 playback with the gateway stopped.")] = True,
) -> None:
    """Ten story steps on a scratch database and a private replay stack, with model-provenance asserts, the
    replay hit rate (any miss fails) and K19 playback; exit status = failures."""
    from sgw.demo import runner

    failures = runner.smoke(out.resolve(), playback=playback)
    report = json.loads(out.read_text(encoding="utf-8"))
    for step in report.get("steps", []):
        typer.echo(
            f"{'PASS' if step['ok'] else 'FAIL'}  {step['n']:>2} {step['name']}"
            f" ({step['seconds']:.1f} s) {step['detail']}"
        )
    if "replay" in report:
        r = report["replay"]
        typer.echo(f"replay hit rate {r['hit_rate']} ({r['hits']} hits, {r['misses']} misses)")
    if "playback" in report:
        p = report["playback"]
        typer.echo(
            f"{'PASS' if p['ok'] else 'FAIL'}  playback with the gateway stopped {p.get('detail', '')}"
        )
    if report.get("error"):
        typer.echo(f"error: {report['error']}")
    typer.echo(f"demo smoke: {failures} failure(s), {report.get('seconds')} s; report {out}")
    raise typer.Exit(min(failures, 100))
