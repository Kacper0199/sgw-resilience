"""Seed the K18 identities into `app_user` (idempotent upsert, Argon2id hash of `DEMO_PASSWORD`)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import psycopg

from sgw.api.security import hash_password
from sgw.contracts.identities import SeedUsers, demo_password_for, load_users

USERS_PATH = Path(__file__).resolve().parents[3] / "data" / "seed" / "users.yaml"

_UPSERT = """
INSERT INTO app_user (user_id, display_name, persona, function, roles, functions, regions, domains,
                      can_approve, break_glass_eligible, password_hash)
VALUES (%(user_id)s, %(display_name)s, %(persona)s, %(function)s::sgw_approval_function, %(roles)s,
        %(functions)s::sgw_approval_function[], %(regions)s, %(domains)s::sgw_domain[], %(can_approve)s,
        %(break_glass_eligible)s, %(password_hash)s)
ON CONFLICT (user_id) DO UPDATE SET
    display_name = EXCLUDED.display_name, persona = EXCLUDED.persona, function = EXCLUDED.function,
    roles = EXCLUDED.roles, functions = EXCLUDED.functions, regions = EXCLUDED.regions,
    domains = EXCLUDED.domains, can_approve = EXCLUDED.can_approve,
    break_glass_eligible = EXCLUDED.break_glass_eligible, password_hash = EXCLUDED.password_hash
"""


DEFAULT_DEMO_PASSWORD_MIN_LENGTH = 8
LOWEST_DEMO_PASSWORD_MIN_LENGTH = 3


def demo_password_min_length(env: Mapping[str, str] | None) -> int:
    """8 by default; a local var/demo.env may lower it with DEMO_PASSWORD_MIN_LENGTH (never below 3)."""
    raw = (env or {}).get("DEMO_PASSWORD_MIN_LENGTH")
    if not raw:
        return DEFAULT_DEMO_PASSWORD_MIN_LENGTH
    return max(LOWEST_DEMO_PASSWORD_MIN_LENGTH, int(raw))


def seed_rows(
    users: SeedUsers, password: str | None, env: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    """Each persona's DEMO_PASSWORD_<USER_ID> (from `env`) wins over the shared `password`."""

    minimum = demo_password_min_length(env)

    def chosen(user_id: str) -> str:
        value = (demo_password_for(user_id, env) if env is not None else None) or password
        if not value or len(value) < minimum:
            raise ValueError(f"the demo password for {user_id} must have at least {minimum} characters")
        return value

    return [
        {
            "user_id": u.user_id,
            "display_name": u.display_name,
            "persona": u.persona,
            "function": u.function.value,
            "roles": u.roles,
            "functions": [u.function.value],
            "regions": u.regions,
            "domains": [d.value for d in u.domains],
            "can_approve": u.can_approve,
            "break_glass_eligible": u.break_glass_eligible,
            "password_hash": hash_password(chosen(u.user_id)),
        }
        for u in users.users
    ]


def seed_users(
    conninfo: str, password: str | None, path: Path = USERS_PATH, env: Mapping[str, str] | None = None
) -> int:
    rows = seed_rows(load_users(path), password, env)
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        cur.executemany(_UPSERT, rows)
    return len(rows)
