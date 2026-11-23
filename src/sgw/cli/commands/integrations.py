"""`sgw integrations ...`: integration tokens, the webhook worker, dead-letter replay, the `/v1` OpenAPI file.

Token commands act as a named platform user (`--as admin_01`) and are audited like the API routes
(`via: cli`). The token is printed once; nothing else ever shows it.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import typer

from sgw.cli.support import guard, load_credentials

app = typer.Typer(
    name="integrations", help="Integration API: tokens, webhooks, OpenAPI v1.", no_args_is_help=True
)

DatabaseOpt = Annotated[
    str | None,
    typer.Option("--database", "-d", help="Database name on the local stack (default: SGW_DATABASE_URL)."),
]
ActorOpt = Annotated[str, typer.Option("--as", help="platform user who acts (audited), e.g. admin_01")]


def _dsn(database: str | None) -> str:
    dsn = load_credentials().runtime_dsn(database) if database else os.environ.get("SGW_DATABASE_URL", "")
    if not dsn:
        typer.echo("set SGW_DATABASE_URL or pass --database", err=True)
        raise typer.Exit(2)
    return dsn


async def _platform_user(conn: Any, user_id: str) -> None:
    cur = await conn.execute("SELECT function FROM app_user WHERE user_id = %s", (user_id,))
    row = await cur.fetchone()
    if row is None or row[0] != "platform":
        typer.echo(f"{user_id} is not a platform user", err=True)
        raise typer.Exit(2)


@app.command("openapi")
@guard
def openapi_cmd(
    check: Annotated[bool, typer.Option(help="fail when the committed file differs")] = False,
) -> None:
    """Write contracts/openapi-v1.json (or check it)."""
    from sgw.integrations import openapi

    if check:
        if openapi.drift():
            typer.echo(
                "contracts/openapi-v1.json is out of date: run `uv run sgw integrations openapi`", err=True
            )
            raise typer.Exit(1)
        typer.echo("contracts/openapi-v1.json is current")
        return
    typer.echo(f"wrote {openapi.write()}")


@app.command("token-create")
@guard
def token_create(
    actor: ActorOpt,
    name: Annotated[str, typer.Option(help="what the token is for")],
    scope: Annotated[
        list[str], typer.Option(help="decisions:read, clocks:read, commitments:read, webhooks:manage")
    ],
    days: Annotated[int, typer.Option(min=1, max=366)] = 90,
    database: DatabaseOpt = None,
) -> None:
    """Create a scoped token; prints it once."""
    from psycopg import AsyncConnection

    from sgw.contracts.vocab import ApiScope
    from sgw.integrations import repository
    from sgw.integrations.keys import load_keys

    scopes = [ApiScope(s) for s in scope]

    async def go() -> tuple[str, str]:
        now = datetime.now(UTC)
        async with await AsyncConnection.connect(_dsn(database)) as conn:
            await _platform_user(conn, actor)
            issued, _ = await repository.create_token(
                conn,
                load_keys(),
                name=name,
                scopes=scopes,
                expires_at=now + timedelta(days=days),
                created_by=actor,
                now=now,
                via="cli",
            )
            await conn.commit()
        return issued.token_id, issued.token

    token_id, token = asyncio.run(go())
    typer.echo(f"token_id {token_id}")
    typer.echo(f"token    {token}")
    typer.echo("store it now; it is not shown again")


@app.command("token-list")
@guard
def token_list(database: DatabaseOpt = None) -> None:
    """List tokens (ids, scopes, state; never the token)."""
    from psycopg import AsyncConnection

    from sgw.integrations import repository

    async def go() -> list[repository.TokenRow]:
        async with await AsyncConnection.connect(_dsn(database)) as conn:
            return await repository.list_tokens(conn)

    now = datetime.now(UTC)
    for t in asyncio.run(go()):
        state = "revoked" if t.revoked_at else ("expired" if t.expires_at <= now else "active")
        typer.echo(f"{t.token_id}  {state:7}  {','.join(t.scopes):45}  {t.name}")


@app.command("token-revoke")
@guard
def token_revoke(token_id: str, actor: ActorOpt, database: DatabaseOpt = None) -> None:
    """Revoke a token and disable its webhook subscriptions."""
    from psycopg import AsyncConnection

    from sgw.integrations import repository

    async def go() -> bool:
        async with await AsyncConnection.connect(_dsn(database)) as conn:
            await _platform_user(conn, actor)
            done = await repository.revoke_token(
                conn, token_id, actor_id=actor, now=datetime.now(UTC), via="cli"
            )
            await conn.commit()
            return done

    typer.echo("revoked" if asyncio.run(go()) else "already revoked")


@app.command("replay-delivery")
@guard
def replay_delivery(delivery_id: str, actor: ActorOpt, database: DatabaseOpt = None) -> None:
    """Give a dead-lettered delivery one more attempt."""
    from psycopg import AsyncConnection

    from sgw.integrations.delivery import replay_dead_letter

    async def go() -> bool:
        async with await AsyncConnection.connect(_dsn(database), autocommit=True) as conn:
            await _platform_user(conn, actor)
            return await replay_dead_letter(conn, delivery_id, actor_id=actor, now=datetime.now(UTC))

    if not asyncio.run(go()):
        typer.echo("no dead-lettered delivery with that id on an active subscription", err=True)
        raise typer.Exit(1)
    typer.echo("queued")


@app.command("worker")
@guard
def worker(
    database: DatabaseOpt = None,
    once: Annotated[bool, typer.Option(help="one fan-out and delivery pass, then exit")] = False,
    interval: Annotated[float, typer.Option(min=0.1, max=60)] = 1.0,
) -> None:
    """Fan out ledger events to webhook deliveries and send them (signed, retried, dead-lettered)."""
    import logging

    from sgw.integrations.worker import WebhookRunner

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    totals = asyncio.run(WebhookRunner(_dsn(database), interval_s=interval).run(once=once))
    if once:
        typer.echo(" ".join(f"{k}={v}" for k, v in sorted(totals.items())))
