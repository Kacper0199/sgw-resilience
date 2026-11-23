"""Prepare a bare Postgres server the way the stack's initdb does, for CI database tests.

Mirrors docker/postgres/initdb/100_sgw_roles.sh and `sgw migrate` (extensions): owner role with CREATEDB and
CREATEROLE, group roles sgw_app and sgw_readonly, runtime login in sgw_app, the owner's database with the same
grants, and every required extension. Names come from sgw.cli.support, so they cannot drift.
Admin URL: SGW_TEST_DATABASE_URL, else the local stack's superuser DSN (var/secrets). Passwords come from
SGW_DB_PASSWORD / SGW_RUNTIME_PASSWORD or are generated; they are never printed.

Usage: uv run python scripts/ci_db_setup.py [--tune] [--database N --owner R --runtime R] [--drop]
Exit 0 ready (or dropped), 1 setup failed, 2 no admin URL or server not reachable.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import time

import psycopg
from psycopg import sql

from sgw.cli.support import DB_NAME, DB_OWNER, DB_RUNTIME, GROUP_ROLES, REQUIRED_EXTENSIONS

DB_ENV = "SGW_TEST_DATABASE_URL"
SERVER_SETTINGS = {
    "idle_in_transaction_session_timeout": "30s",
    "password_encryption": "scram-sha-256",
    "timescaledb.telemetry_level": "off",
    "log_min_duration_statement": "500ms",
}


def admin_url() -> str | None:
    if os.environ.get(DB_ENV):
        return os.environ[DB_ENV]
    try:
        from sgw.cli.support import load_credentials

        return load_credentials().admin_dsn()
    except Exception:  # noqa: BLE001
        return None


def with_db(url: str, dbname: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/{dbname}"


def wait_ready(url: str, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with psycopg.connect(url, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
                return True
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                return False
            time.sleep(1)


def role_exists(conn: psycopg.Connection, role: str) -> bool:
    return conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone() is not None


def ensure_roles(conn: psycopg.Connection, owner: str, runtime: str) -> None:
    owner_pw = os.environ.get("SGW_DB_PASSWORD") or secrets.token_urlsafe(24)
    runtime_pw = os.environ.get("SGW_RUNTIME_PASSWORD") or secrets.token_urlsafe(24)
    if not role_exists(conn, owner):
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN CREATEDB CREATEROLE PASSWORD {}").format(
                sql.Identifier(owner), sql.Literal(owner_pw)
            )
        )
    for group in GROUP_ROLES:
        if not role_exists(conn, group):
            conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(group)))
    if not role_exists(conn, runtime):
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN CONNECTION LIMIT 30 IN ROLE sgw_app PASSWORD {}").format(
                sql.Identifier(runtime), sql.Literal(runtime_pw)
            )
        )


def ensure_database(conn: psycopg.Connection, database: str, owner: str, runtime: str) -> None:
    db, own, run = sql.Identifier(database), sql.Identifier(owner), sql.Identifier(runtime)
    if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone() is None:
        conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(db, own))
    conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db))
    conn.execute(sql.SQL("GRANT CONNECT, TEMPORARY ON DATABASE {} TO {}").format(db, own))
    conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, sgw_readonly").format(db, run))


def missing_extensions(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM pg_available_extensions WHERE name = ANY(%s)", (list(REQUIRED_EXTENSIONS),)
    ).fetchall()
    available = {row[0] for row in rows}
    return [name for name in REQUIRED_EXTENSIONS if name not in available]


def ensure_extensions(url: str) -> list[tuple[str, str]]:
    with psycopg.connect(url, autocommit=True) as conn:
        for name in REQUIRED_EXTENSIONS:
            conn.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS {} CASCADE").format(sql.Identifier(name)))
        return conn.execute(
            "SELECT extname, extversion FROM pg_extension WHERE extname = ANY(%s) ORDER BY extname",
            (list(REQUIRED_EXTENSIONS),),
        ).fetchall()


def tune(conn: psycopg.Connection) -> None:
    for name, value in SERVER_SETTINGS.items():
        conn.execute(sql.SQL("ALTER SYSTEM SET {} = {}").format(sql.Identifier(name), sql.Literal(value)))
    conn.execute("SELECT pg_reload_conf()")


def drop(conn: psycopg.Connection, database: str, owner: str, runtime: str) -> None:
    conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database)))
    for role in (runtime, owner):
        conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", default=DB_NAME)
    parser.add_argument("--owner", default=DB_OWNER)
    parser.add_argument("--runtime", default=DB_RUNTIME)
    parser.add_argument("--tune", action="store_true", help="apply the stack's reloadable server settings")
    parser.add_argument("--drop", action="store_true", help="drop the database and the owner/runtime roles")
    parser.add_argument("--wait", type=float, default=90.0, help="seconds to wait for the server")
    args = parser.parse_args(argv)

    url = admin_url()
    if url is None:
        print(
            f"ci_db_setup: {DB_ENV} not set and no local stack credentials. Fix: export {DB_ENV}",
            file=sys.stderr,
        )
        return 2
    if not wait_ready(url, args.wait):
        print(f"ci_db_setup: server not reachable within {args.wait:.0f}s", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            if args.drop:
                drop(conn, args.database, args.owner, args.runtime)
                print(f"ci_db_setup: dropped database {args.database} and roles {args.owner}, {args.runtime}")
                return 0
            missing = missing_extensions(conn)
            if missing:
                print(
                    f"ci_db_setup: image lacks extensions {', '.join(missing)}. "
                    "Fix: use the pinned stack image"
                )
                return 1
            if args.tune:
                tune(conn)
            ensure_roles(conn, args.owner, args.runtime)
            ensure_database(conn, args.database, args.owner, args.runtime)
        installed = ensure_extensions(with_db(url, args.database))
    except psycopg.Error as error:
        print(f"ci_db_setup: {type(error).__name__}: {str(error).strip()[:300]}", file=sys.stderr)
        return 1
    print(
        f"ci_db_setup: database {args.database} owned by {args.owner}; roles {', '.join(GROUP_ROLES)} present"
    )
    print("ci_db_setup: extensions " + ", ".join(f"{name} {version}" for name, version in installed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
