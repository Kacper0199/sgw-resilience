"""Connection settings for ingest and pipeline code. App code connects as the runtime role (`sgw_runtime`)."""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import psycopg

DEFAULT_DATABASE = "sgw"
URL_ENV = "SGW_DATABASE_URL"
OWNER_URL_ENV = "SGW_OWNER_DATABASE_URL"


def with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


def database_url(database: str | None = None) -> str:
    """`SGW_DATABASE_URL` when set (database name swapped if given), else the runtime DSN from the
    credentials that `sgw bootstrap` generated."""
    env = os.environ.get(URL_ENV)
    if env:
        return with_database(env, database) if database else env
    from sgw.cli.support import load_credentials

    return load_credentials().runtime_dsn(database or DEFAULT_DATABASE)


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, autocommit=True, application_name="sgw-ingest")


def owner_database_url(database: str | None = None) -> str:
    """Owner DSN for maintenance (`--fresh`): `SGW_OWNER_DATABASE_URL`, else the generated credentials."""
    env = os.environ.get(OWNER_URL_ENV)
    if env:
        return with_database(env, database) if database else env
    from sgw.cli.support import load_credentials

    return load_credentials().owner_dsn(database or DEFAULT_DATABASE)
