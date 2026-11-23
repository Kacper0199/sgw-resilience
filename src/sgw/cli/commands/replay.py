from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from sgw.cli.support import CliError, guard

app = typer.Typer()

MAIN_DATABASE = "sgw"


@app.command()
@guard
def replay(
    scenario: Annotated[str, typer.Option("--scenario", "-s", help="Fixture folder under data/fixtures.")],
    database: Annotated[
        str | None,
        typer.Option("--database", "-d", help="Target database (default: SGW_DATABASE_URL or sgw)."),
    ] = None,
    fresh: Annotated[
        bool, typer.Option("--fresh", help="Delete the ledger and ingest tables first.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Allow --fresh on the main database.")] = False,
    from_start: Annotated[
        bool, typer.Option("--from-start", help="Ignore stored cursors (duplicates are absorbed).")
    ] = False,
    as_of: Annotated[
        str | None,
        typer.Option("--as-of", help="Scenario clock: deliver only events known by then (ISO, UTC)."),
    ] = None,
    page_size: Annotated[int, typer.Option("--page-size", min=1, help="Events per adapter page.")] = 500,
    export: Annotated[
        Path | None, typer.Option("--export", help="Write the ledger as canonical JSONL.")
    ] = None,
) -> None:
    """Replay a scenario through adapters, outbox, ledger relay and DQ checks (FAULT_FEED_* honoured)."""
    import psycopg

    from sgw.ingest import ledger
    from sgw.ingest.db import connect, database_url, owner_database_url
    from sgw.ingest.scenario import ScenarioError
    from sgw.pipeline.replay import replay_scenario, reset_replay_state

    clock = _parse_clock(as_of)
    url = database_url(database)
    target = database or url.rsplit("/", 1)[-1].split("?", 1)[0]
    if fresh and target == MAIN_DATABASE and not yes:
        raise CliError("--fresh on the main database deletes its ledger; add --yes to confirm")
    try:
        if fresh:
            with connect(owner_database_url(target)) as owner:
                removed = reset_replay_state(owner)
            typer.echo(f"reset {target}: " + ", ".join(f"{k}={v}" for k, v in removed.items()))
        with connect(url) as conn:
            report = replay_scenario(
                conn,
                scenario,
                env=os.environ,
                page_size=page_size,
                as_of=clock,
                from_start=from_start,
            )
            if export is not None:
                ledger.export_ledger(conn, export)
    except ScenarioError as error:
        raise CliError(str(error)) from None
    except psycopg.Error as error:
        raise CliError(f"database error: {str(error).strip().splitlines()[0]}") from None

    for o in report.outcomes:
        failed = ", ".join(f"{c.name} ({c.severity}: {c.observed})" for c in o.failed_checks)
        counts = f"in={o.rows_in} out={o.rows_out} q={o.rows_quarantined}"
        line = f"{o.asset:<18} {o.status:<8} run={o.run_id} {counts}"
        typer.echo(
            line + (f" error={o.error}" if o.error else "") + (f"\n  failed: {failed}" if failed else "")
        )
    lr = report.ledger
    typer.echo(
        f"ledger: count={lr.count} head={lr.max_seq or 0} gapless={lr.gapless} sha256={report.ledger_sha256}"
        + (f" exported={export}" if export else "")
    )
    typer.echo(f"dq: error_failed={report.error_failures} warn_failed={report.warn_failures}")
    if not report.ok:
        raise typer.Exit(1)


def _parse_clock(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise CliError(f"--as-of is not an ISO timestamp: {value!r}") from None
    if parsed.tzinfo is None:
        raise CliError("--as-of needs a zone, e.g. 2024-09-27T00:00:00Z")
    return parsed
