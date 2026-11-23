"""Contract commands: `sgw contracts` (regenerate), `sgw contracts-check` (drift, exit 1), `sgw numbers`."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import typer

from sgw.common import numbers as numbers_mod
from sgw.contracts import db_snapshot, export

app = typer.Typer(help="Contracts K1-K19: generate and check artefacts.", no_args_is_help=True)

API_TS = Path("web/src/contracts/api.gen.ts")


def _openapi_ts(target: Path) -> None:
    root = export.REPO_ROOT
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise typer.Exit(
            code=_fail("pnpm not found; install pnpm, then `pnpm install` (needed for api.gen.ts)")
        )
    if not (root / "web" / "node_modules" / "openapi-typescript").is_dir():
        raise typer.Exit(code=_fail("web dependencies missing; run `pnpm install` at the repository root"))
    try:
        subprocess.run(  # noqa: S603
            [
                pnpm,
                "-C",
                str(root / "web"),
                "exec",
                "openapi-typescript",
                str(root / "contracts" / "openapi.json"),
                "-o",
                str(target),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()[-1:] or ["no output"]
        raise typer.Exit(code=_fail(f"openapi-typescript failed: {detail[0]}")) from exc


def _fail(message: str) -> int:
    typer.echo(message, err=True)
    return 1


DB_OPTION = typer.Option(
    None,
    "--db",
    envvar="SGW_CONTRACTS_DB_URL",
    help="migrated database for the K1 schema snapshot (contracts/db/schema.sql)",
)


@app.command("contracts")
def contracts(db: str | None = DB_OPTION) -> None:
    """Regenerate JSON Schema, OpenAPI, TS, SQL domains, vectors, golden streams and the micro-fixture."""
    for rel in export.write_all():
        typer.echo(f"wrote {rel}")
    if db:
        db_snapshot.SNAPSHOT_PATH.write_text(db_snapshot.snapshot(db), encoding="utf-8", newline="\n")
        typer.echo("wrote contracts/db/schema.sql")
    _openapi_ts(export.REPO_ROOT / API_TS)
    typer.echo(f"wrote {API_TS}")
    status = numbers_mod.run(tex=True, py=True, ts=True, do_audit=False, check=False)
    raise typer.Exit(code=status)


@app.command("contracts-check")
def contracts_check(db: str | None = DB_OPTION) -> None:
    """Fail with exit 1 when any generated contract artefact differs from a fresh export."""
    problems = export.drift()
    if db and db_snapshot.SNAPSHOT_PATH.read_text(encoding="utf-8") != db_snapshot.snapshot(db):
        problems.append("drift: contracts/db/schema.sql")
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / "api.gen.ts"
        _openapi_ts(fresh)
        committed = export.REPO_ROOT / API_TS
        if not committed.exists() or committed.read_text(encoding="utf-8") != fresh.read_text(
            encoding="utf-8"
        ):
            problems.append(f"drift: {API_TS}")
    for p in problems:
        typer.echo(p, err=True)
    status = numbers_mod.run(tex=True, py=True, ts=True, do_audit=True, check=True)
    if problems or status:
        raise typer.Exit(code=1)
    typer.echo("contracts-check: no drift")


@app.command("numbers")
def numbers(
    tex: bool = typer.Option(False, "--tex"),
    py: bool = typer.Option(False, "--py"),
    ts: bool = typer.Option(False, "--ts"),
    audit: bool = typer.Option(False, "--audit"),
    check: bool = typer.Option(False, "--check"),
) -> None:
    """K10: generate numbers.tex, numbers_gen.py and the TS numbers and policies; audit literal values."""
    if not (tex or py or ts or audit):
        tex = py = ts = True
    raise typer.Exit(code=numbers_mod.run(tex=tex, py=py, ts=ts, do_audit=audit, check=check))


if __name__ == "__main__":
    sys.exit(app())
