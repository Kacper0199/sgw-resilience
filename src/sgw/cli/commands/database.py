from __future__ import annotations

import functools
import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from sgw.cli.support import (
    DB_GATEWAY,
    DB_NAME,
    DB_OWNER,
    DB_RUNTIME,
    GROUP_ROLES,
    LLM_WRITER_ROLE,
    REQUIRED_EXTENSIONS,
    CliError,
    guard,
    load_credentials,
    repo_root,
)

app = typer.Typer()

MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9][a-z0-9_-]*\.sql$")
NO_TRANSACTION_MARKER = "-- sgw:no-transaction"
LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    filename    text PRIMARY KEY,
    sha256      text NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now(),
    applied_by  text NOT NULL DEFAULT current_user,
    duration_ms integer NOT NULL
)
"""
LOCK_KEY = 0x5347_5701


@dataclass(frozen=True)
class Migration:
    path: Path
    sha256: str

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def transactional(self) -> bool:
        return not self.sql.lstrip().startswith(NO_TRANSACTION_MARKER)


def checksum(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def count_statements(sql: str) -> int:
    """Statements in a SQL script, ignoring comments and semicolons inside quotes or dollar quotes."""
    count, pending, i, n = 0, False, 0, len(sql)
    while i < n:
        ch = sql[i]
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end == -1 else end + 1
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if ch in "'\"":
            end = i + 1
            while end < n:
                if sql[end] == ch:
                    if end + 1 < n and sql[end + 1] == ch:
                        end += 2
                        continue
                    break
                end += 1
            pending, i = True, end + 1
            continue
        if ch == "$":
            tag = re.match(r"\$[A-Za-z_]*\$", sql[i:])
            if tag:
                end = sql.find(tag.group(0), i + len(tag.group(0)))
                pending = True
                i = n if end == -1 else end + len(tag.group(0))
                continue
        if ch == ";":
            count += pending
            pending = False
        elif not ch.isspace():
            pending = True
        i += 1
    return count + pending


def migrations_dir() -> Path:
    return repo_root() / "db" / "migrations"


def discover_migrations(directory: Path) -> list[Migration]:
    if not directory.is_dir():
        return []
    found: list[Migration] = []
    for path in sorted(directory.iterdir()):
        if path.suffix != ".sql":
            continue
        if not MIGRATION_NAME.match(path.name):
            raise CliError(f"bad migration file name {path.name}: expected NNNN_<owner>_<name>.sql")
        migration = Migration(path, checksum(path.read_bytes()))
        if not migration.transactional and count_statements(migration.sql) != 1:
            raise CliError(
                f"{path.name}: a '{NO_TRANSACTION_MARKER}' migration must hold exactly one statement"
            )
        found.append(migration)
    numbers = [m.name[:4] for m in found]
    duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
    if duplicates:
        raise CliError(f"duplicate migration numbers: {', '.join(duplicates)}")
    return found


def plan_migrations(available: list[Migration], applied: dict[str, str]) -> list[Migration]:
    for migration in available:
        recorded = applied.get(migration.name)
        if recorded is not None and recorded != migration.sha256:
            raise CliError(f"{migration.name} changed after it was applied; add a new migration instead")
    known = {m.name for m in available}
    missing = sorted(set(applied) - known)
    if missing:
        typer.secho(f"warning: applied but not on disk: {', '.join(missing)}", fg="yellow", err=True)
    pending = [m for m in available if m.name not in applied]
    late = []
    for migration in pending:
        block = owned_range(migration.name)
        newer_in_block = [a for a in applied if owned_range(a) == block and a > migration.name]
        if newer_in_block:
            late.append(f"{migration.name} < {max(newer_in_block)}")
    if late:
        raise CliError(f"migrations older than an applied one in the same owned range: {', '.join(late)}")
    return pending


OWNED_RANGES = ((1, 99),) + tuple((lo, lo + 99) for lo in range(1000, 5100, 100))


def owned_range(name: str) -> tuple[int, int] | None:
    number = int(name[:4])
    return next(((lo, hi) for lo, hi in OWNED_RANGES if lo <= number <= hi), None)


def ensure_database(database: str) -> None:
    import psycopg
    from psycopg import sql

    creds = load_credentials()
    with psycopg.connect(creds.admin_dsn(), autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone()
        if not exists:
            admin.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(database), sql.Identifier(DB_OWNER)
                )
            )
            typer.echo(f"created database {database}")


def ensure_roles(database: str) -> None:
    """Cluster roles the migrations grant to, and the api/worker login (superuser, idempotent)."""
    import psycopg
    from psycopg import sql

    creds = load_credentials()
    with psycopg.connect(creds.admin_dsn(), autocommit=True) as admin:
        for role in GROUP_ROLES:
            admin.execute(
                sql.SQL(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {name}) THEN"
                    " CREATE ROLE {role} NOLOGIN; END IF; END $$"
                ).format(name=sql.Literal(role), role=sql.Identifier(role))
            )
        logins = (
            (DB_RUNTIME, creds.runtime_password, 30, "sgw_app"),
            (DB_GATEWAY, creds.gateway_password, 5, LLM_WRITER_ROLE),
        )
        for login, password, limit, group in logins:
            ident = sql.Identifier(login)
            exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (login,)).fetchone()
            if not exists:
                admin.execute(
                    sql.SQL("CREATE ROLE {} LOGIN CONNECTION LIMIT {}").format(ident, sql.Literal(limit))
                )
            admin.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(ident, sql.Literal(password))
            )
            admin.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), ident))
            admin.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), ident)
            )
        admin.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO sgw_readonly").format(sql.Identifier(database))
        )


def ensure_extensions(database: str) -> None:
    import psycopg
    from psycopg import sql

    creds = load_credentials()
    ensure_roles(database)
    with psycopg.connect(creds.admin_dsn(database), autocommit=True) as admin:
        for extension in REQUIRED_EXTENSIONS:
            admin.execute(
                sql.SQL("CREATE EXTENSION IF NOT EXISTS {} CASCADE").format(sql.Identifier(extension))
            )


def apply_migrations(
    database: str = DB_NAME,
    directory: Path | None = None,
    dry_run: bool = False,
    create: bool = False,
    connect: Callable[[], object] | None = None,
) -> list[str]:
    import psycopg

    available = discover_migrations(directory or migrations_dir())
    if create and not dry_run:
        ensure_database(database)
    if not dry_run:
        ensure_extensions(database)
    creds = load_credentials()
    conn = connect() if connect else psycopg.connect(creds.owner_dsn(database), autocommit=True)
    applied_now: list[str] = []
    with conn:  # type: ignore[attr-defined]
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))  # type: ignore[attr-defined]
        try:
            ledger = conn.execute("SELECT to_regclass('public.schema_migrations')").fetchone()[0]  # type: ignore[attr-defined]
            if ledger is None and not dry_run:
                conn.execute(LEDGER_DDL)  # type: ignore[attr-defined]
                ledger = "schema_migrations"
            rows = (
                conn.execute("SELECT filename, sha256 FROM public.schema_migrations").fetchall()  # type: ignore[attr-defined]
                if ledger is not None
                else []
            )
            pending = plan_migrations(available, dict(rows))
            if not pending:
                typer.echo(f"{database}: up to date ({len(rows)} applied)")
            for migration in pending:
                if dry_run:
                    typer.echo(f"would apply {migration.name}")
                    continue
                started = time.perf_counter()
                record = (
                    "INSERT INTO public.schema_migrations (filename, sha256, duration_ms) VALUES (%s, %s, %s)"
                )
                if migration.transactional:
                    with conn.transaction():  # type: ignore[attr-defined]
                        conn.execute(migration.sql)  # type: ignore[attr-defined]
                        elapsed = int((time.perf_counter() - started) * 1000)
                        conn.execute(record, (migration.name, migration.sha256, elapsed))  # type: ignore[attr-defined]
                else:
                    conn.execute(migration.sql)  # type: ignore[attr-defined]
                    elapsed = int((time.perf_counter() - started) * 1000)
                    conn.execute(record, (migration.name, migration.sha256, elapsed))  # type: ignore[attr-defined]
                applied_now.append(migration.name)
                typer.echo(f"applied {migration.name} ({elapsed} ms)")
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))  # type: ignore[attr-defined]
    return applied_now


@app.command()
@guard
def migrate(
    database: Annotated[str, typer.Option("--database", "-d", help="Target database.")] = DB_NAME,
    create: Annotated[
        bool, typer.Option("--create", help="Create the database (owner sgw) if missing.")
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="List pending migrations only.")] = False,
) -> None:
    """Apply db/migrations/NNNN_*.sql in order, once each, recorded in public.schema_migrations."""
    import psycopg

    try:
        applied = apply_migrations(database=database, dry_run=dry_run, create=create)
    except psycopg.Error as error:
        raise CliError(f"migration failed: {error}") from None
    if applied:
        typer.echo(f"{database}: {len(applied)} migration(s) applied")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _probe(checks: list[Check], name: str, action: Callable[[], str]) -> None:
    try:
        checks.append(Check(name, True, action()))
    except Exception as error:  # noqa: BLE001
        checks.append(Check(name, False, f"{type(error).__name__}: {str(error).strip().splitlines()[0]}"))


SMOKE_PROBES: list[tuple[str, tuple[str, ...], str]] = [
    ("server", (), "SELECT split_part(version(), ' on ', 1)"),
    ("preload timescaledb", (), "SELECT current_setting('shared_preload_libraries')"),
    (
        "settings",
        (),
        "SELECT 'shared_buffers=' || current_setting('shared_buffers')"
        " || ' max_connections=' || current_setting('max_connections')"
        " || ' work_mem=' || current_setting('work_mem')",
    ),
    *(
        (
            f"extension {name}",
            (f'CREATE EXTENSION IF NOT EXISTS "{name}" CASCADE',),
            f"SELECT extversion FROM pg_extension WHERE extname = '{name}'",  # noqa: S608
        )
        for name in REQUIRED_EXTENSIONS
    ),
    (
        "timescaledb hypertable",
        ("CREATE TABLE smoke_obs (observed_at timestamptz NOT NULL, v double precision)",),
        "SELECT 'hypertable ' || hypertable_id || ', created=' || created"
        " FROM create_hypertable('smoke_obs', by_range('observed_at'))",
    ),
    ("postgis", (), "SELECT ST_AsText(ST_SetSRID(ST_MakePoint(-82.55, 35.60), 4326))"),
    ("h3", (), "SELECT h3_lat_lng_to_cell(POINT(-82.55, 35.60), 7)::text"),
    ("pgrouting", (), "SELECT pgr_version()"),
    ("pgvector distance", (), "SELECT ('[1,2,3]'::vector <-> '[1,2,4]'::vector)::text"),
    (
        "vectorscale diskann",
        (
            "CREATE TABLE smoke_emb (e vector(3))",
            "CREATE INDEX smoke_emb_idx ON smoke_emb USING diskann (e vector_cosine_ops)",
        ),
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'smoke_emb_idx'",
    ),
    ("pgcrypto", (), "SELECT left(encode(digest('sgw', 'sha256'), 'hex'), 16)"),
    (
        "btree_gist exclusion",
        (
            "CREATE TABLE smoke_slot (crew int, during tstzrange,"
            " EXCLUDE USING gist (crew WITH =, during WITH &&))",
        ),
        "SELECT conname FROM pg_constraint WHERE conrelid = 'smoke_slot'::regclass AND contype = 'x'",
    ),
]


def smoke_checks(database: str) -> list[Check]:
    import psycopg

    creds = load_credentials()
    checks: list[Check] = []
    with psycopg.connect(creds.admin_dsn(database), autocommit=True) as conn:

        def probe(setup: tuple[str, ...], query: str) -> str:
            for statement in setup:
                conn.execute(statement)  # type: ignore[arg-type]
            row = conn.execute(query).fetchone()  # type: ignore[arg-type]
            if not row or row[0] is None:
                raise CliError("no result")
            return str(row[0])

        for name, setup, query in SMOKE_PROBES:
            _probe(checks, name, functools.partial(probe, setup, query))
    preload = next(c for c in checks if c.name == "preload timescaledb")
    if preload.ok and "timescaledb" not in preload.detail:
        preload.ok = False
    _probe(checks, "langgraph checkpointer", lambda: _checkpointer(creds.admin_dsn(database)))
    _probe(checks, "owner login", lambda: _owner_login(creds.owner_dsn()))
    _probe(checks, "runtime login", lambda: _owner_login(creds.runtime_dsn()))
    _probe(checks, "gateway login", lambda: _owner_login(creds.gateway_dsn()))
    return checks


def _checkpointer(dsn: str) -> str:
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(dsn) as saver:
        saver.setup()
        version = saver.conn.execute("SELECT max(v) AS v FROM checkpoint_migrations").fetchone()  # type: ignore[union-attr]
    return f"setup ok, migration v{version['v'] if version else '?'}"


def _owner_login(dsn: str) -> str:
    import psycopg

    with psycopg.connect(dsn) as conn:
        row = conn.execute("SELECT current_user, current_database()").fetchone()
    return f"{row[0]}@{row[1]}" if row else "?"


@app.command("db-smoke")
@guard
def db_smoke(
    keep: Annotated[bool, typer.Option("--keep", help="Keep the scratch database for inspection.")] = False,
) -> None:
    """Prove every extension, PostGIS, H3, routing, vectors and the LangGraph checkpointer in a scratch DB."""
    import psycopg

    creds = load_credentials()
    scratch = "sgw_smoke"
    try:
        with psycopg.connect(creds.admin_dsn(), autocommit=True) as admin:
            admin.execute(f"DROP DATABASE IF EXISTS {scratch} WITH (FORCE)")
            admin.execute(f"CREATE DATABASE {scratch}")
    except psycopg.Error as error:
        raise CliError(f"cannot reach Postgres on 127.0.0.1:5434: {error}") from None
    try:
        checks = smoke_checks(scratch)
    finally:
        if not keep:
            with psycopg.connect(creds.admin_dsn(), autocommit=True) as admin:
                admin.execute(f"DROP DATABASE IF EXISTS {scratch} WITH (FORCE)")
    width = max(len(c.name) for c in checks)
    for check in checks:
        mark = typer.style("ok  ", fg="green") if check.ok else typer.style("FAIL", fg="red")
        typer.echo(f"{mark} {check.name:<{width}}  {check.detail}")
    failed = [c for c in checks if not c.ok]
    typer.echo(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
    if failed:
        raise typer.Exit(1)
