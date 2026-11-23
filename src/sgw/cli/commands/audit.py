from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Annotated

import typer

from sgw.cli.support import DB_NAME, CliError, guard, load_credentials

app = typer.Typer(name="audit", help="Audit chain: signing key, checkpoints, verification, co-sign tasks.")

Database = Annotated[str, typer.Option("--database", "-d", help="Target database.")]


DATABASE_URL_ENV = "SGW_AUDIT_DATABASE_URL"


def _dsn(database: str) -> str:
    """SGW_AUDIT_DATABASE_URL (containers: runtime role) wins; else the owner DSN from var/secrets."""
    return os.environ.get(DATABASE_URL_ENV) or load_credentials().owner_dsn(database)


@app.command("keygen")
@guard
def keygen(
    database: Database = DB_NAME,
    record: Annotated[bool, typer.Option(help="Append the rotation to the audit chain.")] = True,
) -> None:
    """Create an Ed25519 signing key (0600, under var/secrets/audit) and make it the active key."""
    import psycopg

    from sgw.approval import audit
    from sgw.approval.signer import Keyring, default_paths, generate_key

    paths = default_paths()
    previous = Keyring.load(paths.keyring).active
    now = datetime.now(UTC)
    signer = generate_key(paths, now)
    typer.echo(f"active key {signer.key_id} (previous {previous or 'none'}); keyring {paths.keyring}")
    if not record:
        return
    try:
        with psycopg.connect(_dsn(database), autocommit=True) as conn, conn.transaction():
            audit.append(
                conn,
                kind="audit_key_rotated",
                actor_type="system",
                actor_id="system:cli",
                subject=signer.key_id,
                payload={"key_id": signer.key_id, "public_key": signer.public_key_hex, "previous": previous},
                occurred_at=now,
            )
    except psycopg.Error as error:
        raise CliError(f"key created, but recording the rotation in {database} failed: {error}") from None


@app.command("checkpoint")
@guard
def checkpoint(
    database: Database = DB_NAME,
    every: Annotated[int, typer.Option(help="Repeat every N seconds (0 = once).", min=0)] = 0,
) -> None:
    """Sign the audit head with the active key and write the anchor file."""
    import psycopg

    from sgw.approval import audit
    from sgw.approval.signer import active_signer, default_paths

    paths = default_paths()
    signer = active_signer(paths)
    if signer is None:
        raise CliError("no active signing key; run `uv run sgw audit keygen` first")
    anchors = audit.AnchorStore(paths.anchors)
    while True:
        with psycopg.connect(_dsn(database), autocommit=True) as conn:
            cp = audit.checkpoint(conn, signer, anchors)
        typer.echo(f"signed seq {cp.seq} with {cp.key_id}" if cp else "head already signed")
        if not every:
            return
        time.sleep(every)


@app.command("verify")
@guard
def verify(database: Database = DB_NAME) -> None:
    """Recompute the chain and check checkpoints and anchors; exit 1 with the first bad seq on failure."""
    import psycopg

    from sgw.approval import audit
    from sgw.approval.signer import Keyring, default_paths

    paths = default_paths()
    with psycopg.connect(_dsn(database), autocommit=True) as conn:
        report = audit.verify(
            conn, keyring=Keyring.load(paths.keyring), anchors=audit.AnchorStore(paths.anchors)
        )
    result = report.result()
    typer.echo(result.model_dump_json())
    for problem in report.problems:
        typer.echo(f"  {problem}")
    if not report.ok:
        raise typer.Exit(1)


@app.command("cosign-tasks")
@guard
def cosign_tasks(
    database: Database = DB_NAME,
    flag: Annotated[bool, typer.Option(help="Write one audit record per overdue task.")] = False,
    at: Annotated[
        str | None, typer.Option(help="Scenario time (ISO 8601) to judge due dates; default now.")
    ] = None,
) -> None:
    """List open break-glass co-sign tasks (each is also an after-action flag)."""
    import psycopg

    from sgw.approval.breakglass import BreakGlassService
    from sgw.approval.breakglass_policy import ReferenceGovernance
    from sgw.approval.policy import ReferencePolicy
    from sgw.approval.service import ApprovalService

    when = datetime.fromisoformat(at).astimezone(UTC) if at else datetime.now(UTC)
    approvals = ApprovalService(ReferencePolicy(), scenario_clock=lambda: when)
    service = BreakGlassService(approvals, ReferenceGovernance())
    with psycopg.connect(_dsn(database), autocommit=True) as conn:
        if flag:
            typer.echo(f"flagged overdue: {service.flag_overdue(conn)}")
        for t in service.tasks(conn):
            state = "OVERDUE" if t.overdue else "open"
            typer.echo(
                f"{t.proposal_id} v{t.proposal_version} by {t.ic_id}: {state}, due {t.cosign_due.isoformat()}"
            )


@app.command("policy-data")
@guard
def policy_data() -> None:
    """Regenerate policy/sgw/governance/data.json (break-glass and envelope rules)."""
    from sgw.approval import breakglass_policy

    breakglass_policy.write()
    typer.echo(f"wrote {breakglass_policy.DATA_PATH}")
