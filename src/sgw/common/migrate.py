"""Forward-only migration runner over `db/migrations/NNNN_<owner>_<name>.sql`.

Applied files are recorded with their SHA-256 in `public.schema_migration`; an applied file whose content
changed fails loudly (never edit an applied migration). Each file runs in its own transaction.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "db" / "migrations"
_NAME = re.compile(r"^(?P<num>\d{4})_[a-z0-9]+_[a-z0-9_]+\.sql$")


@dataclass(frozen=True)
class Migration:
    number: int
    name: str
    path: Path
    sha256: str


class MigrationError(RuntimeError):
    pass


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        m = _NAME.match(path.name)
        if not m:
            raise MigrationError(f"bad migration file name: {path.name}")
        found.append(Migration(int(m["num"]), path.name, path, hashlib.sha256(path.read_bytes()).hexdigest()))
    numbers = [m.number for m in found]
    if len(numbers) != len(set(numbers)):
        raise MigrationError("duplicate migration numbers")
    return found


LOCK_KEY = 0x5347_5730  # "SGW0": one migrator at a time per database


def apply(conninfo: str, directory: Path = MIGRATIONS_DIR) -> list[str]:
    applied_now: list[str] = []
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            applied_now = _apply_locked(conn, directory)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    return applied_now


def _apply_locked(conn: psycopg.Connection, directory: Path) -> list[str]:
    applied_now: list[str] = []
    conn.execute(
        "CREATE TABLE IF NOT EXISTS public.schema_migration ("
        " name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done: dict[str, str] = dict(conn.execute("SELECT name, sha256 FROM public.schema_migration").fetchall())
    for mig in discover(directory):
        if mig.name in done:
            if done[mig.name] != mig.sha256:
                raise MigrationError(f"{mig.name} changed after it was applied")
            continue
        with conn.transaction():
            conn.execute(mig.path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO public.schema_migration (name, sha256) VALUES (%s, %s)",
                (mig.name, mig.sha256),
            )
        applied_now.append(mig.name)
    return applied_now
