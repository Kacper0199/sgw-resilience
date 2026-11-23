"""`sgw api serve` and `sgw api seed-users`: the API process and the K18 demo identities."""

from __future__ import annotations

import os
from typing import Annotated

import typer

from sgw.cli.support import CliError, guard, load_credentials, load_demo_env
from sgw.contracts.identities import PASSWORD_ENV

app = typer.Typer(
    name="api", help="API server (FastAPI, sessions, scenario clock, SSE).", no_args_is_help=True
)

DatabaseOpt = Annotated[
    str | None,
    typer.Option("--database", "-d", help="Database name on the local stack (default: SGW_DATABASE_URL)."),
]


@app.command("serve")
@guard
def serve(
    host: Annotated[str, typer.Option(help="bind address")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="listen port")] = 8200,
    database: DatabaseOpt = None,
    scenario: Annotated[str | None, typer.Option(help="scenario when the clock is empty")] = None,
) -> None:
    """Run the API with uvicorn (runtime role sgw_runtime when --database is given)."""
    import uvicorn

    if database:
        os.environ["SGW_DATABASE_URL"] = load_credentials().runtime_dsn(database)
    if scenario:
        os.environ["SGW_SCENARIO"] = scenario
    if not os.environ.get("SGW_DATABASE_URL"):
        typer.echo("set SGW_DATABASE_URL or pass --database", err=True)
        raise typer.Exit(2)
    uvicorn.run(
        "sgw.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        timeout_keep_alive=75,
        server_header=False,
        log_level="info",
    )


@app.command("seed-users")
@guard
def seed_users(database: DatabaseOpt = None) -> None:
    """Upsert the K18 users with an Argon2id hash of each persona's password (var/demo.env or
    DEMO_PASSWORD_<USER_ID>, else the shared DEMO_PASSWORD; read by name, never printed)."""
    from sgw.api.users import seed_users as run_seed

    env = load_demo_env()
    password = os.environ.get(PASSWORD_ENV)
    if not env and not password:
        typer.echo(f"run `uv run sgw bootstrap` (var/demo.env) or set {PASSWORD_ENV} first", err=True)
        raise typer.Exit(2)
    dsn = os.environ.get("SGW_DATABASE_URL", "")
    if database:
        dsn = load_credentials().owner_dsn(database)
    if not dsn:
        typer.echo("set SGW_DATABASE_URL or pass --database", err=True)
        raise typer.Exit(2)
    try:
        count = run_seed(dsn, password, env=env)
    except ValueError as error:
        raise CliError(str(error)) from None
    typer.echo(f"seeded {count} users")
