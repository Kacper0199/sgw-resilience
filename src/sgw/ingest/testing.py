"""Scratch databases for ingest and pipeline tests: created from the real migrations, owned by `sgw`, used as
the runtime role, dropped afterwards. Creation is serialised, since role grants race under pytest-xdist.
Names start with `sgw_wp07_t_`, so a test never touches a shared database."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
from psycopg import sql

PREFIX = "sgw_wp07_t_"
ADMIN_ENV = "SGW_TEST_DATABASE_URL"
CREATE_LOCK = 0x5347_57FF


class NoDatabase(RuntimeError):
    pass


@dataclass(frozen=True)
class ScratchDb:
    name: str
    runtime_url: str
    admin_url: str


def _admin_url() -> str:
    env = os.environ.get(ADMIN_ENV)
    if env:
        return env
    from sgw.cli.support import CliError, load_credentials

    try:
        return load_credentials().admin_dsn()
    except CliError as error:
        raise NoDatabase(str(error)) from None


def _runtime_url(database: str) -> str:
    from sgw.cli.support import load_credentials

    return load_credentials().runtime_dsn(database)


def server_available() -> str | None:
    """None when a Postgres server is reachable with the local credentials, else the reason."""
    try:
        url = _admin_url()
        with psycopg.connect(url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
    except (NoDatabase, psycopg.Error) as error:
        return f"no database server: {type(error).__name__}: {str(error).strip().splitlines()[0]}"
    return None


@contextmanager
def scratch_database(label: str = "x") -> Iterator[ScratchDb]:
    from sgw.cli.commands.database import apply_migrations

    admin = _admin_url()
    name = f"{PREFIX}{label}_{uuid.uuid4().hex[:8]}"
    base, _, _ = admin.rpartition("/")
    from_env = bool(os.environ.get(ADMIN_ENV))
    with psycopg.connect(admin, autocommit=True) as lock:
        lock.execute("SELECT pg_advisory_lock(%s)", (CREATE_LOCK,))
        try:
            if from_env:
                lock.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                from sgw.common.migrate import apply

                apply(f"{base}/{name}")
            else:
                apply_migrations(database=name, create=True)
        finally:
            lock.execute("SELECT pg_advisory_unlock(%s)", (CREATE_LOCK,))
    runtime_role = f"{name}_rt"
    runtime_url = _scratch_runtime_login(admin, name, runtime_role) if from_env else _runtime_url(name)
    try:
        yield ScratchDb(name=name, runtime_url=runtime_url, admin_url=f"{base}/{name}")
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
            if from_env:
                conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(runtime_role)))


def _scratch_runtime_login(admin: str, database: str, role: str) -> str:
    """A throwaway login in `sgw_app`: runtime privileges when only an admin URL is given."""
    import secrets
    from urllib.parse import quote

    from psycopg.conninfo import conninfo_to_dict

    password = secrets.token_urlsafe(18)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN IN ROLE sgw_app PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        conn.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(role)
            )
        )
    params = conninfo_to_dict(admin)
    host = params.get("host") or "127.0.0.1"
    port = params.get("port") or "5432"
    user, secret, db = (quote(v, safe="") for v in (role, password, database))
    return f"postgresql://{user}:{secret}@{host}:{port}/{db}"
