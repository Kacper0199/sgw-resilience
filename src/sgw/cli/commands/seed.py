from __future__ import annotations

import os
from typing import Annotated

import typer

from sgw.cli.support import DB_NAME, CliError, guard, load_credentials, load_demo_env

app = typer.Typer()


@app.command()
@guard
def seed(
    database: Annotated[str, typer.Option("--database", "-d", help="Target database.")] = DB_NAME,
    demo: Annotated[
        bool,
        typer.Option(
            "--demo",
            help="Whole demo database: users with DEMO_PASSWORD, reference rows, map geometry, Helene replay,"
            " PS-17 queue at advisory N, ETR publication, corpus index.",
        ),
    ] = False,
) -> None:
    """Load the K18 users and the Helene T3 crew pre-positioning proposal (synthetic data); idempotent."""
    import psycopg

    from sgw.approval.seed import SeedError, run_seed

    os.environ.update({k: v for k, v in load_demo_env().items() if k not in os.environ})
    if demo:
        _seed_demo(database)
        return
    try:
        report = run_seed(load_credentials().owner_dsn(database))
    except (psycopg.Error, SeedError) as error:
        raise CliError(f"seed failed: {error}") from None
    state = "created" if report.proposal_created else "already present"
    typer.echo(
        f"{database}: {report.users} users; proposal {report.proposal_id} {state} (ETag {report.etag})"
    )


def _seed_demo(database: str) -> None:
    import psycopg

    from sgw.approval.demo_seed import seed_demo
    from sgw.approval.seed import SeedError
    from sgw.reference import load

    missing = load.missing_sources()
    if missing:
        paths = " ".join(str(p) for p in missing)
        raise CliError(
            f"map reference file missing: {paths}; restore it with `git checkout -- {paths}`"
            " (county outlines: `web/scripts/build_geo.py` rebuilds both copies)"
        )
    env = load_demo_env()
    password = os.environ.get("DEMO_PASSWORD")
    if not env and not password:
        raise CliError("run `uv run sgw bootstrap` (var/demo.env) or set DEMO_PASSWORD first")
    try:
        r = seed_demo(load_credentials().owner_dsn(database), password, env=env)
    except (psycopg.Error, SeedError, RuntimeError) as error:
        raise CliError(f"demo seed failed: {error}") from None
    typer.echo(
        f"{database}: {r.users} users; {r.regions} regions and {r.assets} located assets;"
        f" ledger head {r.ledger_head}; {r.cases} decision cases (advisory N);"
        f" {r.etr_rows} ETR rows; {len(r.risk_snapshots)} risk snapshots; crew plan {r.crew_plan};"
        f" corpus {r.corpus}"
    )


@app.command("policy-test")
@guard
def policy_test() -> None:
    """Check, format-check and test policy/*.rego with OPA 1.22.4 (local binary or the pinned image)."""
    from sgw.approval import policy_data
    from sgw.approval.opa_cli import OpaRunError, run_policy_tests

    if not policy_data.is_current():
        raise CliError("policy/sgw/tiers/data.json is out of date; run `uv run sgw policy-data`")
    try:
        result = run_policy_tests(policy_data.POLICY_DIR)
    except OpaRunError as error:
        raise CliError(str(error)) from None
    typer.echo(f"rego: {result.passed} passed, 0 failed, coverage {result.coverage_pct:.1f}%")


@app.command("policy-data")
@guard
def policy_data_cmd() -> None:
    """Regenerate policy/sgw/tiers/data.json from the K8 tier table and K10 policy numbers, and the dispatch
    policy data policy/sgw/crew_dispatch/data.json."""
    from sgw.approval import policy_data
    from sgw.dispatch import policy as dispatch_policy

    typer.echo(f"wrote {policy_data.write()}")
    dispatch_policy.write()
    typer.echo(f"wrote {dispatch_policy.DATA_PATH}")
